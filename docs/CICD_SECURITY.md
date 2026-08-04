# CI/CD and DevSecOps operations

Phase 09 defines the GitHub Actions control plane for ModelGuard AI. It does not authorize an AWS
deployment by itself: the retained Phase 08 bootstrap must first be applied by a human using
short-lived SSO credentials, GitHub protections must be configured, and the exact runtime contract
must pass. No workflow accepts or uses a long-lived AWS access key.

## Trust and workflow matrix

| Workflow | Trigger | AWS identity | Mutation boundary | Durable evidence |
| --- | --- | --- | --- | --- |
| `ci.yml` | pull request, protected `main`, manual | none | none | test, coverage, Bandit, dependency-audit, and redacted history-scan reports |
| `container-security.yml` | relevant pull request/`main` changes, manual | none | local runner images only | per-image inspect metadata and CycloneDX SBOM/vulnerability report |
| `terraform-plan.yml` | relevant pull request/`main` changes, manual | exact customized `demo-plan`/main/workflow plan subject | saved plan only; never apply | value-free resource/action summary plus sealed plan identity |
| `publish-images.yml` | protected manual dispatch or protected reusable call | exact `demo` environment deploy role | create-only Git-SHA ECR tags | image/SBOM/source/digest release manifest |
| `deploy-demo.yml` | protected manual dispatch on `main` | exact `demo` environment deploy role | reviewed prerequisite apply, then reviewed activation apply | plan identities, release manifest, verified inputs, smoke/deployment record, rollback evidence |

Pull-request jobs have only `contents: read`. They have no `id-token: write`, AWS credential action,
backend access, or apply command. AWS jobs declare `id-token: write` at job scope only and mask the
account ID where it is not an output. The publisher deliberately leaves that non-secret provenance
value unmasked because GitHub otherwise suppresses ECR digest job outputs containing it; the action
still validates `allowed-account-ids`, and temporary credential values remain protected. A source
commit must be the exact 40-character SHA selected by the protected `main` dispatch; mutable image
tags are never passed to Terraform.

The repository OIDC template in `.github/oidc-subject-template.json` replaces GitHub's default
subject with these ordered claims:

```json
{
  "include_claim_keys": ["repo", "ref", "environment", "workflow_ref"],
  "use_default": false,
  "use_immutable_subject": true
}
```

For a current immutable repository, every allowed subject has this exact shape:

```text
repo:<owner>@<owner-id>/<repository>@<repository-id>:ref:refs/heads/main:environment:<environment>:workflow_ref:<owner>/<repository>/<workflow-path>@refs/heads/main
```

An older repository that has not opted in uses `repo:<owner>/<repository>` as only the first
segment; every other segment remains mandatory. `github_repository_owner_id`,
`github_repository_id`, `github_oidc_use_immutable_subject`, the exact ref, all environments, and
all workflow paths are explicit validated bootstrap inputs. Never infer immutable IDs from mutable
names and never use a wildcard. Repositories created after July 15, 2026 and repositories that have
opted in or moved to immutable subjects must use the immutable setting.
For a reviewed legacy repository, change only `use_immutable_subject` to `false` in both the
bootstrap tfvars and the committed template before review; never let those two values differ.
The authoritative formats and customization semantics are in GitHub's
[OIDC reference](https://docs.github.com/en/actions/reference/security/oidc) and
[repository OIDC REST contract](https://docs.github.com/en/rest/actions/oidc).

The read-only role accepts only `terraform-plan.yml` at `refs/heads/main` in `demo-plan`. The deploy
role accepts exact subjects for `deploy-demo.yml` and direct `publish-images.yml` dispatches in
`demo`, plus the dormant `destroy-demo.yml` subject in `demo-destroy`. A reusable
`publish-images.yml` job receives the calling `deploy-demo.yml` `workflow_ref`; the local reusable
workflow is resolved from that same exact source commit. This design intentionally uses
`workflow_ref`, not a wildcard or a standalone custom claim.

Apply the subject contract in this fail-closed order:

1. Read the repository owner ID, repository ID, current immutable-subject setting, exact repository
   name, and protected workflow/ref/environment names. Put the reviewed non-secret values in the
   bootstrap tfvars.
2. Using human/SSO AWS access, review and apply the bootstrap change so IAM first trusts only the new
   exact customized subjects. Existing default-subject OIDC tokens will temporarily fail.
3. Compare Terraform outputs `github_oidc_subjects` and `github_oidc_customization` with the reviewed
   values and `.github/oidc-subject-template.json`.
4. Only then use GitHub repository settings or the repository OIDC REST endpoint to set
   `use_default=false`, the exact ordered claim list, and the matching immutable flag. Do not switch
   GitHub first. This repair does not call that API.
5. Prove the expected claim through a protected workflow before retiring any previous trust. A
   repository/ref/environment/workflow/audience mismatch must remain an IAM denial.

The optional destroy workflow is intentionally not added in Phase 09; Phase 10 continues to use the
guarded human/SSO `scripts/safe_destroy.sh` path until live deployment and teardown evidence exist.

## Required GitHub protections

Protect `main` against direct pushes and require pull requests. At minimum, require the five always-
running CI job checks:

- `CI / Format, lint, and typecheck`
- `CI / Pytest and branch coverage`
- `CI / Bandit and dependency audit`
- `CI / Full-history secret scan`
- `CI / Workflow syntax and YAML lint`

Use path-aware rules or required-workflow rules for container and Terraform checks. Do not make a
path-filtered check globally required on repositories where GitHub leaves an untriggered check in a
pending state.

Create `demo-plan` with required reviewers, no self-review/admin bypass, and only protected `main`.
It contains the read-only plan variables listed below and no secrets. Create the `demo` GitHub
Environment with all of these controls:

- required reviewers, prevent self-review, and no administrator bypass;
- deployment branches/tags restricted to protected `main` only;
- environment secrets and variables restricted to this environment;
- a hardened, ephemeral self-hosted runner carrying the labels `self-hosted`, `linux`, `x64`, and
  `modelguard-demo`, with network egress inside `DEMO_ALB_ALLOWED_CIDR`;
- GitHub Actions Runner v2.329.0 or newer on that host, as required by the reviewed Node 24 action
  releases;
- pinned Python/uv dependencies plus Docker, AWS CLI v2, `curl`, and `jq` installed on that runner;
- no general-purpose workloads or unreviewed repositories on that runner.

The AWS deployment repository must remain private while it can create raw saved-plan transfer
artifacts; `deploy-demo.yml` checks the workflow-dispatch repository payload and refuses a public
repository. If a public portfolio copy is desired, publish a secret-free mirror with deployment
workflows disabled and keep the exact OIDC-trusted deployment repository private.

Create `demo-destroy` separately with its own required reviewers, exact protected-`main` branch
restriction, and stronger confirmation procedure. Its exact OIDC subject already exists, but no
Phase 09 workflow consumes it.

Environment review is deliberately repeated at the plan, apply, publish, input-verification,
activation, smoke, and rollback boundaries. Reviewers must inspect the redacted plan artifact before
approving its corresponding apply job.

## Repository and environment configuration

Map the retained bootstrap outputs to GitHub variables; do not copy credentials into GitHub.

| Name | Scope | Meaning |
| --- | --- | --- |
| `AWS_ACCOUNT_ID` | repository, `demo-plan`, or `demo` environment | exact 12-digit demo account |
| `AWS_REGION` | repository, `demo-plan`, or `demo` environment | one reviewed commercial AWS Region |
| `AWS_PLAN_ROLE_ARN` | `demo-plan` environment | bootstrap `ci_plan_role_arn` |
| `AWS_DEPLOY_ROLE_ARN` | `demo` environment | bootstrap `ci_deploy_role_arn` |
| `TF_BACKEND_BUCKET` | repository, `demo-plan`, or `demo` environment | bootstrap `state_bucket_name` |
| `TF_BACKEND_KMS_KEY_ARN` | repository, `demo-plan`, or `demo` environment | bootstrap `state_kms_key_arn` |
| `TF_ALERT_KMS_KEY_ARN` | repository, `demo-plan`, or `demo` environment | bootstrap `alert_kms_key_arn`; same retained key, exact SNS context only |
| `TF_PERMISSION_BOUNDARY_ARN` | repository, `demo-plan`, or `demo` environment | bootstrap `permission_boundary_arn` |
| `DEMO_OWNER_TAG` | repository, `demo-plan`, or `demo` environment | reviewed non-email owner tag |
| `DEMO_ALB_ALLOWED_CIDR` | repository, `demo-plan`, or `demo` environment | exact restricted, canonical CIDR |
| `DEMO_API_ACCESS_MODE` | repository, `demo-plan`, or `demo` environment | preferred `https_token` or disclosed `http_cidr_only` |
| `DEMO_ACM_CERTIFICATE_ARN` | repository, `demo-plan`, or `demo` environment | required only for `https_token` |
| `DEMO_PREDICTION_TOKEN_SSM_ARN` | repository, `demo-plan`, or `demo` environment | SecureString ARN only; never its value |
| `DEMO_AUTO_DESTROY_DATE` | repository or `demo-plan` environment | current UTC plan date, no more than 14 days away |
| `DEMO_SMOKE_BASE_URL` | `demo` environment | exact ALB/custom-domain origin, with no path |

Configure these GitHub secrets:

| Name | Scope | Handling |
| --- | --- | --- |
| `DEMO_PREDICTION_BEARER_TOKEN` | `demo` environment only | smoke request only in `https_token` mode; never passed to Terraform, curl argv/environment, or evidence |

The HTTPS smoke script disables shell tracing before reading the secret, copies it to a non-exported
variable, unsets `PREDICTION_BEARER_TOKEN` before launching any child process, and accepts only
32–512 characters matching `[A-Za-z0-9._~-]+`. That format excludes CR, LF, controls, whitespace,
quotes, backslashes, and curl-config metacharacters. Every curl invocation places `--disable` first,
uses normal TLS verification, and has explicit connect, total-time, and zero-retry limits. The
prediction request supplies its Authorization header only through `curl --config -` on an anonymous
stdin pipe; neither argv nor the curl environment contains the token, and the local copy is cleared
after use. Smoke output and evidence contain only validated response data and value-free status.

No notification address is a Terraform or GitHub Actions input. Terraform configures the budget's
80% notification with only the non-secret exact SNS topic ARN. After the prerequisite apply creates
that budget and topic, a human with short-lived SSO credentials runs this command from an interactive
terminal:

```bash
uv run --frozen --no-sync python -m scripts.notification_enrollment enroll \
  --account-id 123456789012 \
  --region us-east-1 \
  --confirmation "ENROLL modelguard-ai notifications"
```

The command reads one mandatory SNS email address without echo, verifies the exact account, uses the
fixed topic identity, writes no file, and emits only value-free status. That one subscriber receives
both budget and drift alarms. The command refuses `GITHUB_ACTIONS=true`, refuses any pre-existing
different or additional subscriber, and requires the AWS email confirmation before the protected
deployment gate passes. Terraform owns the budget, its non-secret SNS target, and the topic lifecycle,
so demo destroy still removes them; it never owns or refreshes the email subscription. The gate uses
only `ListSubscriptionsByTopic` and never emits an endpoint.

The separately protected human/SSO operator needs only `sts:GetCallerIdentity` and SNS
list/subscribe for
`arn:aws:sns:<region>:<account>:modelguard-ai-demo-alerts`. Do not grant this enrollment operation to
an untrusted workflow or a long-lived user. The deployment workflow executes only read-only
notification checks; it does not receive the address or perform enrollment.

The deployment verifier calls SSM metadata APIs for the bearer-token parameter; it does not fetch
token bytes. In `http_cidr_only` mode, omit the ACM/token variables and bearer secret.

## Release and deployment sequence

The protected deployment is deliberately two-stage:

1. Validate the dispatch confirmation, exact protected-main SHA, model version, model-manifest hash,
   account, Region, backend, and bounded UTC destroy date.
2. Create a prerequisite plan with services disabled, seal its raw hash/source/account/Region/
   backend/workspace identity, publish a value-free review summary, and apply only that saved plan.
3. Pause before any image publication. Enroll the one mandatory SNS email subscriber interactively
   through the human/SSO command above, confirm it through AWS email, and rerun the failed value-free
   notification gate. The same topic carries budget and drift alarms; no endpoint enters the workflow
   or saved plan.
4. Build each of the API, dashboard, and monitor images once from a digest-pinned base. Scan that
   exact local image once, create a CycloneDX report, and refuse any high/critical finding before
   authenticating to ECR or pushing.
5. Push the already-scanned local images under `git-<40-character-sha>`, re-resolve the ECR digest,
   and bind source labels, Dockerfile/base digest, local image ID, SBOM hash, and ECR digest in one
   release manifest.
6. During the next protected approval pause, promote the exact seven-object model bundle and active
   pointer through the separately reviewed Phase 10 model procedure. Input verification then reads
   the pointer, downloads each exact S3 VersionId, verifies the bundle, checks ECR digests, token
   metadata, certificate hostname, and all digest-pinned runtime interfaces. The verified version,
   manifest hash, and seven VersionIds are inputs to the activation plan; Terraform refuses if its
   fresh SSM read differs.
7. Only after verification succeeds, create and review a second activation plan containing
   `repository@sha256:...` references, reverify every saved-plan identity, and apply it. No workflow
   contains `terraform -target`.
8. Wait for ECS stability, then require `/health/live`, `/health/ready`, `/version` with the exact
   model-manifest SHA, and one prediction with the expected model version. A failed smoke step fails
   the workflow.

ECR tag immutability is fail-closed. If a network/service failure leaves only part of a three-image
release published, the workflow refuses to overwrite those tags. Use a new reviewed source commit or
a separately authorized human cleanup; do not weaken repository immutability to retry in place.

The current Phase 08 runtime images do not yet satisfy activation: the API has no AWS bundle-
hydration path for its empty ECS runtime volume, the dashboard image lacks its AWS monitoring
configuration file, and the monitor lacks the one-shot `aws-run` command. The exact-image verifier
refuses the dashboard/monitor interfaces; ECS readiness and smoke remain the final API hydration
proof. Phase 10 must implement and test all three runtime paths before the first protected deploy can
pass.

## Saved-plan confidentiality and review evidence

Deployment plan/apply pairs use a same-run artifact named with `run_id` and `run_attempt`. The raw
saved plan, generated non-secret tfvars, backend configuration, and sealed identity have one-day
retention. Access remains limited to users and jobs authorized for that private repository/workflow
run. Only the corresponding apply job downloads that exact raw artifact name from its own run;
later evidence jobs consume the separate redacted identity artifact.

Terraform has no email variable or email-subscription resource. Its budget notification contains only
the non-secret exact SNS topic ARN, and the out-of-band SNS subscriber is not part of any
Terraform-managed resource. No GitHub secret is mapped to `TF_VAR_*`, and the CI renderer ignores
ambient notification variables. Therefore state and raw saved plans may carry the topic ARN but
cannot acquire the subscriber endpoint through configuration or refresh. Retention, masking, and
redaction are defense in depth, not the subscriber-protection mechanism.

The encrypted topic uses the retained bootstrap customer-managed key because AWS Budgets requires a
customer-managed key policy for encrypted SNS delivery. Its Budget and CloudWatch service-principal
statements independently require `StringEquals` for the exact source account, the exact Budget ARN
or twelve exact CloudWatch alarm ARNs, the exact SNS topic encryption context, and
`kms:ViaService = sns.<region>.amazonaws.com`. No condition contains a wildcard. The same
ViaService restriction in workload IAM is defense in depth and is not a substitute for either
key-policy condition. Reusing the already retained control-plane key avoids a second key that would
linger after demo teardown while cryptographically separating SNS and state ciphertext by
encryption context.

The plan/apply steps suppress raw Terraform diagnostics because provider errors can repeat sensitive
inputs; the value-free summary is the review surface. The apply script never renders the raw plan.
It rechecks the checked-out commit, event type, protected ref/environment, OIDC account, Region,
backend bucket/key/config hash, workspace, stage, tfvars hash, raw plan SHA-256, a maximum 24-hour
plan age, and the plan manifest. For activation it also re-reads SSM and requires the live pointer
to equal every sealed model-identity input immediately before the sole `terraform apply`. Any
mismatch refuses the mutation.

A separate 30-day artifact omits all Terraform before/after/configuration/variable values. It
contains only resource addresses/actions and the sealed plan hash, source commit, account, Region,
backend identity, workspace, workflow run, and tool versions. The trusted non-applying main plan
deletes its raw saved plan and uploads only this redacted evidence.

## Secret scanning and supply-chain pins

`ci.yml` checks out full history and runs Gitleaks 8.30.1 from the exact GHCR digest in the workflow.
The scanner uses 100% value redaction; its intermediate report is deleted, and only value-free scope
metadata is uploaded. `.github/secret-scanning-allowlist.json` is empty by default. An exception must
bind one exact fingerprint, repository-relative path, rule ID, 40-character commit, rationale of at
least 20 characters, owner, and UTC expiry date no more than 90 days away. Expired, overlong,
duplicate, unused, wildcarded, malformed, or unowned exceptions fail the gate.

External actions are pinned to immutable commits, with the upstream version retained as an inline
comment:

| Dependency | Reviewed release | Immutable pin |
| --- | --- | --- |
| `actions/checkout` | 6.0.2 | `de0fac2e4500dabe0009e67214ff5f5447ce83dd` |
| `actions/upload-artifact` | 7.0.1 | `043fb46d1a93c77aae656e7c1c64a875d1fc6a0a` |
| `actions/download-artifact` | 8.0.1 | `3e5f45b2cfb9172054b4087a40e8e0b5a5461e7c` |
| `astral-sh/setup-uv` | 8.1.0 | `08807647e7069bb48b6ef5acd8ec9567f424441b` |
| `hashicorp/setup-terraform` | 3.1.2 | `b9cd54a3c349d3f38e8881555d616ced269862dd` |
| `aws-actions/configure-aws-credentials` | 6.1.2 | `acca2b1b2070338fb9fd1ca27ecee81d687e58e5` |
| `aquasecurity/trivy-action` | 0.36.0 | `ed142fd0673e97e23eac54620cfb913e5ce36c25` |

Pin review on 2026-08-04 advanced checkout 4.2.2 to 6.0.2, upload-artifact 4.6.2 to
7.0.1, and download-artifact 4.3.0 to 8.0.1 so every GitHub-owned JavaScript action in this set uses
the current Node 24 runtime. That review raised the documented self-hosted runner floor to v2.329.0.

Actionlint is installed from source commit
`a443f344ff32813837fa49f7aa6cbc478d770e62` (release 1.7.9). Gitleaks is pinned to
`sha256:c00b6bd0aeb3071cbcb79009cb16a60dd9e0a7c60e2be9ab65d25e6bc8abbb7f`; Trivy is fixed at
0.70.0; yamllint at 1.37.1; Checkov at 3.3.9; Terraform at 1.10.5; and uv at 0.12.1. Release
Dockerfiles pin the full Python base-image digest.

For an update, open one dedicated dependency PR. Resolve the advertised version/tag to its upstream
commit or registry digest from the official project, review release notes and security advisories,
update the inline version comment and this table, then run CI, actionlint/yamllint, all image scans,
and the credentialless Terraform validation. Never replace a commit/digest with a floating tag.

## Rollback and last-known-good state

After smoke passes, the workflow writes a versioned history record and the current
`deployments/last-known-good.json` record to the private, versioned audit bucket. The record binds all
three image digests, API/dashboard/monitor task-definition ARNs, active model pointer and object
VersionIds, both reviewed plan hashes, smoke hash, source commit, and GitHub run identity.
Before creating that record, the workflow reads each task definition back from ECS and refuses any
container image that differs from its published `repository@sha256:...` identity. It also re-reads
the live SSM pointer and requires exact equality with the verified pointer before publishing the
successful runtime signal.

Activation-apply failure/cancellation, or any non-successful smoke result after a successful apply,
triggers the protected rollback job. It restores the API and dashboard services plus the scheduled
monitor target to the last-known-good task definitions and waits for service stability. ECS circuit-
breaker rollback remains enabled independently. The model pointer is never changed by this job:
model rollback is a distinct protected pointer operation. Terraform drift detection is evidence
only and never triggers either rollback.

For a model-only rollback, an operator must select the prior `active_model_pointer` from a versioned
last-known-good/history record, reverify every recorded S3 VersionId and the bundle-manifest hash,
then use the separately approved Phase 10 pointer-promotion procedure to replace only the non-secret
SSM active-pointer String. Re-run readiness, `/version`, and prediction smoke before recording that
pointer as good. Never change the pointer from this ECS rollback job, from a drift alarm, or without
the protected model review; until that procedure exists, model rollback fails closed as a manual
gate.

On the first deployment there may be no last-known-good record. In that case the rollback job fails
closed after the ECS circuit breaker has had its chance; it does not invent a model or task target.
The operator must inspect the deployment/rollback artifacts and perform a protected corrective plan
or destroy. A workflow failure must never be reclassified as success.

A failure after prerequisite apply but before activation leaves only the deliberately disabled
prerequisite infrastructure. It does not invoke a runtime rollback because no service/schedule was
activated. The run remains failed, and the operator must either correct/review a new deploy or use
the guarded Phase 10 destroy path; AutoDestroyDate is a reminder/guard, not an automatic cleanup.

## Validation boundary

Run locally:

```bash
UV_CACHE_DIR="$PWD/.cache/uv" uv run --frozen --no-sync ruff format --check .
UV_CACHE_DIR="$PWD/.cache/uv" uv run --frozen --no-sync ruff check .
UV_CACHE_DIR="$PWD/.cache/uv" uv run --frozen --no-sync mypy src \
  scripts/terraform_demo_guard.py scripts/notification_enrollment.py \
  scripts/secret_scan_policy.py scripts/plan_evidence.py \
  scripts/render_ci_terraform.py scripts/release_manifest.py \
  scripts/verify_deployment_inputs.py scripts/deployment_record.py
UV_CACHE_DIR="$PWD/.cache/uv" uv run --frozen --no-sync pytest -q
./scripts/check_shell.sh
./scripts/check_no_secrets.sh
```

Local YAML parsing and Phase 09 contract tests catch trust/permission/pinning regressions. A real
GitHub run is still required to prove GitHub expression evaluation, environment approvals, OIDC
claims, artifact transfer, hosted/self-hosted runner behavior, action downloads, and report upload.
A live Phase 10 AWS run is required to prove IAM authorization, ECR publication, saved-plan apply,
ECS stabilization, ALB reachability, smoke behavior, durable audit writes, and rollback.

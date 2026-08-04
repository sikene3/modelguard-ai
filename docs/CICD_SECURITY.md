# CI/CD and DevSecOps operations

Phase 09 defines the GitHub Actions control plane for ModelGuard AI. It does not authorize an AWS
deployment by itself: the retained Phase 08 bootstrap must first be applied by a human using
short-lived SSO credentials, GitHub protections must be configured, and the exact runtime contract
must pass. No workflow accepts or uses a long-lived AWS access key.

## Trust and workflow matrix

| Workflow | Trigger | AWS identity | Mutation boundary | Durable evidence |
| --- | --- | --- | --- | --- |
| `ci.yml` | pull request, protected `main`, manual | none | none | test, coverage, Bandit, dependency-audit, and sanitized repository-scan SARIF |
| `container-security.yml` | relevant pull request/`main` changes, manual | none | local runner images only | per-image inspect metadata, CycloneDX evidence, and sanitized SARIF |
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

Protect `main` against direct pushes and require pull requests. At minimum, require the four always-
running CI job checks:

- `CI / Format, lint, and typecheck`
- `CI / Pytest and branch coverage`
- `CI / Reproducible security release gates`
- `CI / Workflow YAML compatibility lint`

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

## Reproducible security release gates

The Phase 09.1 read-first audit classified all five scanners as **partially enforced**; none was
absent and none yet met the complete local/CI reproducibility contract:

| Scanner | Before Phase 09.1 | Repaired enforcement |
| --- | --- | --- |
| actionlint | CI-only source installation; no shared local cache or command | every workflow through the shared script, with the exact local ShellCheck binary for embedded Bash |
| ShellCheck | repository script skipped when the host binary was missing | every approved shell file plus embedded workflow Bash; a missing pinned binary fails |
| Checkov | Terraform-only workflow invocation through `uvx` | one exact OCI digest scans Terraform, Dockerfiles, and GitHub Actions with one failure policy |
| Trivy | image-only action/local critical-only paths | filesystem vulnerability/secret, configuration, and exact-image HIGH/CRITICAL gates |
| Gitleaks | CI history scan with a separate container invocation | complete history plus an approved current-worktree snapshot through one redacted shared gate |

`security/security-tools.lock.json` is the single source of truth. `scripts/security_tools.py`
strictly validates the schema and rejects floating versions, `latest`, mutable branches, missing
checksums, and unqualified OCI tags. `make security-tools-bootstrap` installs or caches only under
ignored `.cache/security-tools/`; `make security-tools-check` verifies the lock identity, installed
versions, downloaded archive hashes, extracted binary hashes, Checkov image digest, and cached OCI
archive identity. It never treats a globally installed scanner as release evidence.

`scripts/security_scan.sh` is the sole scanner command used by local gates and GitHub Actions.
`make security-scan` executes all five scanner groups through `scripts/security_gate_runner.py`,
preserves each exit status, and fails after all groups run if any tool is missing or returns nonzero.
`make release-gates` runs the full `make verify` contract followed by those shared scans. There is no
`continue-on-error`, soft-fail, or forced-zero scanner path.

The CI security job has only `contents: read` and `security-events: write`; it has no protected
environment, secret reference, OIDC permission, AWS credential step, image publication, or
deployment command. Container and publish workflows scan in similarly credentialless jobs. The
protected publisher receives the already scanned exact image archive, verifies its source,
manifest/archive hashes, and three image IDs before assuming AWS identity; it cannot rerun or bypass
the scan.

Checkov, Gitleaks, and Trivy outputs are reduced by `scripts/sanitize_sarif.py` to scanner/rule,
severity, safe repository path/line, and value-free suppression state before upload through the
pinned CodeQL SARIF action. Raw scanner output exists only in a mode-0700 ignored temporary cache and
is removed after sanitization. Scanner caches, vulnerability databases, environment dumps, raw
secret matches, Terraform plans/state, and downloaded binaries are not artifacts.

Gitleaks scans every commit with `--log-opts=--all`, then independently scans a copied approved
current-worktree snapshot. It uses 100% value redaction, disables inline `gitleaks:allow`, and emits
only sanitized SARIF. The sole historical exception in
`.github/secret-scanning-allowlist.json` binds one exact fingerprint, repository-relative path, rule
ID, 40-character commit, substantive rationale, owner, and UTC expiry; the current worktree has no
finding. Expired, overlong, duplicate, unused, wildcarded, malformed, or unowned exceptions fail.

All suppressions are version-controlled and policy-checked before their scanner runs:

| Scanner | Approved records | Boundary |
| --- | ---: | --- |
| Checkov | 50 inline directives producing 59 resource/file result-instance skips | exact finding and affected block/file, justification, owner `modelguard-maintainers`, expiry 2026-10-31 |
| ShellCheck | 6 directives | adjacent exact finding, justification, owner, expiry 2026-10-31 |
| Trivy repository config | 3 path-scoped records | exact misconfiguration ID and path, justification, owner, expiry 2026-10-31 |
| Trivy images | 0 | exact image/CVE/package registry remains empty |
| Gitleaks | 1 historical record | exact fingerprint/path/rule/commit, rationale, owner, expiry 2026-10-31 |
| Bandit release-gate helpers | 6 directives | exact Bandit IDs adjacent to fixed-command/verified-download justification, owner, and expiry 2026-10-31 |

The three repository Trivy configuration suppressions retain the reviewed demo architecture: an
internet-facing ALB still has an exact non-world CIDR; restricted-CIDR HTTP remains a disclosed
token-free fallback while HTTPS is preferred; and the teardown-safe delivery bucket keeps mandatory
SSE-S3. None suppresses a vulnerability or secret finding, and any expiry makes the gate fail.

## Supply-chain pins

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
| `github/codeql-action/upload-sarif` | 4.37.5 | `d1ba80a13dd99fba24a470575428917156a28b43` |

Pin review on 2026-08-04 advanced checkout 4.2.2 to 6.0.2, upload-artifact 4.6.2 to
7.0.1, and download-artifact 4.3.0 to 8.0.1 so every GitHub-owned JavaScript action in this set uses
the current Node 24 runtime. That review raised the documented self-hosted runner floor to v2.329.0.

| Scanner | Version | Approved artifact identity |
| --- | --- | --- |
| actionlint | 1.7.9 | release archive SHA-256 `233b280d05e100837f4af1433c7b40a5dcb306e3aa68fb4f17f8a7f45a7df7b4` |
| ShellCheck | 0.11.0 | release archive SHA-256 `8c3be12b05d5c177a04c29e3c78ce89ac86f1595681cab149b65b97c4e227198` |
| Checkov | 3.3.9 | Linux/amd64 OCI digest `sha256:3617c42277657f23ed75a554f10bce3a46867251c1c0ea2e5a1df3bad24e336f` |
| Trivy | 0.70.0 | release archive SHA-256 `8b4376d5d6befe5c24d503f10ff136d9e0c49f9127a4279fd110b727929a5aa9` |
| Gitleaks | 8.30.1 | release archive SHA-256 `551f6fc83ea457d62a0d98237cbad105af8d557003051f41f3e7ca7b3f2470eb` |

Yamllint remains locked through the Python dependency command at 1.37.1, Terraform at 1.10.5 in
workflows, and uv at 0.12.1. Release Dockerfiles pin the full Python base-image digest.

For an update, open one dedicated dependency PR. Resolve the advertised version/tag to its upstream
commit or registry digest from the official project, review release notes and security advisories,
update the lock plus inline action version comments and this table, then delete only the affected
ignored cached tool, run `make security-tools-bootstrap`, `make security-tools-check`,
`make release-gates`, all exact image scans, and credentialless Terraform validation. Never replace
a commit/checksum/digest with a floating tag.

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
make security-tools-bootstrap
make security-tools-check
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
make security-scan
make release-gates
```

The release-gate tests mutate tool pins, scanner availability/exit codes, suppression records,
workflow action pins, permissions, AWS/deployment access, image identities, and sanitized SARIF.
Local YAML parsing and Phase 09 contract tests also catch trust and permission regressions. A real
GitHub run is still required to prove GitHub expression evaluation, environment approvals, OIDC
claims, artifact transfer, hosted/self-hosted runner behavior, action downloads, and report upload.
A live Phase 10 AWS run is required to prove IAM authorization, ECR publication, saved-plan apply,
ECS stabilization, ALB reachability, smoke behavior, durable audit writes, and rollback.

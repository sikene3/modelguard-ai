# CI/CD and DevSecOps operations

Phase 09 defines the GitHub Actions control plane for ModelGuard AI. It does not authorize an AWS
deployment by itself: the retained Phase 08 bootstrap must first be applied by a human using
temporary browser-authenticated credentials, GitHub protections must be configured, and the exact runtime contract
must pass. No workflow accepts or uses a long-lived AWS access key.

## Trust and workflow matrix

| Workflow | Trigger | AWS identity | Mutation boundary | Durable evidence |
| --- | --- | --- | --- | --- |
| `ci.yml` | pull request, protected `main`, manual | none | none | test, coverage, Bandit, dependency-audit, and sanitized repository-scan SARIF |
| `container-security.yml` | relevant pull request/`main` changes, manual | none | local runner images only | per-image inspect metadata, CycloneDX evidence, and sanitized SARIF |
| `terraform-plan.yml` | relevant pull request/`main` changes, manual | exact customized `demo-plan`/main/workflow plan subject | saved plan only; never apply | value-free resource/action summary plus sealed plan identity |
| `publish-images.yml` | protected manual dispatch or team-protected reusable call rooted in manual deploy | exact `demo` environment deploy role | create-only Git-SHA ECR tags | image/SBOM/source/digest release manifest |
| `deploy-demo.yml` | protected manual dispatch on `main` | exact `demo` environment deploy role | reviewed prerequisite apply, then reviewed activation apply | plan identities, release manifest, verified inputs, smoke/deployment record, rollback evidence |
| `rollback-demo.yml` | protected manual dispatch on `main` | exact `demo` environment deploy role | exact last-known-good ECS/schedule identities only | private value-free rollback result |
| `destroy-demo.yml` | protected manual dispatch on `main` | exact `demo-destroy` environment deploy role | reviewed saved destroy plan only | redacted plan summary and private plan identity |

Pull-request jobs have only `contents: read`. They have no `id-token: write`, AWS credential action,
backend access, or apply command. AWS jobs declare `id-token: write` at job scope only and always
request GitHub's account-ID masking. A source
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
role accepts exact subjects for `deploy-demo.yml`, direct `publish-images.yml`, and
`rollback-demo.yml` in `demo`, plus `destroy-demo.yml` in `demo-destroy`. A reusable
`publish-images.yml` job receives the calling `deploy-demo.yml` `workflow_ref`; the repository-owned
entry guard additionally verifies the called job's exact `publish-images.yml` `job_workflow_ref` and
requires both identities at the same source revision. Direct dispatch requires both identities to be
`publish-images.yml`. Neither contract uses a wildcard.

Apply the subject contract in this fail-closed order:

1. Read the repository owner ID, repository ID, current immutable-subject setting, exact repository
   name, and protected workflow/ref/environment names. Put the reviewed non-secret values in the
   bootstrap tfvars.
2. Using temporary browser-authenticated AWS access, review and apply the bootstrap change so IAM first trusts only the new
   exact customized subjects. Existing default-subject OIDC tokens will temporarily fail.
3. Compare Terraform outputs `github_oidc_subjects` and `github_oidc_customization` with the reviewed
   values and `.github/oidc-subject-template.json`.
4. Only then use GitHub repository settings or the repository OIDC REST endpoint to set
   `use_default=false`, the exact ordered claim list, and the matching immutable flag. Do not switch
   GitHub first. This repair does not call that API.
5. Prove the expected claim through a protected workflow before retiring any previous trust. A
   repository/ref/environment/workflow/audience mismatch must remain an IAM denial.

Phase 10 adds explicit manual `rollback-demo.yml` and `destroy-demo.yml` boundaries. The destroy
workflow creates a private saved plan, publishes only value-free review evidence, then pauses at the
separate protected apply job. It requires the exact run identity, raw plan and identity hashes,
governance mode, source commit, environment, and mode-specific phrase. The browser-authenticated
`scripts/safe_destroy.sh` path remains a separate human-only fallback with the same mandatory mode;
omitting the mode never selects a weaker default.

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

In `team_protected`, create `demo-plan` with required reviewers, no self-review/admin bypass, and
only protected `main`.
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

Repository visibility is selected with the governance mode. `team_protected` supports the Private
deployment repository and requires a real independent reviewer. `solo_portfolio` is available only
after the controlled publication checklist passes and the repository is deliberately Public while
Actions remains disabled; it truthfully lacks separation of duties. The governance script refuses
the wrong visibility. Public conversion and Actions enablement are separate external approvals. Raw
saved plans use only the encrypted private retained-backend transfer and are never GitHub artifacts
in either mode.

Create `demo-destroy` separately with its own exact protected-`main` branch restriction and stronger
confirmation procedure. Team mode requires a real independent reviewer at every mutation gate. Solo
mode may use owner approval only after the redacted plan has been inspected and the exact reviewed
hash variables have been entered; that is a manual pause, not independent separation of duties.

Environment review is deliberately repeated at the plan, apply, publish, input-verification,
activation, smoke, and rollback boundaries. Reviewers must inspect the redacted plan artifact before
approving its corresponding apply job.

## Repository and environment configuration

Map the retained bootstrap outputs to GitHub variables; do not copy credentials into GitHub.

| Name | Scope | Meaning |
| --- | --- | --- |
| `AWS_ACCOUNT_ID` | repository plus `demo-plan`, `demo`, and `demo-destroy` as used | exact 12-digit demo account |
| `AWS_REGION` | repository plus `demo-plan`, `demo`, and `demo-destroy` as used | canonical `us-east-1` |
| `AWS_PLAN_ROLE_ARN` | `demo-plan` environment | bootstrap `ci_plan_role_arn` |
| `AWS_DEPLOY_ROLE_ARN` | `demo` and `demo-destroy` environments | bootstrap `ci_deploy_role_arn` |
| `TF_BACKEND_BUCKET` | repository plus `demo-plan`, `demo`, and `demo-destroy` as used | bootstrap `state_bucket_name` |
| `TF_BACKEND_KMS_KEY_ARN` | repository plus `demo-plan`, `demo`, and `demo-destroy` as used | bootstrap `state_kms_key_arn` |
| `TF_ALERT_KMS_KEY_ARN` | repository plus `demo-plan`, `demo`, and `demo-destroy` as used | bootstrap `alert_kms_key_arn`; same retained key, exact SNS context only |
| `TF_PERMISSION_BOUNDARY_ARN` | repository plus `demo-plan`, `demo`, and `demo-destroy` as used | bootstrap `permission_boundary_arn` |
| `DEMO_OWNER_TAG` | repository plus `demo-plan`, `demo`, and `demo-destroy` as used | reviewed non-email owner tag |
| `DEMO_ALB_ALLOWED_CIDR` | repository plus `demo-plan`, `demo`, and `demo-destroy` as used | exact restricted, canonical CIDR |
| `DEMO_API_ACCESS_MODE` | repository plus `demo-plan`, `demo`, and `demo-destroy` as used | preferred `https_token` or disclosed `http_cidr_only` |
| `DEMO_ACM_CERTIFICATE_ARN` | repository plus `demo-plan`, `demo`, and `demo-destroy` as used | required only for `https_token` |
| `DEMO_PREDICTION_TOKEN_SSM_ARN` | repository plus `demo-plan`, `demo`, and `demo-destroy` as used | SecureString ARN only; never its value |
| `DEMO_AUTO_DESTROY_DATE` | repository or `demo-plan` environment | current UTC plan date, no more than 14 days away |
| `DEMO_SMOKE_BASE_URL` | `demo` environment | exact ALB/custom-domain origin, with no path |
| `DEPLOYMENT_GOVERNANCE_MODE` | repository, `demo-plan`, `demo`, and `demo-destroy` | exact `team_protected` or `solo_portfolio`; never inferred |
| `IMAGE_TRANSFER_PUBLIC_KEY_B64` | repository | non-secret Base64 DER RSA public key used only to encrypt scanned-image transfer bytes |
| `REVIEWED_PREREQUISITE_*` | `demo` environment | exact run identity, plan hash, identity hash, and mode-specific apply phrase copied only after redacted-plan review |
| `REVIEWED_ACTIVATION_*` | `demo` environment | exact run identity, plan/identity/pointer hashes, three image digests, and mode-specific activation phrase copied only after review |
| `REVIEWED_DESTROY_*` | `demo-destroy` environment | exact destroy run identity, plan/identity hashes, and mode-specific destroy phrase copied only after review |

Configure these GitHub secrets:

| Name | Scope | Handling |
| --- | --- | --- |
| `DEMO_PREDICTION_BEARER_TOKEN` | `demo` environment only | smoke request only in `https_token` mode; never passed to Terraform, curl argv/environment, or evidence |
| `IMAGE_TRANSFER_PRIVATE_KEY_B64` | `demo` environment only | Base64 DER RSA private key supplied to the decryptor through stdin after removal from the child environment; never uploaded or logged |

`team_protected` requires a genuine independent reviewer, prevents self-review, and disables
administrator bypass. The current owner has no such reviewer, so that mode cannot be used for a live
deployment. `solo_portfolio` does not pretend otherwise: it requires the controlled Public
conversion before Actions, manual privileged entry, exact source/image/plan/confirmation evidence,
and separate plan/deploy/destroy identities. See `docs/DEPLOYMENT_GOVERNANCE.md`. Automated checks
never count as independent approval.

The HTTPS smoke script disables shell tracing before reading the secret, copies it to a non-exported
variable, unsets `PREDICTION_BEARER_TOKEN` before launching any child process, and accepts only
32–512 characters matching `[A-Za-z0-9._~-]+`. That format excludes CR, LF, controls, whitespace,
quotes, backslashes, and curl-config metacharacters. Every curl invocation places `--disable` first,
uses normal TLS verification, and has explicit connect, total-time, and zero-retry limits. The
prediction request supplies its Authorization header only through `curl --config -` on an anonymous
stdin pipe; neither argv nor the curl environment contains the token, and the local copy is cleared
after use. Smoke output and evidence contain only validated response data and value-free status.

No notification address is a Terraform or GitHub Actions input. The retained USD 10 budget is
created manually in the AWS Console with 50/80/100 percent actual and 100 percent forecast alerts;
the operator enters its endpoint only in the Console. The value-free read-only preflight verifies
the budget identity and thresholds without requesting subscribers.

After prerequisite apply creates the separate drift/alarm topic, a human with temporary browser
credentials runs this command from an interactive terminal:

```bash
uv run --frozen --no-sync python -m scripts.notification_enrollment enroll \
  --profile modelguard-bootstrap \
  --account-id 123456789012 \
  --region us-east-1 \
  --confirmation "ENROLL modelguard-ai notifications"
```

The command reads one mandatory SNS endpoint without echo, verifies the exact account, uses the
fixed topic identity, writes no file, and emits only value-free status. That subscriber receives
drift and CloudWatch alarms, not the separately retained budget alerts. The command refuses
`GITHUB_ACTIONS=true`, refuses any pre-existing
different or additional subscriber, and requires the AWS email confirmation before the protected
deployment gate passes. Terraform owns the disposable topic lifecycle but neither endpoint and not
the retained budget; demo destroy removes only the topic. The gate uses
only `ListSubscriptionsByTopic` and never emits an endpoint.

The separately protected browser-authenticated human operator needs only `sts:GetCallerIdentity` and SNS
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
   backend/workspace identity, transfer plaintext only through the encrypted retained-backend
   prefix, and publish a value-free review summary. A second protected job runs only after the
   operator records the exact reviewed run/plan/identity hashes and typed phrase, rechecks them, and
   applies only that saved plan.
3. Before any apply, verify the manually retained USD 10 budget with the value-free preflight. After
   prerequisite apply, enroll the separate drift/alarm SNS subscriber interactively, confirm it, and
   rerun the value-free notification gate. No endpoint enters the workflow or saved plan.
4. Build each of the API, dashboard, and monitor images once from a digest-pinned base. Scan that
   exact local image once, create a CycloneDX report, and refuse any high/critical finding before
   authenticating to ECR or pushing. The cross-job transfer is RSA/AES-GCM encrypted; its private
   key reaches only the protected publisher through stdin, and a Public solo repository exposes
   neither the image archive nor inspect/SBOM metadata as plaintext artifacts.
5. Push the already-scanned local images under `git-<40-character-sha>`, re-resolve the ECR digest,
   and bind source labels, Dockerfile/base digest, local image ID, SBOM hash, and ECR digest in one
   release manifest.
6. During the next protected approval pause, promote the exact seven-object model bundle and active
   pointer through the create-only `scripts.model_bundle_publisher` Phase 10 procedure. Its
   conditional lock, historical-prefix refusal, exact readback, and active/previous rollback must
   pass before input verification reads
   the pointer, downloads each exact S3 VersionId, verifies the bundle, checks ECR digests, token
   metadata, certificate hostname, and all digest-pinned runtime interfaces. The verified version,
   manifest hash, and seven VersionIds are inputs to the activation plan; Terraform refuses if its
   fresh SSM read differs.
7. Only after verification succeeds, create the second activation plan containing
   `repository@sha256:...` references. The protected apply job binds the reviewed run identity,
   plan/identity/pointer hashes, all three image digests, governance mode, and typed phrase before it
   can apply. No workflow contains `terraform -target`.
8. Wait for ECS stability, then require `/health/live`, `/health/ready`, `/version` with the exact
   model-manifest SHA, and one prediction with the expected model version. A failed smoke step fails
   the workflow.

ECR tag immutability is fail-closed. If a network/service failure leaves only part of a three-image
release published, the workflow refuses to overwrite those tags. Use a new reviewed source commit or
a separately authorized human cleanup; do not weaken repository immutability to retry in place.

The three code-only runtime paths are implemented: exact SSM/S3 API hydration, typed regional
dashboard source health, and one-shot monitor `aws-run`. The exact-image verifier executes these
interfaces and negative fail-closed probes inside each image, then emits a record bound to the source
commit and image references. Activation rendering refuses a missing, local-only, malformed, or
mismatched record. ECS readiness, IAM authorization, and live smoke remain deployment-time proof.

## Saved-plan confidentiality and review evidence

Deployment plan/apply pairs never upload a raw saved plan, tfvars, backend configuration, active
pointer, identity manifest, account/KMS/CIDR/SSM/model metadata, or image metadata as a plaintext
GitHub artifact. Raw Terraform inputs use only the encrypted, public-blocked retained state bucket at
`reviewed-plans/<run>/<attempt>/<stage>/`, with exact KMS, owner, run, attempt, and stage checks and a
one-day lifecycle. The corresponding protected apply job downloads that exact prefix and deletes it
only after success. GitHub receives only value-free resource/action summaries with a masked account
suffix. Solo release/model/runtime evidence stays in encrypted private S3; team-only artifacts are
conditioned on `team_protected`. The scanned-image cross-job transfer is authenticated ciphertext,
not a plaintext image archive or metadata directory. The ordinary container-security workflow also
withholds image inspect, SBOM, and vulnerability-detail artifacts in `solo_portfolio`; only
sanitized Code Scanning SARIF remains public-facing.

Terraform has no email variable, email-subscription resource, or AWS Budget resource. The
out-of-band drift/alarm SNS subscriber is not part of any Terraform-managed resource. No GitHub
secret is mapped to `TF_VAR_*`, and the CI renderer ignores ambient notification variables.
Therefore state and raw saved plans may carry the drift/alarm topic ARN but cannot acquire a budget
endpoint or subscriber endpoint through configuration or refresh. Retention, masking, and redaction
are defense in depth, not the endpoint-protection mechanism.

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
| Checkov | 59 inline directives producing 68 result-instance skips | exact finding and affected block/file, justification, owner `modelguard-maintainers`, expiry 2026-10-31 |
| ShellCheck | 6 directives | adjacent exact finding, justification, owner, expiry 2026-10-31 |
| Trivy repository config | 3 path-scoped records | exact misconfiguration ID and path, justification, owner, expiry 2026-10-31 |
| Trivy images | 0 | exact image/CVE/package registry remains empty |
| Gitleaks | 1 historical record | exact fingerprint/path/rule/commit, rationale, owner, expiry 2026-10-31 |
| Bandit release-gate helpers | 6 directives | exact Bandit IDs adjacent to fixed-command/verified-download justification, owner, and expiry 2026-10-31 |

The three repository Trivy configuration suppressions retain the reviewed demo architecture: an
internet-facing ALB still has an exact non-world CIDR; restricted-CIDR HTTP remains a disclosed
token-free fallback while HTTPS is preferred; and the teardown-safe delivery bucket keeps mandatory
SSE-S3. None suppresses a vulnerability or secret finding, and any expiry makes the gate fail.

The Phase 10 local audit raised GitPython from 3.1.57 to the fixed 3.1.58 floor and regenerated the
127-package lock. Streamlit's unused Git integration is additionally excluded from the dashboard
runtime image, so the production image does not carry GitPython, gitdb, or smmap. No vulnerability
suppression was added; the full hashed dependency audit and each exact-image scan remain blocking.

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
VersionIds, both reviewed plan hashes, smoke hash, source commit, GitHub run identity, and the exact
persisted deployment-governance mode.
Before creating that record, the workflow reads each task definition back from ECS and refuses any
container image that differs from its published `repository@sha256:...` identity. It also re-reads
the live SSM pointer and requires exact equality with the verified pointer before publishing the
successful runtime signal.

In team mode, activation-apply failure/cancellation, or any non-successful smoke result after a
successful apply triggers the protected rollback job. Solo mode never performs an unreviewed
automatic AWS mutation: it requires a separate `rollback-demo.yml` dispatch, exact record hash,
source, governance mode, environment, and `ROLLBACK SOLO modelguard-ai demo` phrase. Either path
restores the API and dashboard services plus the scheduled
monitor target to the last-known-good task definitions and waits for service stability. ECS circuit-
breaker rollback remains enabled independently. The model pointer is never changed by this job:
model rollback is a distinct protected pointer operation. Terraform drift detection is evidence
only and never triggers either rollback.

For a model-only rollback, an operator must select the prior `active_model_pointer` from a versioned
last-known-good/history record, reverify every recorded S3 VersionId and the bundle-manifest hash,
then use the separately approved create-only Phase 10 publisher/pointer procedure to replace only the non-secret
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
make typecheck
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

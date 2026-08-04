# Phase 09 report — GitHub Actions CI/CD and DevSecOps

> Phase 09.1 supersedes this report's original local scanner-availability and scanner-invocation
> boundary. See `reports/phase-09-1.md` and `checklists/PHASE_09_1.md` for the pinned repository-local
> toolchain, real scanner results, shared local/CI commands, and current residual live gates. The
> original Phase 09 command evidence below is retained as historical evidence, not a current claim.

## Outcome

Phase 09 implements five reviewable GitHub Actions workflows for quality/security CI, container
security, credentialless Terraform validation plus a trusted non-applying plan, immutable image
publication, and protected two-stage demo deployment. Pull-request jobs cannot obtain an AWS token
or apply infrastructure. AWS jobs use GitHub OIDC only, with `id-token: write` declared at the
individual job boundary. The repaired repository-level custom subject binds exact repository names
and, when enabled, immutable owner/repository IDs, plus main ref, protected environment, workflow
path, and audience. IAM is updated before the matching GitHub template is activated.

The implementation is locally green at 255 tests and 84.72% branch coverage. No live GitHub
workflow, OIDC exchange, AWS plan/apply, image push, deployment smoke, rollback, or destroy was
executed. Those operations remain protected Phase 10 evidence gates.

## Delivered controls

- Added `ci.yml` with locked uv synchronization, Ruff format/lint, strict Mypy, Pytest/JUnit/branch
  coverage, Bandit JSON, strict hashed pip-audit input/reporting, basic secret defense, a full-history
  digest-pinned Gitleaks scan, and pinned yamllint/actionlint validation.
- Added `container-security.yml` to build each of the three untrusted validation images once, scan
  that exact local image once with pinned Trivy, create CycloneDX evidence, and upload sanitized
  image identity without image environment values.
- Added `terraform-plan.yml` with credentialless fmt/init/validate/Checkov for pull requests. Only
  its exact main-ref workflow in `demo-plan` can assume the plan role, and that job creates but never
  applies a runtime-disabled plan. It deletes the raw plan and publishes only action/address
  evidence plus its sealed hash/source/account/Region/backend/workspace identity.
- Added `publish-images.yml` as a protected main-only manual/reusable workflow. It validates an exact
  source SHA, builds each digest-base image once, scans all three before ECR login/push, refuses an
  existing Git-SHA tag, pushes without rebuilding, re-resolves ECR digests, and emits only
  `repository@sha256:...` outputs bound to SBOM/source/Dockerfile evidence.
- Added `deploy-demo.yml` as `workflow_dispatch` only, serialized through concurrency and the
  protected `demo` environment. It applies a reviewed runtime-disabled prerequisite plan, publishes
  images, verifies ECR/model/pointer/object-version/token-metadata/certificate/runtime inputs, then
  binds that exact pointer identity into and applies a separate reviewed activation plan. It never
  uses `terraform -target`.
- Added a restricted-runner smoke gate for liveness, readiness, exact `/version` model-manifest
  identity, and one exact-model prediction. In HTTPS mode the strictly validated bearer is removed
  from the environment and supplied only through anonymous `curl --disable --config -` stdin; it
  never enters curl argv, the child environment, output, or evidence. A non-successful smoke after
  activation fails the run and invokes protected ECS/service/scheduler rollback. Model-pointer
  rollback is deliberately separate, and drift never triggers rollback.
- Added a durable, versioned last-known-good record in the audit bucket containing all three image
  digests and task definitions, the active model pointer/object versions, both plan hashes, smoke
  hash, source commit, and GitHub run identity. Record creation first verifies that every observed
  ECS task-definition image equals its published digest.
- Added a one-day raw-plan transfer boundary, an explicit 24-hour plan-age guard, and a separate
  30-day value-free review artifact. The apply script verifies event/ref/environment, current OIDC
  account, Region, backend, workspace, source, stage, tfvars hash, plan hash, manifest, age, and the
  activation pointer immediately before applying the exact saved plan. Raw Terraform plan/apply
  diagnostics are suppressed in favor of generic failures and the redacted review summary.
- Removed notification addresses from Terraform variables/resources and every saved-plan workflow.
  Terraform binds the budget's 80% notification only to the exact non-secret SNS topic ARN. A
  protected interactive human/SSO command enrolls one confirmed SNS email endpoint for both budget
  and drift alarms without writing a file or returning PII; a value-free gate refuses image
  publication until exactly one confirmed subscriber exists. The encrypted topic reuses the retained
  bootstrap customer-managed key. Its Budget and CloudWatch service-principal statements each use
  exact `StringEquals` source account, source ARN, SNS encryption-context, and regional SNS
  `kms:ViaService` restrictions, preserving delivery without creating a second lingering key.
- Added `.github/oidc-subject-template.json` and matching bootstrap inputs/outputs. Both legacy and
  current immutable repository formats are explicit; exact `StringEquals` subjects contain repo,
  ref, environment, and workflow identity with no wildcard.
- Added exact secret-scan exception validation: one fingerprint/path/rule/commit plus a substantive
  rationale, owner, and UTC expiry. Wildcards, expired/duplicate/unused entries, unmatched findings,
  and any value-bearing artifact fail closed.
- Pinned every external action to a full commit SHA, Gitleaks to a GHCR digest, Trivy/yamllint/
  Checkov/Terraform/uv to exact versions, and retained digest-pinned release base images. Update
  procedure and reviewed pins are recorded in `docs/CICD_SECURITY.md`.
- Repaired a live dependency-audit failure without an exception: replaced the unused full MLflow
  server distribution with current `mlflow-skinny`, retained the required local `MlflowClient`, and
  raised explicit patched floors for Cryptography and PyArrow. The local tracking wrapper supports
  both legacy and maintenance-mode MLflow file stores. The regenerated 127-package lock and matching
  Compose/Dockerfile provenance defaults use lock SHA-256
  `a8a841251ea3520a988d8042be7efabddcb93014f6cd24a40ffb3cf22812aefc`.
- Deliberately omitted optional `destroy-demo.yml`. The exact `demo-destroy` OIDC subject remains
  separate, but Phase 10 retains the guarded human/SSO `scripts/safe_destroy.sh` path until a live
  deployment exists to destroy and verify.

## Files changed

- Workflows: `.github/workflows/{ci,container-security,terraform-plan,publish-images,deploy-demo}.yml`.
- Scanner/lint policy: `.gitleaks.toml`, `.yamllint.yml`, and
  `.github/{oidc-subject-template,secret-scanning-allowlist}.json`.
- Deployment controls: `scripts/{ci_apply_saved_plan,deployment_record,plan_evidence,
  notification_enrollment,release_manifest,render_ci_terraform,secret_scan_policy,smoke_aws,
  verify_deployment_inputs,verify_release_runtime}.{py,sh}`, the extended
  `scripts/terraform_demo_guard.py`, and `scripts/__init__.py`.
- Tests: `tests/unit/test_phase09_cicd.py` and the extended Phase 08 Terraform contracts.
- Terraform: customized OIDC trust inputs and notification-PII-free budget/SNS ownership, plus
  activation-time exact model-pointer bindings.
- Dependency/provenance repair: `pyproject.toml`, `uv.lock`, the narrow MLflow compatibility branch
  in `src/modelguard/training/tracking.py`, `docker-compose.yml`, and the three Dockerfile lock-hash
  defaults. No image was rebuilt.
- Documentation/status: `docs/CICD_SECURITY.md`, `docs/08_AWS_DEPLOYMENT_ORDER.md`, README,
  acceptance criteria, Phase 09 checklist/status, `FILE_MANIFEST.txt`, Makefile, and this report.

## Commands and evidence

### Focused Phase 09 contracts

```text
UV_CACHE_DIR="$PWD/.cache/uv" uv run --frozen --no-sync pytest -q --no-cov \
  tests/unit/test_phase09_cicd.py
PASS — 39 passed in 1.16s.
```

The tests parse all required workflows, reject floating external actions, inspect untrusted/OIDC
permission boundaries, construct every exact bootstrap subject, and prove that repository, immutable
owner/repository IDs, ref, environment, workflow path, and audience mutations are rejected. They
also prove that notification PII cannot enter Terraform inputs or uploaded plans and exercise the
manual enrollment contract. Mutations of the actual extracted Budget and CloudWatch Terraform KMS
statements reject missing conditions, wrong SourceAccount, each wrong SourceArn, wrong SNS
encryption context, wrong ViaService service/Region, and ViaService present only in workload IAM.
The fake curl proves that bearer material travels only over config stdin, while a repository-wide
manifest scan permits its expansion only for the two hardened parent-shell reads and rejects it from
documentation or curl arguments. The suite also enforces build-scan-push order and digest
references, tests redacted plan evidence, exercises prerequisite/activation barriers, binds live
release/model identities, and requires explicit independent rollback semantics.

```text
UV_CACHE_DIR="$PWD/.cache/uv" uv run --frozen --no-sync pytest -q --no-cov -vv \
  tests/unit/test_phase09_cicd.py \
  -k 'notification_kms or workload_viaservice or repository_never_expands_prediction_bearer_token'
PASS — 23 KMS/bearer cases passed and 16 unrelated Phase 09 cases were deselected in 0.08s.
```

```text
UV_CACHE_DIR="$PWD/.cache/uv" uv run --frozen --no-sync pytest -q --no-cov \
  tests/unit/test_phase08_terraform.py tests/unit/test_phase09_cicd.py
PASS — 56 passed in 1.03s.
```

```text
UV_CACHE_DIR="$PWD/.cache/uv" uv run --frozen --no-sync pytest -q --no-cov \
  tests/integration/test_training_workflow_phase02.py
PASS — 4 passed in 1.14s; the repaired MLflow client and local tracking-store behavior remain green.
```

### Full tests and quality

```text
UV_CACHE_DIR="$PWD/.cache/uv" uv run --frozen --no-sync ruff format --check .
PASS — 176 files already formatted.

UV_CACHE_DIR="$PWD/.cache/uv" uv run --frozen --no-sync ruff check .
PASS — all checks passed.

UV_CACHE_DIR="$PWD/.cache/uv" uv run --frozen --no-sync mypy src \
  scripts/terraform_demo_guard.py scripts/secret_scan_policy.py scripts/plan_evidence.py \
  scripts/notification_enrollment.py scripts/render_ci_terraform.py scripts/release_manifest.py \
  scripts/verify_deployment_inputs.py scripts/deployment_record.py
PASS — no issues in 60 source files.

UV_CACHE_DIR="$PWD/.cache/uv" uv run --frozen --no-sync pytest -q
PASS — 255 passed in 22.85s; 84.72% branch coverage, above the 70% gate.
```

### Security and offline integrity

```text
UV_CACHE_DIR="$PWD/.cache/uv" uv run --frozen --no-sync bandit -q -r src \
  scripts/terraform_demo_guard.py scripts/notification_enrollment.py \
  scripts/secret_scan_policy.py scripts/plan_evidence.py scripts/render_ci_terraform.py \
  scripts/release_manifest.py \
  scripts/verify_deployment_inputs.py scripts/deployment_record.py
PASS — no findings, including the new deployment-control scripts.

./scripts/check_no_secrets.sh
PASS — basic repository secret/file defense passed.

./scripts/check_shell.sh
PARTIAL PASS — Bash syntax passed for all 18 shell scripts; ShellCheck was unavailable.

UV_CACHE_DIR="$PWD/.cache/uv" uv lock --check --offline
PASS — 127 locked packages resolved without modifying `uv.lock`.

uv export --quiet --all-groups --frozen --no-emit-project \
  --output-file .cache/audit-requirements.txt
uv run --frozen --no-sync pip-audit --strict --require-hashes --disable-pip \
  --progress-spinner=off --cache-dir .cache/pip-audit \
  --requirement .cache/audit-requirements.txt
PASS — no known vulnerabilities found.

UV_NO_SYNC=1 UV_CACHE_DIR="$PWD/.cache/uv" make verify-model
PASS — trusted bundle 1.0.0 verified; manifest
49cbe04bc4285fc71463d0071e3babc3a5f5c20011541a072b4844bb5c78afd9.

git diff --check
git diff --cached --check after staging the exact 56 reviewed paths
PASS — no whitespace errors, including new files that are visible only in the staged snapshot.

LC_ALL=C sort -c FILE_MANIFEST.txt; exact tracked/untracked candidate-set comparison
PASS — the 277-path manifest is sorted and exactly matches the approved project file set; the
manifest intentionally excludes itself and ignored local outputs.

Repository Arabic-character, disposable-path, future-phase scope, and bearer-argument scans
PASS — no Arabic characters or filenames, unapproved cache/temporary/generated paths, Phase 10
runtime/deployment implementation, or bearer expansion in documentation/curl arguments was found in
the approved project candidate set. Only the two hardened parent-shell reads remain.
```

The first post-run `make verify` reached pip-audit and found `cryptography 49.0.0` affected by
`CVE-2026-69247`. A direct Cryptography upgrade initially forced an old full MLflow/PyArrow
resolution with 27 additional findings; that resolution was rejected. The final minimal-client
dependency set above preserves the tested local tracking contract and removes the unused vulnerable
server stack. The final complete `make verify` passed Ruff, Mypy, 255 tests, coverage, Bandit, strict
hashed pip-audit, the repository secret/file check, and trusted-model verification.

### Original workflow and infrastructure validation boundary (superseded by Phase 09.1)

```text
Unique-key PyYAML parse plus `bash -n` of all five `.github/workflows/*.yml` files
PASS — all five documents/job maps and 76 embedded Bash blocks parsed; all lines are at most 120
characters.

Static external `uses:`/forbidden-pattern inspection
PASS — all external actions use 40-character SHAs; no `pull_request_target`, AWS access-key
variables, floating action refs, `latest` deployment tag, `terraform -target`, or PR apply path.
```

Terraform formatting passed locally with Terraform 1.15.8. Provider-backed `terraform validate`
could not complete because the required provider and module caches are absent; no `terraform init`
or download was permitted for this repair. Local actionlint, yamllint, ShellCheck, Checkov, Trivy,
and Gitleaks were unavailable and were not installed. Consequently provider-backed Terraform
validation, Checkov, actionlint/yamllint, ShellCheck, full-history Gitleaks, image builds/Trivy,
GitHub expression evaluation, artifact transfer, OIDC, and AWS permissions remain mandatory pinned
GitHub gates. Phase 08's last provider-backed result was 433 Checkov passes and zero failures, but it
is historical evidence and is not presented as a Phase 09 rerun.

## Workflow artifact paths

The following are runtime-only, Git-ignored paths created by GitHub runners; no raw plan or scanner
report was generated locally:

- `artifacts/ci/`: JUnit, coverage XML, Bandit, pip-audit, and value-free Gitleaks evidence.
- `artifacts/container-security/<component>/`: sanitized image identity and CycloneDX evidence.
- `artifacts/terraform-static/` and `artifacts/terraform-plan/`: Checkov JSON and the value-free
  trusted prerequisite-plan summary/identity.
- `artifacts/image-release/`: three SBOMs and the immutable image-release manifest; partial scan
  evidence is retained after a refusal.
- `artifacts/deploy/prerequisite/` and `artifacts/deploy/activation/`: one-day raw same-run transfers
  plus separate redacted plan summaries/identities.
- `artifacts/deploy/verified/`, `artifacts/deploy/smoke/`, and `artifacts/deploy/rollback/`: value-free
  deployment input, smoke, last-known-good, and rollback evidence.

## Decisions and assumptions

- GitHub `main`, `demo-plan`, `demo`, and `demo-destroy` protections are external settings. IAM does
  not rely on them as substitutes: the customized subject itself includes the exact repository,
  ref, environment, and workflow, while the audience is a separate exact condition. Required
  reviewers, prevented self-review, and no admin bypass remain mandatory defense in depth.
- The bootstrap IAM update must precede repository activation of the matching custom subject. The
  explicit immutable flag and owner/repository IDs accommodate GitHub's current immutable format;
  legacy mode must be a reviewed exact setting, never an assumption.
- Raw-plan deployment is restricted to a private repository by both workflow guard and documented
  operating policy. A public portfolio mirror must disable deployment workflows and is not the
  repository named by the OIDC trust subjects.
- The ALB is CIDR-restricted, so smoke uses a hardened ephemeral self-hosted runner whose egress is
  inside that CIDR. It must not be shared with untrusted repositories or general workloads.
- Terraform and the saved-plan workflows have no notification address input or email-subscription
  resource. The budget/state/plan contain only the exact non-secret SNS topic ARN. Private-repository
  workflow access plus same-run exact artifact names and one-day retention protect the remaining
  non-secret plan transfer; portfolio evidence is the separately redacted summary.
- Mandatory SNS email enrollment is a human/SSO interactive operation after prerequisite apply. The
  first workflow attempt may stop at the value-free enrollment gate; after manual enrollment and AWS
  email confirmation, a failed-job rerun can continue without moving PII through GitHub.
- The commercial AWS partition, one reviewed account/Region, default Terraform workspace, fixed demo
  resource names, and versioned audit bucket from Phase 08 remain the bounded MVP assumptions.
- GitHub Environment approval is the apply confirmation. Apply has no second typed user input because
  it consumes only the already dispatched, reviewed, sealed same-run plan and rechecks its identity
  twice.

## Residual risks and open live gates

- The current API cannot hydrate the exact bundle into its empty ECS runtime volume, the dashboard
  image lacks its AWS monitoring configuration, and the monitor lacks `aws-run`. Verification fails
  closed before activation; Phase 10 must implement/test all three rather than setting the runtime
  flag optimistically.
- No live GitHub run has proved action syntax/expression contexts, hosted runner versions, protected
  approvals, OIDC `sub` claims, artifact immutability/transfer, or pinned dependency downloads.
- No live AWS run has proved the deploy role's effective authorization, ECR behavior, remote state
  locking, plan/apply identity, S3 object versions, ECS stabilization, ALB reachability, smoke,
  audit-record writes, or rollback.
- The first activation has no earlier last-known-good record. If smoke fails, the rollback job relies
  first on the ECS circuit breaker and otherwise refuses rather than inventing rollback identities.
- Failure after prerequisite apply but before activation can leave disabled demo infrastructure;
  the workflow remains failed and requires a reviewed retry or guarded destroy.
- ECR cannot atomically publish three repositories. A partial push intentionally makes that SHA
  non-retryable without a new commit or separately authorized cleanup.
- Manual workflow cancellation after infrastructure mutation still requires operator inspection;
  cancellation/non-success conditions request rollback when GitHub continues scheduling jobs, but a
  force-cancelled run cannot guarantee that any subsequent job executes.
- The optional destroy workflow remains absent. Live teardown continues through the human/SSO
  guarded script and post-destroy verifier in Phase 10.

## Exact next manual action

Review the 56 unstaged Phase 09 paths, including this focused security repair. Do not stage, commit,
push, activate the repository OIDC template, access AWS, dispatch a workflow, or begin Phase 10
without a separate explicit authorization. When live activation is later authorized, apply and
review the matching AWS trust policy before activating the GitHub subject template, then perform the
protected manual SNS enrollment and confirmation before any deployment workflow can pass its
value-free notification gate.

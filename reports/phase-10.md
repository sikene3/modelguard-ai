# Phase 10 report — Ultra-review repair and local readiness

## Outcome

The independent Ultra findings were repaired in the preserved uncommitted worktree based on
`MGH10___________________________________` on `main`. No prior Phase 10 work was reset or
discarded. The final source, container, security, sealed-runtime, smoke, demo, and E2E gates now pass,
so the Phase 10 **local code-only readiness segment is complete**.

The overall Phase 10 controlled AWS deployment remains `in_progress` and deployment is still
**NO-GO**: its live AWS/GitHub/Terraform prerequisites and deployment checklist were not authorized
or executed. The repository's `runtime_contract_verified` Terraform default remains `false` until a
future authorized activation supplies registry-digest evidence matching the verified source and all
three images.

No GitHub setting, AWS resource, Terraform state, repository remote, commit, push, or deployment was
created or changed. Phase 11 was not started.

## Ultra findings repaired

1. **Monitor ECS configuration.** `RuntimeComponent` separates API-only exposure validation from
   monitor settings. The exact Terraform monitor environment constructs typed AWS settings without
   adding or permitting API `local_open` access. A cross-component test parses the rendered map.
2. **Firehose object names.** Terraform sets `file_extension = ".jsonl.gz"` with GZIP, the AWS
   reader accepts that exact suffix only, and a Terraform-to-reader test binds both sides.
3. **Metric identity.** EMF, dashboard health, alarms, Terraform task metadata, and tests use the
   existing exact `MonitorCompletions` metric.
4. **Locked monitoring policy.** `aws-run` exposes no `--config` override and requires canonical
   semantic policy SHA-256
   `edd3177bc4a692262858b6ec2e60a991cdce1bc844ef7eb0becac6846df56c73` before any AWS
   access. Mutations cover bins/smoothing, thresholds, sample limits, performance semantics, and
   windows.
5. **Existing bundle provenance.** An existing destination without proof of the current exact
   bucket/prefix/seven keys/VersionIds is never reused. It fails closed without serving the valid but
   unproven local bytes.
6. **Model-bucket Region.** API hydration requires `GetBucketLocation`, an explicit
   `LocationConstraint` key, explicit null only for `us-east-1`, and rejects denied, missing,
   malformed, or cross-Region results before object reads. IAM grants only that exact bucket action.
7. **Strict SSM JSON.** The pointer uses the duplicate-key-rejecting strict parser before Pydantic.
   Identical and conflicting duplicates at root and nested levels are rejected.
8. **Bounded prediction enumeration.** Listings set `MaxKeys`, bound pages and every returned entry,
   require the exact prefix, and reject malformed pages, repeated/cycling/changing tokens, duplicate
   keys, out-of-prefix keys, and pagination/entry/object overflow.
9. **Dashboard endpoint consistency.** Health probes and real S3 report reads receive the same exact
   validated `DASHBOARD_S3_ENDPOINT_URL`.
10. **Reusable publication identity.** Governance validates the real caller `workflow_ref` and
    reusable job `job_workflow_ref`, plus both immutable workflow SHAs. Direct dispatch retains its
    distinct exact identity. Tests reproduce both contexts.
11. **Solo post-plan boundary.** Separate protected apply jobs run only after saved-plan and identity
    evidence exists. The invoked verifier binds commit, run, plan and identity hashes, immutable
    images, model pointer, governance mode, and typed phrase. Solo never claims independent review.
12. **Public artifact confidentiality.** Raw Terraform files move only through the encrypted private
    retained-backend prefix; GitHub gets value-free redacted plan evidence. Image archives and
    inspect/SBOM metadata use authenticated RSA/AES-GCM ciphertext or private S3. Public solo mode
    withholds ordinary container metadata artifacts and masks account IDs.
13. **Protected destroy and mode downgrade.** `destroy-demo.yml` is a separate manual saved-plan
    review/apply workflow. Mode is mandatory and checked against tfvars and deployed Terraform
    state. The immutable last-known-good record is v2 and persists the mode, so rollback also refuses
    a repository-variable downgrade.
14. **Human AWS authentication.** Human apply, destroy, notification enrollment, and readiness paths
    require the exact `modelguard-bootstrap` browser-login profile, temporary `login` credentials,
    canonical Region, and non-root bootstrap user. Static/shared/environment credentials and root are
    rejected. Workflow checks separately require the exact OIDC deploy role session.
15. **Sealed runtime evidence.** The verifier removes the exact previous regular result before
    probing, writes only a mode-0600 temporary record after full success, fsyncs, and atomically
    renames. Schema v2, image labels, release identity, renderer, and activation bind the exact
    `uv.lock` SHA-256. Behavioral fake-Docker tests cover stale output, failed reruns, atomic mode,
    cleanup, and lock mismatch.
16. **IAM and bundle size.** Unused API `ListBucket`, `GetParameters`, and previous-pointer rights and
    the unused monitor versioned-prefix listing statement are absent. Per-file measured ceilings
    bound the seven compressed objects below 1.25 MiB; `model.joblib` is 64 KiB compressed and 4 MiB
    inflated maximum for the 1 GiB task. Boundary and decompression-bomb tests pass.
17. **Truthful evidence.** The checklist, acceptance criteria, contracts, report, status, and manifest
    distinguish passing source gates from blocked final-image/runtime/container gates. Pagination
    coverage and fresh Checkov results are recorded only after execution.

## Adversarial and cross-component coverage

New or strengthened tests prove:

- exact Terraform monitor environment, Firehose suffix, EMF/alarm/dashboard metric, and S3 endpoint
  agreement;
- strict duplicate-key pointer refusal, Region denial/mismatch, current-VersionId provenance,
  interruption cleanup, atomic rollback, compressed bounds, and decompression-memory refusal;
- bounded S3 listing pages/entries/tokens/prefix and locked monitoring-policy mutations;
- direct/reusable workflow identity, confidential artifact tamper/wrong-key refusal, real
  post-plan verifier invocation, prohibited Public artifact paths, destroy downgrade refusal,
  persisted rollback mode, and human/OIDC credential-source mutation;
- stale sealed-result invalidation, failed rerun cleanup, mode-0600 atomic publication, and lock-label
  mismatch; and
- Phase 08/09 OIDC, KMS, saved-plan, bearer-token, dependency, and release-gate regressions.

## Validation actually executed

```text
.venv/bin/pytest -q --no-cov \
  tests/integration/test_phase10_api_hydration.py \
  tests/integration/test_phase10_aws_monitoring.py \
  tests/unit/test_phase10_governance.py \
  tests/unit/test_phase10_prerequisites.py \
  tests/unit/test_phase10_runtime_readiness.py
PASS — 101 passed in 3.04s.

.venv/bin/pytest -q --no-cov \
  tests/unit/test_phase08_terraform.py \
  tests/unit/test_phase09_cicd.py \
  tests/unit/test_phase091_release_gates.py
PASS — 74 passed in 1.25s.

.venv/bin/pytest -q
PASS — 381 passed in the final release-gate run (28.48s) with branch coverage enabled; 83.87%
       total versus the unchanged 70% gate.

.venv/bin/ruff format --check src scripts tests
.venv/bin/ruff check src scripts tests
PASS — 115 files formatted; no lint findings.

make typecheck
PASS — strict Mypy, 72 source files, no issues.

make security
PASS — Bandit; strict hashed pip-audit (no known vulnerabilities); basic secret/file check.

./scripts/verify_environment.sh
uv lock --check
uv sync --all-groups --locked --offline --dry-run
PASS — Python 3.12.13, uv 0.12.1, 127 locked packages, 126 installed packages, no change.

make security-scan
PASS — pinned actionlint 1.7.9, ShellCheck 0.11.0, Checkov 3.3.9,
       Gitleaks 8.30.1, and Trivy 0.70.0 all executed through the repository-owned gate.
PASS — Bash syntax/ShellCheck: 21 tracked shell files.
PASS — Checkov Terraform: 477 passed, 0 failed, 63 skipped instances.
PASS — Checkov Dockerfiles: 317 passed, 0 failed, 3 skipped instances.
PASS — Checkov GitHub Actions: 892 passed, 0 failed, 4 skipped instances.
PASS — 61 version-controlled Checkov annotations, 7 ShellCheck suppressions,
       1 Gitleaks exception, and 3 Trivy exceptions passed owner/justification/expiry policy.
PASS — full-history/current-worktree Gitleaks and Trivy filesystem/configuration scans.

terraform fmt -recursive -check infrastructure
git diff --check
PASS. Phase 08/09/10 source-contract tests and Checkov supplied local static validation. A
provider-backed `terraform validate` was not run because this worktree has no initialized provider
directory and Terraform initialization is explicitly prohibited for this task.

make verify
make release-gates
PASS — final documented state reran the complete quality, trusted-model, dependency, secret,
       workflow, IaC, history/worktree, filesystem, and configuration gates successfully.
```

## Image/runtime/container gate — passed

The fail-closed host reset removed the conflicting Snap runtime and all authorized legacy Docker
state, then established one Ubuntu Docker Engine 29.1.3 daemon on `/run/docker.sock` with data root
`/var/lib/docker`, Buildx 0.30.1, and Compose v2.40.3. The clean-engine baseline was empty before the
ModelGuard rebuild. AppArmor, built-in seccomp, and the real Alpine
`--security-opt no-new-privileges:true` probe passed.

The final source produced these exact immutable local image IDs:

```text
sha256:86bac0330814474c913324a9cade13686d44f1a3b8f292edd13d667f3c86fc6b  component=api
sha256:1ca0bb33104afc6cbb77f23ecc3aa48ff9a6d592988fd3e3d9f70fb21cc2c8fc  component=dashboard
sha256:6d7647a901e45ecaa774cceb799df2c1d34dfdca575a86e83b5bbaf82809285b  component=monitor
```

Blocking image scans passed for all three IDs. `scripts/verify_release_runtime.sh` emitted a passing
`modelguard.runtime-contract-verification.v2` record in `local_image_id` mode, bound to source commit
`MGH10___________________________________`, the truthful dirty source revision, the three image IDs,
and `uv.lock`. The API hydration, typed dashboard AWS-health, and one-shot monitor contracts passed.

The complete local matrix then passed:

- smoke: API live/ready, dashboard healthy, and 601 persisted prediction events;
- demo: baseline drift state `healthy` followed by injected `degraded`;
- E2E: `insufficient_data`, `corrupt_bundle`, and `sink_outage`; and
- final runtime: API and dashboard healthy with loopback HTTP status `200/200`.

The reset and resume logs are sealed privately at
`${HOME}/Backups/modelguard-phase10/phase10-final-verification.nx1DW5fZ` with directory
mode 0700, file mode 0600, and a strict private checksum inventory. No secret-bearing evidence is
stored in the repository.

## Changed-path inventory

The repaired candidate set is 70 modified plus 29 new paths (99 total), with no deleted or staged
path. The five paths added specifically by the Ultra repairs are the protected destroy/rollback
workflows and confidential artifact/plan-transfer/human-login helpers; additional existing paths
were updated to bind their contracts.

Modified paths:

```text
.dockerignore
.github/workflows/ci.yml
.github/workflows/container-security.yml
.github/workflows/deploy-demo.yml
.github/workflows/publish-images.yml
.github/workflows/terraform-plan.yml
ACCEPTANCE_CRITERIA.md
ARCHITECTURE.md
FILE_MANIFEST.txt
Makefile
PROJECT_SPEC.md
README.md
checklists/PHASE_10.md
docker-compose.yml
docker/api.Dockerfile
docker/dashboard.Dockerfile
docker/monitor.Dockerfile
docs/03_SECURITY_BASELINE.md
docs/04_COST_CONTROL.md
docs/07_TROUBLESHOOTING.md
docs/08_AWS_DEPLOYMENT_ORDER.md
docs/CICD_SECURITY.md
docs/DASHBOARD_CONTRACT.md
docs/MONITORING_CONTRACT.md
docs/TERRAFORM_AWS.md
infrastructure/bootstrap/README.md
infrastructure/bootstrap/bootstrap.auto.tfvars.example
infrastructure/bootstrap/iam.tf
infrastructure/bootstrap/main.tf
infrastructure/bootstrap/outputs.tf
infrastructure/bootstrap/variables.tf
infrastructure/environments/demo/budget.tf
infrastructure/environments/demo/demo.auto.tfvars.example
infrastructure/environments/demo/ecs.tf
infrastructure/environments/demo/firehose.tf
infrastructure/environments/demo/iam.tf
infrastructure/environments/demo/outputs.tf
infrastructure/environments/demo/variables.tf
pyproject.toml
scripts/ci_apply_saved_plan.sh
scripts/deployment_record.py
scripts/notification_enrollment.py
scripts/plan_evidence.py
scripts/render_ci_terraform.py
scripts/safe_apply.sh
scripts/safe_destroy.sh
scripts/terraform_demo_guard.py
scripts/verify_release_runtime.sh
src/modelguard/api/main.py
src/modelguard/core/config.py
src/modelguard/dashboard/app.py
src/modelguard/dashboard/config.py
src/modelguard/dashboard/repository.py
src/modelguard/inference/loader.py
src/modelguard/monitoring/aws.py
src/modelguard/monitoring/cli.py
src/modelguard/monitoring/config.py
src/modelguard/monitoring/service.py
src/modelguard/monitoring/telemetry.py
src/modelguard/storage/__init__.py
tasks/phase_status.json
tests/integration/test_api_phase03.py
tests/integration/test_prediction_logging_phase04.py
tests/unit/test_dashboard_repository_parsing_phase06.py
tests/unit/test_monitoring_aws_phase05.py
tests/unit/test_phase07_local_containers.py
tests/unit/test_phase08_terraform.py
tests/unit/test_phase091_release_gates.py
tests/unit/test_phase09_cicd.py
uv.lock
```

New paths:

```text
.github/workflows/destroy-demo.yml
.github/workflows/rollback-demo.yml
docs/AWS_ACCOUNT_PREREQUISITES.md
docs/AWS_RUNTIME_CONTRACTS.md
docs/DEPLOYMENT_GOVERNANCE.md
docs/PUBLIC_RELEASE_CHECKLIST.md
infrastructure/audit-bootstrap/.terraform.lock.hcl
infrastructure/audit-bootstrap/README.md
infrastructure/audit-bootstrap/audit.auto.tfvars.example
infrastructure/audit-bootstrap/main.tf
infrastructure/audit-bootstrap/outputs.tf
infrastructure/audit-bootstrap/variables.tf
infrastructure/audit-bootstrap/versions.tf
reports/evidence/phase-10/README.md
reports/phase-10.md
scripts/aws_readiness_preflight.py
scripts/confidential_artifact.py
scripts/confidential_plan_transfer.sh
scripts/deployment_governance.py
scripts/human_aws_login.py
src/modelguard/dashboard/aws_health.py
src/modelguard/monitoring/aws_run.py
src/modelguard/runtime_contracts.py
src/modelguard/storage/versioned_bundle.py
tests/integration/test_phase10_api_hydration.py
tests/integration/test_phase10_aws_monitoring.py
tests/unit/test_phase10_governance.py
tests/unit/test_phase10_prerequisites.py
tests/unit/test_phase10_runtime_readiness.py
```

`FILE_MANIFEST.txt` contains the exact sorted 317-path approved candidate set and excludes itself by
contract.

## Remaining external blockers

- Controlled future-Public audit and separately authorized visibility change while Actions is off.
- A real independent reviewer for `team_protected`; `solo_portfolio` remains non-production.
- Manual USD 10 Budget and value-free preflight; its notification endpoint remains Console-only.
- Separate review/apply and encrypted state preservation for retained CloudTrail.
- Firehose service-subscription readiness; no fallback is authorized.
- Live GitHub environments/protections/variables/OIDC and AWS bootstrap resources.
- Immutable image/model publication, reviewed Terraform plans, live smoke, rollback, and teardown.

## Boundary confirmation

The Docker host remediation was separately authorized maintenance and did not modify the protected
repository or durable backup artifacts. No destructive reset operation was repeated during the
verification resume. No remote was added. Nothing was staged, committed, pushed, published,
deployed, or applied. No GitHub or AWS API mutation occurred. No Terraform
init/plan/apply/destroy/import/refresh/state command ran. No Phase 11 work began.

Suggested commit message after owner review:

```text
feat: complete fail-closed Phase 10 local runtime readiness
```

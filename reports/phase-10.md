# Phase 10 report — local readiness and live-blocker remediation

## Outcome

The independent Ultra findings were repaired in the commit now represented as
`aad098ccb54d51c64a48b2105992d242f1c96b09` on `main`. The source, container, security,
sealed-runtime, smoke, demo, and E2E gates passed for that baseline, so the Phase 10 **local
code-only readiness segment is complete**. A later, explicitly authorized, single pre-publication
rewrite replaced historical email metadata and host-private paths and removed obsolete
language-specific documentation. It preserved commit order, names, timestamps, messages, and the
canonical English project tree. The full original repository and corrective patch remain in a
verified private backup.

The descendant live-blocker-remediation commit
`e5095af0114a938ffb7c779904e140f1db3c49a1` pins the missing AWS browser-login dependency and
adds the controlled model-bundle publication/promotion implementation described below. Its exact
commit message is `fix: remediate Phase 10 live deployment blockers`.

The overall Phase 10 controlled AWS deployment remains `in_progress`. The browser-authenticated
non-root AWS identity and the single combined value-free Budget/Firehose preflight passed in
`us-east-1`; no subscriber endpoint was queried. The sanitized history was published once to the
Public repository, the exact active `main` ruleset and three solo environments were verified, and
Actions remain disabled. Retained audit bootstrap, OIDC/bootstrap, applies, artifact publication,
live tests, and teardown have not yet executed. One value-free audit-bootstrap saved plan was
reviewed locally and remains unapplied at the mandatory encrypted-state/human-approval boundary.
The repository's `runtime_contract_verified` Terraform default remains `false` until an activation
supplies registry-digest evidence matching the verified source and all three images.

No AWS resource, Terraform state, image/model publication, or deployment was created or changed by
either local readiness segment or the history rewrite. After the sealed Publication Audit passed,
the exact audited history was pushed once and only the contract-defined Public ruleset and three
solo environments were configured while Actions remained disabled. The later AWS calls were
read-only identity, prerequisite, collision, and saved-plan checks. No Terraform
apply/destroy/import, state mutation, or Phase 11 work occurred.

## Consolidated blocker remediation

1. **Reproducible browser login.** The operator-only `aws-operator` dependency group pins
   `awscrt==0.36.0`, exactly matching Botocore `1.43.62`. `uv.lock` carries the package URL and hashes;
   runtime Docker groups do not include it. `START_HERE.sh` synchronizes the exact lock and runs the
   network-free `scripts.human_aws_login dependency` import/metadata check before tests. No login was
   attempted.
2. **Create-only immutable publication.** `CreateOnlyModelBundlePublisher` uses the existing strict
   inspector and decompression bound locally, requires the exact versioned model bucket, obtains a
   conditional owner-verified S3 lock, refuses any current/noncurrent/delete-marker history for the
   semantic-version prefix, conditionally creates every object, uploads the checksum index last, and
   reads all seven exact VersionIds back to compare checksum, metadata, encryption, content type,
   length, and bytes. It never deletes model objects; a partial prefix is inactive and permanently
   consumed.
3. **Transactional pointer promotion.** Under the lock, the publisher snapshots and strictly parses
   active/previous, rechecks both, copies old active to previous, writes active last, and verifies each
   returned SSM version. Any attempted failure restores active then previous. If rollback cannot be
   proven, the lock is retained to block all follow-up mutation until separately reviewed repair.
4. **Secret-free interface.** The command accepts no access key, secret key, session token, bearer
   token, password, generic endpoint, or output-file argument. It writes no local file. Success emits
   only non-secret model/manifest/pointer identities, seven VersionIds, fixed parameter names, and
   status; failures emit bounded reason categories without SDK exception text.
5. **Cost and teardown.** The publisher creates no standing service. A successful run uses one small
   lock lifecycle, one prefix-history query, seven small puts/readbacks, and bounded SSM operations;
   model/lock versions remain covered by the existing demo lifecycle and guarded bucket teardown.
   The retained USD 10 monthly budget remains a warning, not a hard spending cap.

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
    review/apply workflow. Mode is mandatory and bound to the sealed tfvars and configured workflow
    mode. Destroy evidence also validates the deployment guard's saved before-value when present;
    absence after a partial apply stays recoverable without inventing deployed state. The immutable
    last-known-good record is v2 and persists the mode, so rollback also refuses a
    repository-variable downgrade.
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

## Historical baseline validation for the tree now represented by `aad098c`

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

## Historical image/runtime/container gate — current regeneration pending

The fail-closed host reset removed the conflicting Snap runtime and all authorized legacy Docker
state, then established one Ubuntu Docker Engine 29.1.3 daemon on `/run/docker.sock` with data root
`/var/lib/docker`, Buildx 0.30.1, and Compose v2.40.3. The clean-engine baseline was empty before the
ModelGuard rebuild. AppArmor, built-in seccomp, and the real Alpine
`--security-opt no-new-privileges:true` probe passed.

The pre-rewrite dirty worktree that became the local-readiness baseline produced these historical
immutable local image IDs. They are functional local evidence only; they are not current
clean-source publication provenance.

```text
sha256:86bac0330814474c913324a9cade13686d44f1a3b8f292edd13d667f3c86fc6b  component=api
sha256:1ca0bb33104afc6cbb77f23ecc3aa48ff9a6d592988fd3e3d9f70fb21cc2c8fc  component=dashboard
sha256:6d7647a901e45ecaa774cceb799df2c1d34dfdca575a86e83b5bbaf82809285b  component=monitor
```

Blocking image scans passed for all three IDs. `scripts/verify_release_runtime.sh` emitted a passing
`modelguard.runtime-contract-verification.v2` record in `local_image_id` mode. Its literal embedded
revision was the unpublished predecessor of canonical
`f66eb68c36e110e66902b3910334df7984707601` plus the truthful `-dirty` suffix; the canonical
hash was not the literal label. The record remains historical local evidence and cannot satisfy
current digest-mode activation. It also binds the three image IDs and `uv.lock`. The API hydration,
typed dashboard AWS-health, and one-shot monitor contracts passed.

The complete local matrix then passed:

- smoke: API live/ready, dashboard healthy, and 601 persisted prediction events;
- demo: baseline drift state `healthy` followed by injected `degraded`;
- E2E: `insufficient_data`, `corrupt_bundle`, and `sink_outage`; and
- final runtime: API and dashboard healthy with loopback HTTP status `200/200`.

The reset and resume logs are sealed privately at
`${HOME}/Backups/modelguard-phase10/phase10-final-verification.nx1DW5fZ` with directory
mode 0700, file mode 0600, and a strict private checksum inventory. No secret-bearing evidence is
stored in the repository.

## Baseline changed-path inventory

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

At baseline, `FILE_MANIFEST.txt` contained the exact sorted 317-path approved candidate set and
excluded itself by contract.

## Blocker-remediation validation

The descendant remediation candidate was validated without AWS credentials, AWS API calls, GitHub
mutation, publication, or Terraform state/backend access:

```text
./START_HERE.sh
PASS — required/optional tools and pinned scanner cache verified; Python 3.12.13 and uv 0.12.1;
       locked sync unchanged; browser-login dependency passed; 394 tests passed in 27.26s at
       83.50% coverage. The workflow opened no browser and made no AWS call.

uv lock --check
uv sync --all-groups --locked --offline --dry-run
uv run --frozen --no-sync python -m scripts.human_aws_login dependency
PASS — 128 locked packages resolved; the 127-package environment required no change; imported
       awscrt 0.36.0 exactly matched Botocore 1.43.62.

uv run pytest -q
PASS — 394 passed in 28.16s with branch coverage enabled; 83.50% total versus the unchanged 70%
       gate.

make release-gates
PASS — Ruff formatting/lint for 206 Python files; strict Mypy for 74 source files; 394 tests;
       Bandit; strict hashed pip-audit with no known vulnerabilities; the basic secret/file gate;
       exact model verification; and all repository security scanners.
PASS — pinned actionlint 1.7.9, ShellCheck 0.11.0, Checkov 3.3.9, Gitleaks 8.30.1, and Trivy
       0.70.0.
PASS — Checkov Terraform 477/0/63, Dockerfile 317/0/3, and GitHub Actions 892/0/4
       passed/failed/skipped; all 61 Checkov, 7 ShellCheck, 1 Gitleaks, and 3 Trivy policy
       exceptions remained valid; history/worktree and filesystem/configuration scans passed.

make shell-check
PASS — Bash syntax and pinned ShellCheck for 21 tracked shell files.

terraform fmt -recursive -check infrastructure
terraform -chdir=infrastructure/audit-bootstrap init -backend=false -input=false -lockfile=readonly
terraform -chdir=infrastructure/audit-bootstrap validate
terraform -chdir=infrastructure/bootstrap init -backend=false -input=false -lockfile=readonly
terraform -chdir=infrastructure/bootstrap validate
terraform -chdir=infrastructure/environments/demo init -backend=false -input=false -lockfile=readonly
terraform -chdir=infrastructure/environments/demo validate
PASS — Terraform 1.15.8 formatting and all three AWS-provider 6.46.0 configurations validated.
       Backend-disabled, read-only-lock initialization created only ignored local provider/module
       caches; it did not initialize a backend, read state, use credentials, or call an AWS account.

make docker-build
make scan-images
PASS — all three non-root images rebuilt from the exact new dependency lock and passed blocking
       Trivy high/critical scans:
       sha256:6de2397dcc6fed3b9a74dab5a27438def5aac91ccc152a12da39f0a04210b723 component=api
       sha256:0c2aae094c957d0192b6788d7d17efb87a97d9148a1cd5ddf7567714b8eacc8a component=dashboard
       sha256:e1408044694bb5dee8d38f0325947e13f33870b694eb3616ffed9a35c66b97a5 component=monitor

The historical verifier invocation mapped each image-reference placeholder below to its exact
component ID recorded immediately above. At that time, `git rev-parse HEAD` resolved to the
unpublished predecessor of canonical `aad098ccb54d51c64a48b2105992d242f1c96b09`; the dirty tree
was later committed as canonical `e5095af0114a938ffb7c779904e140f1db3c49a1`. The block is a
description of historical execution, not replayable current-source provenance. Keeping the
non-secret digest inventory separate avoids presenting a digest as a secret-like API key assignment
in version-controlled evidence.

SOURCE_COMMIT="$(git rev-parse HEAD)" \
RUNTIME_VERIFICATION_MODE=local_image_id \
API_IMAGE_REF=<exact api ID above> \
DASHBOARD_IMAGE_REF=<exact dashboard ID above> \
MONITOR_IMAGE_REF=<exact monitor ID above> \
RUNTIME_VERIFICATION_OUTPUT=artifacts/phase-10-evidence/local-runtime-remediation.json \
./scripts/verify_release_runtime.sh
HISTORICAL PASS — schema v2, exact local image IDs, non-root runtime contracts, the then-current
       dirty source revision (superseded by the authorized rewrite), and uv.lock SHA-256
       e7d65ff8a26e20c8f9c73f1bd0c7f7b2bbdf8162288d23a7a3b8397841078f5d.

MODELGUARD_API_PORT=18000 MODELGUARD_DASHBOARD_PORT=18501 make smoke-local
MODELGUARD_API_PORT=18000 MODELGUARD_DASHBOARD_PORT=18501 make demo-local
MODELGUARD_API_PORT=18000 MODELGUARD_DASHBOARD_PORT=18501 make e2e-local
PASS — smoke persisted 601 events; baseline and drifted stages accepted 1,000 predictions each and
       produced healthy then degraded drift; insufficient-data, corrupt-bundle, and sink-outage
       scenarios all passed.

git diff --check
FILE_MANIFEST.txt exact-inventory comparison
PASS — no whitespace errors; exact sorted 320-path repository inventory excluding the manifest.
```

The first final `make release-gates` rerun caught the report's original `api`-then-digest evidence
layout as `generic-api-key`. No secret was present. The layout was corrected to digest-first without
adding an exception or weakening policy; the full release gate was then rerun.

The first unqualified `make smoke-local` attempt refused at Docker's bind boundary because a
separately named, pre-existing local ModelGuard project occupied loopback ports 8000/8501. It did
not start the candidate containers. That older project was preserved; the candidate reran on
18000/18501 and passed. Only the candidate project's temporary containers and network were removed
after validation. The generated pre-rewrite artifacts were preserved in the verified private backup
and removed from the publication candidate. They are not present in the worktree and are not
reusable as current acceptance evidence.

The remediation changes 29 existing paths and adds 3 paths, with no deletion:

```text
.github/workflows/ci.yml
ACCEPTANCE_CRITERIA.md
FILE_MANIFEST.txt
GETTING_STARTED.md
Makefile
README.md
RUN_ORDER.txt
START_HERE.sh
checklists/PHASE_10.md
docker-compose.yml
docker/api.Dockerfile
docker/dashboard.Dockerfile
docker/monitor.Dockerfile
docs/04_COST_CONTROL.md
docs/07_TROUBLESHOOTING.md
docs/08_AWS_DEPLOYMENT_ORDER.md
docs/10_COMMANDS_CHEATSHEET.md
docs/AWS_ACCOUNT_PREREQUISITES.md
docs/AWS_RUNTIME_CONTRACTS.md
docs/CICD_SECURITY.md
docs/TERRAFORM_AWS.md
infrastructure/bootstrap/README.md
pyproject.toml
reports/evidence/phase-10/README.md
reports/phase-10.md
scripts/human_aws_login.py
tasks/phase_status.json
tests/unit/test_phase10_prerequisites.py
uv.lock
scripts/model_bundle_publisher.py (new)
src/modelguard/storage/publisher.py (new)
tests/unit/test_phase10_model_publisher.py (new)
```

## Current protected-live-path checkpoint

The checksum-verified `PUBLICATION_AUDIT_PACKAGES_AUTHORIZED_RECEIPT.json` records a complete
Publication Audit `PASS` for the canonical sanitized tree at
`22e9d2ff84545f996aa1718be7b58b5abf640197`. Repository privacy passed, the repository was verified
Public, the exact active solo `main` ruleset and three contract environments were read back, and the
audit recorded zero GitHub mutations and no displayed private values. The audited tree was pushed
once. Actions remains disabled and the GitHub OIDC subject template remains at its default until the
matching AWS trust exists.

The browser-authenticated non-root AWS identity and the single combined value-free readiness
preflight passed in `us-east-1`. The retained Budget is the exact monthly COST/USD 10 contract with
ACTUAL 50/80/100 percent and FORECASTED 100 percent notifications, all `GREATER_THAN`; Firehose is
accessible and the future demo delivery stream is absent. No subscriber endpoint was queried.

A value-free audit-bootstrap plan was produced and reviewed but **not applied**. It contains exactly
11 creates (10 tagged/namespaced AWS resources plus one `terraform_data` guard), with no update,
delete, or replacement. It is checkpoint evidence only: the required clean corrective commit changes
the source identity, so a new clean-source plan must be generated, reviewed, and sealed before any
apply. Its bounded identities are:

```text
opaque plan SHA-256:        a327f946caff85b6820e62e971cab73a9e2fe9a4dd629686d7b91c9cbda526ef
redacted summary SHA-256:   2cc70e2a35714f2001ab84cad27d5654f848b6ab34f4e17f700050e9440e11a4
plan identity SHA-256:      d18ac07399778233c8ed542ffbddb700a6b21b895610d0eeaf9c593e677019bf
```

The current `agent/phase10-live-guard-fixes` candidate hardens saved-plan identity and action
contracts, exact OIDC/browser-login identity rechecks, private create-only plan/evidence handling,
activation pointer binding, confidential transfer, partial-state destroy recovery, retained Budget
classification, inactive nonbillable ECS metadata, two-attempt teardown evidence, and exact-role
cleanup. The final independent integration review found no remaining critical or high-severity
local guard defect. No AWS or GitHub mutation was performed by this candidate.

The exact current validation results are:

```text
uv run --frozen --no-sync pytest -q --no-cov \
  tests/unit/test_phase08_terraform.py \
  tests/unit/test_phase09_cicd.py \
  tests/unit/test_phase10_governance.py
PASS — 245 passed.

uv run ruff format --check .
uv run ruff check .
make typecheck
make shell-check
terraform fmt -check -recursive infrastructure
terraform validate (audit-bootstrap, bootstrap, and demo; backend disabled)
git diff --check
git fsck --full --strict --no-reflogs --unreachable
PASS — 208 Python files formatted; no Ruff findings; strict Mypy passed for 74 source files;
       Bash syntax and ShellCheck passed for 21 files; all three Terraform roots validated;
       whitespace and Git integrity passed.

make security
make security-scan
PASS — Bandit and hashed pip-audit passed with no known vulnerabilities; actionlint 1.7.9,
       ShellCheck 0.11.0, Checkov 3.3.9, Gitleaks 8.30.1, and Trivy 0.70.0 all exited zero.
PASS — Checkov Terraform 477/0/63, Dockerfile 317/0/3, and GitHub Actions 956/0/4
       passed/failed/skipped; full-history and worktree secret policy passed.

make release-gates
EXPECTED FAIL-CLOSED — 554 tests passed and one clean-source provenance test refused; total
       coverage was 83.51% versus the 70% gate. The generated manifest is one byte shorter because
       it truthfully records the current uncommitted source as dirty. The measured clean-source
       manifest bound is unchanged and was not weakened. A clean corrective commit and regenerated
       bundle are required before this gate can pass.

FILE_MANIFEST.txt exact inventory
private-email/path/account/language scan of the candidate diff
PASS — exact manifest parity; no untracked nonignored file; no approved account literal,
       host-private path, or non-English tracked content in the candidate diff.
```

The retained audit-bootstrap apply remains stopped before mutation. It requires both an immediate
human plan approval and an OS-encrypted state work volume with two independently encrypted offline
copies and a restore/hash verification. The current corrective candidate must first become a clean
ordinary commit so the bundle and all deployment artifacts can truthfully bind to clean source.

## Read-only continuation evidence

- AWS profile: `modelguard-bootstrap`; Region: `us-east-1`.
- Caller: non-root IAM user `modelguard-bootstrap-admin`; account shown only in masked form.
- Budget: `modelguard-ai-demo-monthly`, monthly COST, USD 10, ACTUAL 50/80/100 percent and
  FORECASTED 100 percent, all `GREATER_THAN`; missing/null AWS `ThresholdType` is normalized to the
  documented effective `PERCENTAGE`, while explicit `ABSOLUTE_VALUE` remains rejected.
- Firehose: service access is active in `us-east-1`; the exact demo stream is not pre-existing.
- Publication rewrite: one verified 12-commit rewrite completed locally; the full bundle, `.git`
  archive, commit map, and exact five-file corrective patch remain private and checksum-verified.
  No remote received the pre-sanitized history. The original history and Git metadata remain
  preserved, and the tracked corrective tree is reconstructable from the verified bundle and patch.
  The sanitized audited `main` history was later pushed once to the authorized Public repository.

## Remaining external blockers

- `solo_portfolio` remains a disclosed non-production governance mode without independent review.
- Separate review/apply and encrypted state preservation for retained CloudTrail.
- Live GitHub variables/OIDC and AWS bootstrap resources; Actions remain disabled.
- Immutable registry image/model publication, reviewed Terraform plans, live smoke, rollback, and
  teardown. Local publisher tests do not satisfy the unchecked live publication gate.

## Boundary confirmation

The Docker host remediation was separately authorized maintenance and did not modify the protected
repository or durable backup artifacts. The blocker-remediation commit is one ordinary descendant
of `aad098c`. One later pre-publication rewrite was explicitly authorized, completed against a
verified candidate, and adopted only after the exact corrective files were restored byte-for-byte;
the original history and Git metadata remain preserved, and the corrective working tree is exactly
reconstructable from the verified bundle and patch. No further rewrite is authorized. The audited
sanitized history has been pushed and the exact solo ruleset/environments configured; no image,
model, AWS resource, or deployment has been published or applied. AWS activity was limited to
browser login and read-only identity/Budget/Firehose/collision/plan checks. No Terraform
apply/destroy/import/refresh/state mutation or Phase 11 work occurred.

Authorized blocker-remediation commit message:

```text
fix: remediate Phase 10 live deployment blockers
```

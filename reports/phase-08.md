# Phase 08 Report

## Objective

Implement a secure, cost-aware, destroyable Terraform architecture for the temporary AWS demo,
including a separately retained human/SSO bootstrap trust boundary, without planning, applying,
destroying, or otherwise calling AWS.

## Completion status

**Complete — technical GO for Phase 08 and GO for independent review.** Both Terraform roots
initialize without a backend and validate against locked AWS provider 6.46.0. Checkov 3.3.9 reports
433 passed, 0 failed, and 54 narrowly justified resource-instance skips. The focused and full test,
quality, security, dependency, shell, secret, trusted-bundle, manifest, language, and scope gates
pass. Phase 08 is recorded as `completed`.

This does not authorize Phase 09 by itself. The complete uncommitted Phase 08 diff still requires an
independent human review and a manual commit. Runtime activation also remains fail-closed until the
exact image digests prove the separately documented AWS startup contracts.

No Terraform plan, apply, destroy, AWS CLI command, IAM mutation, image push, model promotion, or
other live cloud operation was executed.

## Scope completed

- Added a separate bootstrap root for the versioned, KMS-encrypted, public-blocked, TLS-only remote
  state bucket with native S3 lockfiles, GitHub OIDC provider, exact-subject plan/deploy roles, and a
  mandatory workload permission boundary. Retained bootstrap resources use `prevent_destroy` and
  cannot be managed by disposable demo state.
- Added reusable network, data-plane, and ECS-service modules plus a demo root with hard account,
  Region, project, environment, backend, workspace, stage, tag, budget, ingress, image, model, and
  runtime-contract preconditions.
- Added a two-AZ VPC with public ALB and private ECS subnets, no task public IPs, one documented
  non-HA NAT gateway, an exact-bucket S3 gateway endpoint, and ALB-security-group-to-task-port-only
  ingress.
- Added private/versioned/lifecycle-managed model, prediction, report, and ALB-audit buckets; three
  immutable scan-on-push ECR repositories; and GZIP Firehose delivery into physical UTC partitions.
- Added ECS API/dashboard services, a one-shot monitor task definition, ALB listeners/rules/health
  checks, circuit-breaker rollback, finite log groups, EventBridge Scheduler, encrypted SNS,
  optional drift subscription, and a mandatory small AWS Budget notification.
- Added exact active/previous SSM model pointers with a promotion-owned value lifecycle. The initial
  value is an unset sentinel; activation requires semantic model and manifest identities plus all
  seven exact S3 VersionIds.
- Added preferred `https_token` and disclosed `http_cidr_only` modes. HTTPS accepts only a same-
  account/Region/path SecureString ARN and injects bytes through ECS `secrets.valueFrom`; Terraform
  never reads or accepts token bytes. World, IPv6, malformed, and noncanonical ALB CIDRs fail.
- Added separate CI plan, CI deploy, ECS execution, API, dashboard, monitor, Firehose, and Scheduler
  roles. Workload roles have the retained boundary; `iam:PassRole` is split by exact role and service.
- Added a machine-readable eleven-alarm source matrix covering native ALB, Firehose, and Scheduler
  metrics plus API/monitor EMF metrics. Missing monitor heartbeats breach; sparse API failures do
  not. Container Insights remains deliberately disabled and supplies no alarm.
- Added guarded saved-plan seal/verify logic, fixed-name manual apply/destroy scripts, and a fail-
  closed post-destroy verifier combining tag inventory with service-specific AWS queries.
- Added two-stage activation: prerequisites default API/dashboard desired count to zero and disable
  Scheduler; activation requires reviewed ECR digests, exact pointer/bundle, access prerequisites,
  and `runtime_contract_verified=true`. No ad hoc targeting path exists.
- Added `ReportFreshnessSeconds` to the single monitor completion EMF record and regression coverage.
- Added architecture, inventory, ownership, IAM, deployment order, variables, alarm sources, cost,
  teardown, retained-inventory, final-bootstrap-cleanup, and Region/service-assumption documentation.

## Activation contract finding

The Terraform monitor task intentionally invokes `aws-run`, but the current Phase 07 monitor image
exposes only local `run` and `status` commands. Implementing AWS one-shot orchestration is outside
Phase 08's infrastructure-only boundary. This is now documented explicitly, and activation fails
closed because `runtime_contract_verified` defaults to false and must be proven for the exact image
digest before the schedule can be enabled. Phase 10 must not set that variable until a later phase
implements and tests `aws-run`, API AWS model bootstrap, and dashboard AWS reads.

## Files changed

- Bootstrap: `infrastructure/bootstrap/{versions,variables,main,iam,outputs}.tf`, its provider lock,
  README, and non-secret variables example.
- Demo environment: provider lock, backend, versions, variables, locals/guards, network/data
  composition, IAM, Firehose, ECS, pointers, ALB, Scheduler, observability, budget, outputs, and
  non-secret examples under `infrastructure/environments/demo/`.
- Modules: `infrastructure/modules/{network,data_plane,ecs_service}/`.
- Static contract: `infrastructure/alarm-sources.json` and
  `tests/unit/test_phase08_terraform.py`.
- Operations: `scripts/terraform_demo_guard.py`, `scripts/safe_apply.sh`, the expanded
  `scripts/safe_destroy.sh`, and `scripts/verify_aws_teardown.sh`.
- Telemetry: `src/modelguard/monitoring/telemetry.py` and its Phase 05 report regression test.
- Documentation/records: `docs/TERRAFORM_AWS.md`, `docs/08_AWS_DEPLOYMENT_ORDER.md`, README,
  acceptance criteria, Phase 08 checklist/status, manifest, Git ignores, and this report.

## Commands and evidence

### Terraform formatting

```text
/snap/terraform/current/terraform fmt -recursive infrastructure
PASS — final Terraform files formatted.

/snap/terraform/current/terraform fmt -check -recursive infrastructure
PASS — exit 0 with Terraform v1.15.8.
```

### Safe local initialization and validation

```text
/snap/terraform/current/terraform -chdir=infrastructure/bootstrap init -backend=false -input=false
PASS — hashicorp/aws 6.46.0 installed and a complete provider lock was generated.

/snap/terraform/current/terraform -chdir=infrastructure/bootstrap validate
PASS — configuration valid.

/snap/terraform/current/terraform -chdir=infrastructure/environments/demo init -backend=false \
  -input=false
PASS — local modules and hashicorp/aws 6.46.0 initialized; the independently generated provider
lock is byte-identical to the bootstrap lock.

/snap/terraform/current/terraform -chdir=infrastructure/environments/demo validate
PASS — configuration valid with no warning. The first provider-backed attempt correctly exposed two
invalid `setequals` calls and deprecated `data.aws_region.current.name` references; they were
repaired using exact set equality and the provider-v6 `region` attribute before this final pass.

checkov 3.3.9 -d infrastructure --compact --quiet --skip-download
PASS — 433 passed, 0 failed, 54 resource-instance skips.
```

The initial Checkov run reported 52 failures because intended exceptions were outside their resource
blocks, plus a fixed Fargate platform version. The final tree uses `LATEST` for API, dashboard, and
scheduled-monitor Fargate execution and binds every exception inside the exact affected resource.
There is no repository-wide skip configuration or policy weakening. The 54 skipped instances are
the expanded results of documented temporary-demo decisions: AWS-managed encryption where a
disposable customer key would linger, finite rather than one-year logs, activation-gated alarm
actions, single-Region/no-WAF/no-flow-log choices, the disclosed token-free HTTP fallback, private
ALB-to-task HTTP after TLS termination, non-secret String model pointers, module-output graph false
positives, standard KMS key-policy semantics, and unavoidable generated-ID IAM scope.

Neither initialization nor validation had AWS credentials, initialized a backend, refreshed state,
created a plan, or called an AWS API. Generated `.terraform/` working metadata is Git-ignored and is
removed before staging; the reviewed `.terraform.lock.hcl` files are commit candidates.

### Focused and full tests

```text
UV_CACHE_DIR="$PWD/.cache/uv" uv run --frozen --no-sync pytest -q --no-cov \
  tests/unit/test_phase08_terraform.py tests/unit/test_monitoring_reports_phase05.py
PASS — 26 passed in 0.87s.

UV_CACHE_DIR="$PWD/.cache/uv" uv run --frozen --no-sync pytest -q
PASS — 216 passed in 18.91s; 84.74% branch coverage, above the 70% gate.
```

The Phase 08 tests cover CIDR refusal, every activation barrier, token-ARN-only handling, saved-plan
tamper/identity/expiry behavior, default-off runtime derivation, exact OIDC/boundary/PassRole scope,
alarm-source provenance and missing-data policy, bootstrap/demo ownership separation, post-destroy
residual detection, network/storage/runtime contracts, and operator confirmation refusal paths.

### Quality and security checks

```text
UV_CACHE_DIR="$PWD/.cache/uv" uv run --frozen --no-sync ruff format --check .
PASS — 165 files already formatted.

UV_CACHE_DIR="$PWD/.cache/uv" uv run --frozen --no-sync ruff check .
PASS — all checks passed.

UV_CACHE_DIR="$PWD/.cache/uv" uv run --frozen --no-sync mypy \
  src scripts/terraform_demo_guard.py
PASS — no issues in 53 source files.

UV_CACHE_DIR="$PWD/.cache/uv" uv run --frozen --no-sync bandit -q -r \
  src scripts/terraform_demo_guard.py
PASS — no findings.

./scripts/check_shell.sh
PASS — Bash syntax and ShellCheck 0.11.0 passed for all 15 shell scripts. One JMESPath literal is
documented with a line-local SC2016 directive because its backticks belong to AWS CLI query syntax.

jq -e . infrastructure/alarm-sources.json
PASS — strict parse succeeded.

./scripts/check_no_secrets.sh
PASS — basic repository secret/file defense-in-depth scan passed.

git diff --check
PASS — no whitespace errors.

make verify
PASS — Ruff checked 165 files; strict Mypy passed 52 application source files; 216 tests passed at
84.74% branch coverage; Bandit had no findings; strict hashed `pip-audit` found no known
vulnerabilities; the secret/file defense passed; and the trusted Phase 02 bundle verified as model
1.0.0 with manifest `49cbe04bc4285fc71463d0071e3babc3a5f5c20011541a072b4844bb5c78afd9`.

uv lock --check --offline
PASS — all 159 locked packages resolved without changing `uv.lock`.
```

### Dependency audit

```text
UV_CACHE_DIR=/tmp/modelguard-phase08-uv-cache uv export --quiet --all-groups --frozen \
  --no-emit-project --output-file /tmp/modelguard-phase08-audit-requirements.txt
PASS — strict hashed requirements exported.

UV_CACHE_DIR=/tmp/modelguard-phase08-uv-cache uv run --frozen --no-sync pip-audit --strict \
  --require-hashes --disable-pip --progress-spinner=off \
  --cache-dir /tmp/modelguard-phase08-pip-audit-cache \
  --requirement /tmp/modelguard-phase08-audit-requirements.txt
PASS — no known vulnerabilities found.
```

## Generated artifacts

- `infrastructure/alarm-sources.json` — committed static alarm/source contract.
- `infrastructure/bootstrap/.terraform.lock.hcl` and
  `infrastructure/environments/demo/.terraform.lock.hcl` — independently generated, byte-identical
  lock records for signed hashicorp/aws 6.46.0 packages.
- Dependency-audit inputs, provider downloads, Checkov, and ShellCheck were isolated under `/tmp`;
  none is a project commit candidate.
- No Terraform state, saved plan, plan identity, AWS inventory, endpoint, credential, token, image
  digest, deployment evidence, or teardown evidence was generated.

## Decisions and assumptions

- Commercial AWS partition and one selected Region are assumed; documented services must be
  available in that Region. Provider `allowed_account_ids` and hard preconditions bind the account.
- One NAT gateway, desired count one, and no ECS task public IP are deliberate temporary-demo
  choices. They are not highly available.
- Required HTTPS AWS/ECR control-plane egress uses that NAT. S3 data and ECR layer objects use the
  gateway endpoint. No interface endpoint fleet or second NAT was added.
- `https_token` is the preferred synthetic-demo mode, not an authentication platform. The HTTP
  fallback carries no reusable token and makes no secure-transport claim.
- Demo S3 data uses SSE-S3 to support clean teardown. Retained Terraform state uses its own rotating
  KMS key. Finite retention and every resource-local Checkov exception were reviewed in the final
  zero-failure scan.
- A noncommitted, confirmed human budget destination is mandatory. AWS Budgets is a notification,
  not a hard spending cap; `AutoDestroyDate` is a reminder/guard, not automatic deletion.
- Bootstrap state access logging depends on a separately retained account CloudTrail S3 data-event
  trail confirmed by the human bootstrap operator, avoiding a circular state-owned log target.
- The AWS-managed SSM and SNS key paths are the bounded MVP assumption. Customer-managed keys need
  a separately reviewed exact-key policy change.

## Residual risks

- The present monitor image cannot execute `aws-run`; runtime activation is correctly blocked but
  scheduled-monitor operational acceptance remains open.
- Checkov's 54 skips are deliberate resource-instance exceptions, not production recommendations.
  Future architecture or policy-version changes require re-review rather than copying them forward.
- No live AWS plan proves IAM authorization details, service-linked-role assumptions, AWS-managed
  KMS compatibility, Scheduler dimensions, Firehose delivery, ACM coverage, SSM metadata, budget
  subscription confirmation, state locking, alarm behavior, or post-destroy eventual consistency.
  These are Phase 10 live gates.
- `force_destroy` enables complete demo cleanup but is destructive by design. The guarded, reviewed
  destroy plan and post-destroy inventory must be used after evidence capture.
- Existing bootstrap resources are intentionally retained and require a separate human/SSO-only
  final cleanup after all backend consumers are gone and state is archived.

## Acceptance checklist status

- Terraform implementation/static-contract items: complete.
- Terraform format check: pass.
- Provider-backed bootstrap/demo initialization and validation: pass with locked AWS provider 6.46.0.
- Checkov: pass with 433 passed, 0 failed, and 54 documented resource-instance skips.
- ShellCheck and hashed dependency audit: pass.
- Scheduled monitor live read/write contract: intentionally open; activation is fail-closed.
- Destruction proof: intentionally open until the controlled deployment phase; verifier is present
  and statically tested.
- Phase status: `completed`; technical GO for independent review and, after a manual commit, Phase
  09. Phase 10 activation remains blocked until the exact runtime contracts pass.

## Suggested commit message

```text
feat: add guarded Phase 08 AWS Terraform architecture
```

Do not commit automatically; the complete Phase 08 diff still requires independent human review.

## Exact next manual action

Perform an independent review of all 54 Phase 08 change records, including both provider locks, the
54 expanded Checkov exceptions, IAM boundaries, activation barriers, guard scripts, checklist,
manifest, and this report. If the review passes, stage only the approved Phase 08 paths and create
the suggested commit manually. Do not push, start Phase 09, create a Terraform plan, or call AWS as
part of that review action.

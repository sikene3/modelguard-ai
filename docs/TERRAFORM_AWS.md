# Phase 08 AWS Terraform architecture

## Status and scope

Phase 08 defines and statically validates infrastructure only. It does not call AWS, create a plan
against an account, or apply/destroy anything. Phase 10 is the first phase allowed to use short-lived
AWS credentials and reviewed saved plans.

The design is a temporary, synthetic portfolio environment. It is not highly available and neither
access mode is presented as an enterprise authentication platform.

## Architecture

```mermaid
flowchart TB
    Human[Human using short-lived AWS SSO] --> Bootstrap[Retained bootstrap state]
    Bootstrap --> State[S3 state + native lockfile + KMS]
    Bootstrap --> OIDC[GitHub OIDC plan/deploy roles]
    Bootstrap --> Boundary[Mandatory workload boundary]

    User[Restricted demo CIDR] --> ALB[Public ALB in two AZs]
    ALB --> API[Private ECS API desired 0 or 1]
    ALB --> Dashboard[Private ECS dashboard desired 0 or 1]
    API --> Firehose[Firehose]
    Firehose --> Events[Versioned prediction bucket]
    API --> Models[Versioned model bucket]
    Scheduler[EventBridge Scheduler] --> Monitor[Private one-shot ECS monitor]
    Monitor --> Events
    Monitor --> Models
    Monitor --> Reports[Versioned report bucket]
    Monitor --> SNS[Encrypted SNS topic]
    Dashboard --> Models
    Dashboard --> Reports
    API --> Logs[Finite CloudWatch logs + EMF]
    Monitor --> Logs

    Private[Two private subnets] --> S3EP[S3 gateway endpoint]
    S3EP --> ECRLayers[ECR regional layer bucket]
    Private --> NAT[One non-HA NAT for HTTPS AWS APIs/ECR control plane]
```

The ALB spans two public subnets. API, dashboard, and scheduled monitor tasks span two private
subnets, have no public IP, and accept task ingress only from the ALB security group on ports 8000
and 8501. The monitor has no inbound rule. S3 routes use a gateway endpoint restricted to the exact
demo buckets plus the Region's ECR layer bucket. ECR/API control-plane HTTPS and other AWS APIs use
one NAT gateway; image layer objects follow the more-specific S3 gateway route. DNS stays inside the
VPC. No interface endpoints or second NAT are present.

## Resource inventory

| Area | Resources | Lifecycle/guard |
|---|---|---|
| Bootstrap state | KMS key/alias, S3 bucket, versioning, encryption, public block, TLS-only policy, lifecycle | Retained; `prevent_destroy`; S3 `use_lockfile=true`; separate final cleanup |
| Bootstrap trust | GitHub OIDC provider, CI plan/deploy roles, workload boundary, retained state/SNS key, four scoped CI managed policies and attachments | Retained with `prevent_destroy`; exact OIDC audience/subjects; demo role cannot mutate them |
| Network | VPC, IGW, two public and two private subnets, route tables, one EIP/NAT, S3 gateway endpoint, four security groups | Disposable; one NAT is an explicit non-HA cost choice |
| Images/data | Three immutable ECR repositories; model, prediction, report, and audit S3 buckets | Disposable; force-delete; version and object expiry; no public access |
| Ingestion | Firehose delivery stream and finite log group/stream | GZIP newline JSON; physical UTC year/month/day/hour prefixes |
| Runtime | ECS cluster, API/dashboard task definitions and services, monitor task definition | Desired counts default zero; schedule default disabled; digest-form images, non-root users, read-only roots, task-scoped `/tmp`/runtime volumes |
| Routing | ALB, listeners, two target groups, rules and health checks | Restricted CIDR; `/metrics` fixed 404; circuit-breaker rollback on both services |
| Identity | Execution, API, dashboard, monitor, Firehose, Scheduler roles and inline policies | Exact project path/names; mandatory bootstrap boundary; separate responsibilities |
| Model identity | Active and previous SSM String pointers | Explicit unset sentinel; `ignore_changes` gives later values to promotion |
| Secret reference | ARN of a pre-created SSM SecureString | Terraform never reads the value; ECS `secrets.valueFrom` injects it only into API |
| Operations | Scheduler/group, SNS topic/policy, logs, native/EMF alarms, budget | Finite retention; alarm actions disabled before activation; only the email endpoint is enrolled out of band |

Every taggable demo resource receives `Project`, `Environment`, `Owner`, `ManagedBy`, `Ownership`,
and `AutoDestroyDate`. The date is a plan guard and reminder, never an automatic deletion mechanism.

## Ownership boundary

| Owner | Owns | Must not own/change |
|---|---|---|
| Human/SSO bootstrap | State bucket/KMS, native state locking permissions, OIDC provider, CI roles, mandatory boundary | Disposable workload resources |
| Disposable demo state | VPC through budget, including the six boundary-constrained workload roles | State/trust bucket, KMS, OIDC, CI roles, permission boundary |
| Model promotion | Active/previous pointer values and controlled ECS rollout decision | Pointer locations, IAM, token value |
| Human secret operator | Pre-created SecureString and its confirmation/rotation | Terraform state or inputs containing token bytes |
| Human notification operator | One confirmed SNS email subscriber receiving budget and drift alarms | Terraform variables, plans, state, workflow inputs, or artifacts containing an address |
| ACM owner | Pre-created certificate used by preferred HTTPS mode | Demo state unless a later phase explicitly changes ownership |

The initial pointer is `modelguard.unset.v1` with `UNSET` identity fields. A promoted active pointer
must validate as `modelguard.active-monitor-target.v1`, contain an exact semantic model version and
64-hex manifest digest, target `model-bundles/<version>/`, and pin all seven bundle objects by S3
VersionId. Terraform reads that non-secret pointer only in the activation plan. It never reads the
SecureString.

## Access modes and routing

`https_token` is preferred. It requires a pre-created ACM certificate and an SSM SecureString ARN
under `/modelguard-ai/demo/secrets/`. Port 80 redirects to 443. `POST /v1/predict` receives the token
through ECS `secrets`, and the application verifies HTTPS forwarding plus a constant-time bearer
comparison. The ARN is not marked as a secret because it is metadata; the bytes are never a
Terraform variable, local, data source, plan value, output, test fixture, or evidence field.

The Phase 08 boundary supports the AWS-managed SSM key only (`alias/aws/ssm`). Before activation,
`DescribeParameters` must prove the exact ARN is `SecureString` with that `KeyId`; do not call
`GetParameter`. A customer-managed token key would require a separately reviewed exact-key boundary
change and is not silently accepted. The ARN is also passed as non-secret application identity
metadata, while only ECS `secrets.valueFrom` supplies the token bytes.

`http_cidr_only` is a temporary fallback for synthetic data. It accepts no token or certificate
input and the application rejects authorization headers, so no reusable credential traverses HTTP.
It supplies restricted network exposure, not secure transport or authentication.

Both modes require a canonical restricted IPv4 CIDR. `0.0.0.0/0`, `::/0`, IPv6 (not enabled in this
VPC), malformed CIDRs, and host bits in a network CIDR are refused. Health routes are routed without
token enforcement. `/metrics` and `/metrics/*` are answered by a fixed 404 ALB rule and never reach
the API. All other default traffic goes to the read-only dashboard.

## IAM permission table

| Principal | Allowed boundary | Explicitly absent |
|---|---|---|
| CI plan (bootstrap) | Exact state read/lock object + KMS; one retained scoped read managed policy for refresh/inventory | State write, service mutation, IAM mutation, PassRole |
| CI deploy (bootstrap) | Exact state write/lock; separate compute/data/operations managed policies; exact inline workload-IAM/PassRole policy | OIDC/boundary/CI-role mutation, managed-policy creation, unrestricted IAM |
| ECS execution | ECR auth plus exact repository pulls; exact log streams; configured token ARN only | S3 application data, Firehose, SNS, arbitrary SSM |
| API task | Model bundle reads, exact model pointers, exact Firehose stream writes | Report writes, SNS, IAM |
| Dashboard task | Exact manifest objects and `monitoring/` report-prefix reads/presigned downloads | Any write, pointer/token access, Firehose, SNS |
| Monitor task | Exact model/prediction/report prefixes, pointer reads, exact SNS publish plus AWS-managed SNS-key use | ECR control, IAM, unrelated buckets |
| Firehose | Prediction bucket delivery prefixes and exact Firehose log stream | Model/report buckets, SNS, IAM |
| Scheduler | Exact monitor task revision on exact cluster; PassRole for execution+monitor to ECS only | API/dashboard tasks, other clusters/services/roles |

The CI deploy role has three separate `iam:PassRole` statements: ECS roles only to
`ecs-tasks.amazonaws.com`, Firehose only to `firehose.amazonaws.com`, and Scheduler only to
`scheduler.amazonaws.com`. The Scheduler workload role has its own exact execution/monitor
PassRole statement to ECS. All six demo roles use the bootstrap boundary. The deploy role can create
only those six names with the exact boundary and required project/environment request tags.

Resource `"*"` remains only where AWS offers no useful resource-level ARN, notably ECR authorization,
account/list discovery, legacy Billing authorization, generated EC2/association lifecycle calls, and
tagged ECS cluster creation. Actions are individually enumerated; there is no `Action: "*"`. Billing
view data is narrowed to the exact account's billing-view ARN pattern. Exact account/Region provider
guards, hard lifecycle preconditions, saved-plan identity, exact OIDC subjects, name allowlists,
project tags, and the workload boundary compensate for the remaining AWS API limitations.

The demo deploy role cannot remove or alter the boundary, OIDC provider, CI roles, or retained
managed policies. The bootstrap KMS key policy delegates its enumerated state-key actions through
account IAM; it does not name not-yet-created CI role principals and does not grant `kms:*`.

## OIDC subjects

Both roles require `aud=sts.amazonaws.com` and a `StringEquals` subject built from the repository-
level custom claim order `repo`, `ref`, `environment`, `workflow_ref`. For an immutable repository,
the subject begins `repo:<owner>@<owner-id>/<repository>@<repository-id>`; an explicitly legacy
repository begins `repo:<owner>/<repository>`. The remainder always binds `refs/heads/main`, one
exact protected environment, and one exact workflow path at that same ref.

The plan role accepts only `terraform-plan.yml` in `demo-plan`. The deploy role accepts exact
`deploy-demo.yml` and direct `publish-images.yml` subjects in `demo`, plus the dormant
`destroy-demo.yml` subject in `demo-destroy`. There is no wildcard repository, ref, environment, or
workflow condition. See `docs/CICD_SECURITY.md` and `.github/oidc-subject-template.json` for the exact
subjects, legacy/immutable inputs, and repository setting.

Create the matching IAM conditions first through the human/SSO bootstrap. Only after reviewing the
Terraform subject/template outputs may a repository administrator activate the matching GitHub OIDC
customization. Switching GitHub first is forbidden. Phase 09 ensures fork/untrusted PR jobs receive
neither `id-token: write` nor state/AWS credentials.

## Bootstrap and deployment order

### 1. Validate the two roots locally

```bash
terraform fmt -check -recursive infrastructure
terraform -chdir=infrastructure/bootstrap init -backend=false
terraform -chdir=infrastructure/bootstrap validate
terraform -chdir=infrastructure/environments/demo init -backend=false
terraform -chdir=infrastructure/environments/demo validate
checkov -d infrastructure
```

Initialization generates one reviewed `.terraform.lock.hcl` in each root. Both lock files pin the
same signed hashicorp/aws version and checksum set; commit them, but never commit `.terraform/`
working directories.

### 2. Human bootstrap in Phase 10

Copy `infrastructure/bootstrap/bootstrap.auto.tfvars.example` to a Git-ignored file. Supply the exact
repository names, numeric owner/repository IDs, immutable-subject flag, ref, environments, and
workflow paths. A human uses short-lived SSO, verifies STS account and configured Region, produces a
saved plan, reviews it, and applies it before activating the GitHub custom subject template. Preserve
bootstrap state in an approved encrypted location. Record only non-secret outputs. Before that
apply, the account/organization owner must confirm an existing CloudTrail trail
captures S3 data events for the exact future state-bucket ARN; that retained account-level control is
why this root does not create a circular second state-log bucket.

Copy `backend.hcl.example` to Git-ignored `backend.hcl` with bootstrap outputs. The required fields
are exact bucket/key/Region/KMS, `encrypt=true`, and `use_lockfile=true`. The guard refuses missing or
additional backend fields, a wrong account/Region key ARN, or a bucket that does not match the exact
account/Region naming contract.

### 3. First reviewed saved plan: prerequisites

Copy `demo.auto.tfvars.example` to a Git-ignored file. Use a current restricted CIDR and an
AutoDestroyDate no more than 14 days away. For HTTPS, include only ACM and SecureString ARNs. No
notification address is a Terraform input. Set `alert_kms_key_arn` only from the bootstrap
`alert_kms_key_arn` output; it is non-secret and is bound to the guarded account and Region.

```bash
terraform -chdir=infrastructure/environments/demo init \
  -reconfigure -backend-config=/absolute/path/backend.hcl
terraform -chdir=infrastructure/environments/demo plan \
  -var-file=/absolute/path/demo.auto.tfvars \
  -out=prerequisites.tfplan
terraform -chdir=infrastructure/environments/demo show prerequisites.tfplan
```

The first plan must have `deployment_stage=prerequisites`, `activate_services=false`,
`runtime_contract_verified=false`, no image inputs, API/dashboard desired count zero, and schedule
disabled. Task definitions use an explicit non-runnable zero digest so no mutable tag ever appears.
Alarm actions are disabled. The `terraform_data.deployment_guard` lifecycle preconditions make an
invalid identity, date, transport combination, or stage a plan error. Do not use
`terraform -target`.

Bind the opaque saved plan to its plan hash, variable-file hash, backend-file hash, account, Region,
project, environment, backend key, default workspace, Git commit, stage, activation state, and
AutoDestroyDate:

```bash
uv run python scripts/terraform_demo_guard.py seal-plan \
  --plan infrastructure/environments/demo/prerequisites.tfplan \
  --var-file /absolute/path/demo.auto.tfvars \
  --backend-config /absolute/path/backend.hcl \
  --stage prerequisites --account-id 123456789012 --region us-east-1 \
  --repository . --auto-destroy-date YYYY-MM-DD --activate-services false \
  --output infrastructure/environments/demo/prerequisites.tfplan.identity.json
```

Verification must run immediately before applying the same saved plan in Phase 10. A renamed,
modified, more-than-24-hour-old, implausibly future-dated, wrong-commit, wrong-account, wrong-Region,
wrong-backend, or wrong-stage plan is refused.

In Phase 10 only, the manual operator path applies this exact file through `scripts/safe_apply.sh`.
The script rechecks backend/account/Region/default workspace, displays the plan, verifies the sealed
identity, requires the operator to type the exact stage, and verifies identity again immediately
before `terraform apply <saved-plan>`. It never creates a plan and accepts no arbitrary plan name:

```bash
CONFIRM_APPLY=YES \
EXPECTED_AWS_ACCOUNT_ID=123456789012 \
AWS_REGION=us-east-1 \
BACKEND_BUCKET_NAME=modelguard-ai-terraform-state-123456789012-us-east-1 \
BACKEND_CONFIG=/absolute/path/backend.hcl \
TFVARS_FILE=/absolute/path/demo.auto.tfvars \
PLAN_STAGE=prerequisites \
scripts/safe_apply.sh
```

### 4. Enroll notifications, then publish and verify prerequisites

The prerequisite apply creates a budget whose 80% actual-cost notification targets the exact SNS
topic ARN; this is non-secret plan data. A human using short-lived SSO then runs
`scripts.notification_enrollment enroll` from an interactive terminal. The prompt accepts one
mandatory SNS email address without echo, writes no files, and emits no address. That single endpoint
receives both budget and drift alarms, and Terraform never owns or refreshes it. The protected
deployment calls `scripts.notification_enrollment verify` and refuses before image publication
unless exactly one confirmed email subscription exists. See
`docs/CICD_SECURITY.md` for the exact command and permission boundary.

Build each role image once for the reviewed Git SHA, scan that exact image, push one immutable
`git-<sha>` tag, and resolve it with ECR `DescribeImages`. Activation uses only
`repository@sha256:<digest>`; it never rebuilds or deploys a tag.

Publish the verified seven-file bundle into the model bucket without overwriting an existing version,
read every object back, record every VersionId, and promote the exact active pointer outside
Terraform. Verify the pointer and bundle. In HTTPS mode, use SSM `DescribeParameters` to prove the
ARN names a `SecureString` using `alias/aws/ssm` without calling `GetParameter`; verify the ACM
certificate is issued and covers the ALB hostname, and verify all ECR digests. Confirm the value-free
notification enrollment gate and that the `Project` user cost-allocation tag is active. Run image contract
tests proving API model bootstrap, dashboard S3 reads, and the monitor's one-shot `aws-run` contract before setting
`runtime_contract_verified=true`.

The current Phase 07 monitor image exposes only the local `run` and `status` commands; it does not
yet implement `aws-run`. Phase 08 intentionally does not pre-build that later runtime orchestration.
Consequently, `runtime_contract_verified` must remain false and neither services nor the schedule
may be activated until a later phase implements and tests that exact digest-pinned image contract.

### 5. Second reviewed saved plan: activation

Set `deployment_stage=activation`, `activate_services=true`, all three exact digest references,
`runtime_contract_verified=true`, and the verified pointer's model version, manifest SHA-256, and
seven-entry S3 VersionId map. The activation plan freshly reads the non-secret active pointer and
requires exact equality with those inputs before setting desired count one, enabling alarm actions,
and enabling the schedule.

```bash
terraform -chdir=infrastructure/environments/demo plan \
  -var-file=/absolute/path/demo.auto.tfvars \
  -out=activation.tfplan
terraform -chdir=infrastructure/environments/demo show activation.tfplan
```

Seal the identity beside the activation plan, then use the same guarded script with
`PLAN_STAGE=activation`; review, verify, and only then apply it in Phase 10. No ad hoc target,
refresh-only substitute, mutable tag, or rebuilt image may bridge the two stages.

## Alarm source matrix

The machine-readable source inventory is `infrastructure/alarm-sources.json` and a static test proves
each entry exists in Terraform and, for EMF, in application source.

| Signal | Namespace/metric | Producer | Missing-data policy |
|---|---|---|---|
| API target 5xx | `AWS/ApplicationELB/HTTPCode_Target_5XX_Count` | ALB | not breaching |
| API p95 latency | `AWS/ApplicationELB/TargetResponseTime` | ALB | not breaching |
| API/dashboard healthy hosts | `AWS/ApplicationELB/HealthyHostCount` | ALB | breaching after activation |
| S3 delivery | `AWS/Firehose/DeliveryToS3.Success` | Firehose | not breaching when idle |
| Schedule submission failure | `AWS/Scheduler/TargetErrorCount` | Scheduler | not breaching when idle |
| API event write failure | `ModelGuardAI/EventSinkErrors` | API EMF | not breaching; sparse failure metric |
| Monitor completion | `ModelGuardAI/MonitorCompletions` | One monitor EMF record/run | breaching |
| Monitor input | `ModelGuardAI/RawRecords` | Same EMF record | breaching |
| Monitor rejected | `ModelGuardAI/RejectedRecords` | Same EMF record | breaching |
| Monitor predictions | `ModelGuardAI/AcceptedTargetRecords` | Same EMF record | breaching |
| Report freshness | `ModelGuardAI/ReportFreshnessSeconds` | Same EMF record | breaching |

Scheduler target submission is not monitor completion. A monitor failure emits no successful
heartbeat, so the completion and companion metrics become missing and breach. API event-write
failures are sparse and missing is healthy. No alarm uses ECS desired/running metrics because paid
Container Insights is explicitly disabled.

`AcceptedEventFreshnessSeconds` remains telemetry for accepted event-time freshness and explicitly
does not claim row delivery lateness. `ReportFreshnessSeconds` is `monitor as_of - finalized window
end` and is the source for the report-age alarm.

## Cost controls and known assumptions

Primary cost drivers are the NAT gateway, ALB, two one-task Fargate services while active, one-shot
monitor runs, Firehose ingestion, log storage, S3 objects, and the retained state KMS key. ECR and S3
lifecycle rules bound stale images, current objects, noncurrent versions, and incomplete multipart
uploads. Logs retain 14 days by default. Desired count one and one NAT are non-HA choices.

The monthly USD budget defaults to 25. Its 80% actual-cost notification targets the Terraform-owned
SNS topic by non-secret ARN. The topic policy permits only the exact account's exact budget service
identity for this publish path. Because AWS Budgets requires a customer-managed key policy for an
encrypted SNS target, the topic reuses the retained bootstrap KMS key. Exact Budget and CloudWatch
source ARNs, the source account, the SNS topic encryption context, and exact regional
`kms:ViaService = sns.<region>.amazonaws.com` conditions are enforced independently inside both
service-principal key-policy statements; the monitor role is limited to the same key/context/SNS
path. One confirmed SNS email
endpoint is enrolled after prerequisite apply by the protected interactive human/SSO contract and
receives both budget and drift alarms; its address never enters Terraform, state, a saved plan, a
workflow input, or an artifact. Before deployment, a
billing administrator must activate the user-defined `Project` cost-allocation tag and confirm the
SNS subscription; tag activation and cost data can take time, so the budget is never
described as a hard real-time cap.
This follows AWS's
[budget-to-SNS policy](https://docs.aws.amazon.com/cost-management/latest/userguide/budgets-sns-policy.html)
and [encrypted SNS key-policy](https://docs.aws.amazon.com/sns/latest/dg/sns-key-management.html)
contracts.

Assumptions:

- Commercial AWS partition, Python 3.12 images, Fargate platform 1.4.0, and one Region (default
  `us-east-1`).
- The selected Region has exactly the two configured AZs, supports Scheduler, Firehose extended S3,
  Fargate, ALB, Budgets, ACM, ECR, SSM, and SNS.
- Account service-linked roles needed by these managed services already exist or are created once by
  an authorized human; the demo deploy role cannot create arbitrary IAM service-linked roles.
- Required HTTPS AWS API and ECR control-plane egress uses the single NAT. ECR layer objects and demo
  S3 data use the S3 gateway endpoint. No interface endpoints or second NAT are added.
- The pre-created prediction token uses the AWS-managed SSM key. The SNS topic uses the retained
  bootstrap customer-managed key with exact source account, source ARN, topic context, and regional
  SNS ViaService conditions in each Budget/CloudWatch key-policy statement, so both services can
  publish without creating a second retained key.
- CloudWatch alarms publishing to the encrypted SNS topic, Scheduler dimensions, Firehose
  delivery, and every digest-pinned image contract require live Phase 10 smoke evidence before
  activation is accepted as operationally complete.
- S3 demo data uses SSE-S3 so destroy leaves no demo KMS key pending deletion. Data is synthetic,
  buckets are TLS-only/private, and the retained state bucket does use a dedicated rotating KMS key.
- Cross-Region S3 replication, a WAF, paid VPC Flow Logs, and KMS encryption for short-lived logs/data
  are narrowly skipped security checks because of the temporary restricted synthetic scope. ALB/S3
  access logs, native telemetry, versioning, lifecycle cleanup, and restricted ingress compensate.

There are 45 line-local directives. Expansion of `for_each` resources produces exactly 54 skipped
Checkov result instances; the counts below sum to 54. Every directive is inside the exact affected
resource or data block. There is no global Checkov configuration, command-line check suppression,
wildcard check ID, or repository-wide exception.

| Check (result instances) | Exact scope | Justification/compensating control |
|---|---|---|
| `CKV_AWS_109` (1) | `data.aws_iam_policy_document.state_kms` | Same-account root is the standard KMS recovery/IAM-delegation principal; Budget/CloudWatch use is separately limited by exact account, source ARN, SNS context, and regional SNS ViaService |
| `CKV_AWS_111` (2) | `state_kms`; `data.aws_iam_policy_document.ci_deploy_compute` | KMS policy resource must denote its own key and every service statement has exact source/context/ViaService; generated EC2/association IDs cannot be known before creation, while actions and guards are fixed |
| `CKV_AWS_356` (2) | `state_kms`; `ci_deploy_compute` | Same two unavoidable resource forms; no `Action: "*"`, KMS service use has exact source/context/ViaService, and resource-addressable workload actions use exact ARNs |
| `CKV_AWS_18` (2) | `aws_s3_bucket.state`; `module.data_plane.aws_s3_bucket.this` | Retained state requires separately confirmed CloudTrail data events; three demo buckets log to the audit sink, which cannot server-log to itself |
| `CKV_AWS_144` (2) | Retained state bucket; disposable data-plane bucket resource | Single-Region temporary scope; versioning, encryption, saved state, and finite cleanup remain |
| `CKV2_AWS_62` (2) | Retained state bucket; disposable data-plane bucket resource | No unconsumed S3 notification path is part of the state, Firehose, or monitor contract |
| `CKV_AWS_145` (1) | `module.data_plane.aws_s3_bucket.this` | Private synthetic data uses SSE-S3 to avoid a demo KMS key lingering after teardown; TLS, public block, versioning, and lifecycle remain |
| `CKV_AWS_136` (3) | API, dashboard, and monitor ECR repositories | Private immutable scan-on-push repositories contain no secrets; AES256 avoids a lingering disposable key |
| `CKV_AWS_158` (4) | API, dashboard, monitor, and Firehose log groups | Short-lived synthetic logs use AWS-managed encryption so teardown leaves no customer key pending deletion |
| `CKV_AWS_338` (4) | Same four log groups | Validated finite retention matches the temporary cost/teardown contract; one-year retention does not |
| `CKV_AWS_65` (1) | `aws_ecs_cluster.this` | Paid Container Insights is intentionally disabled; no alarm claims its metrics, and native/EMF sources are statically checked |
| `CKV2_AWS_11` (1) | `module.network.aws_vpc.this` | Paid flow logs are omitted; ALB access logs, application/service telemetry, and restricted rules remain |
| `CKV2_AWS_5` (3) | API, dashboard, and monitor task security groups | Checkov cannot trace the module outputs; static tests bind each group to its ECS service or Scheduler task, and monitor has no ingress |
| `CKV_AWS_382` (3) | API, dashboard, and monitor 443 egress rules | Exact-port AWS/ECR HTTPS egress uses the documented single NAT; S3 uses the exact-resource gateway endpoint |
| `CKV_AWS_150` (1) | `aws_lb.this` | ALB deletion protection conflicts with mandatory guarded teardown and residual verification |
| `CKV2_AWS_20` (1) | `aws_lb.this` | The conditional synthetic-only HTTP mode intentionally forwards; preferred `https_token` mode creates the HTTPS redirect |
| `CKV2_AWS_28` (1) | `aws_lb.this` | WAF is intentionally omitted only for this restricted, disposable synthetic demo |
| `CKV_AWS_378` (2) | API and dashboard target groups | TLS terminates at the ALB; each private hop is security-group restricted to one exact target port |
| `CKV_AWS_2` (1) | Conditional `aws_lb_listener.http_demo` | Preferred mode redirects to HTTPS; fallback carries no reusable token and makes no secure-transport claim |
| `CKV_AWS_103` (1) | Conditional `aws_lb_listener.http_demo` | TLS policy is inapplicable to the disclosed HTTP fallback; the HTTPS listener enforces TLS 1.2 or newer |
| `CKV_AWS_241` (1) | `aws_kinesis_firehose_delivery_stream.predictions` | AWS-owned stream encryption plus encrypted private destination avoids a customer key lingering after teardown |
| `CKV_AWS_297` (1) | `aws_scheduler_schedule.monitor` | The synthetic command contains no secret; AWS-owned encryption avoids a lingering disposable key |
| `CKV2_AWS_34` (2) | Active and previous SSM model pointers | Values are integrity metadata, not credentials; the separate SecureString token is pre-created and never read by Terraform |
| `CKV_AWS_319` (12) | Twelve expanded ALB, Firehose, Scheduler, API EMF, and monitor EMF alarms | Actions are disabled only in prerequisites and enabled by the guarded activation plan; every metric source and missing-data policy is explicit |

There is no EKS, RDS, MSK, interface endpoint fleet, second NAT, always-on monitor, auth platform,
automatic retraining, or automatic deletion service.

## Guarded destroy and retained inventory

Run `scripts/safe_destroy.sh` only in Phase 10 with the required explicit account, Region, backend,
tfvars, and date inputs. It verifies backend identity before init, confirms STS and configured Region,
requires the default workspace, creates exactly `destroy.tfplan`, displays it, seals its identity,
requires two human confirmations, verifies the unchanged saved plan immediately before apply, then
calls `scripts/verify_aws_teardown.sh`. The saved-plan identity guard deliberately accepts an expired
AutoDestroyDate for the exact `destroy.tfplan`; it is a teardown deadline, not an authorization to
strand resources. Phase 10 must still review the provider-backed destroy plan before applying it.

Tag inventory is necessary but not sufficient. Record service-specific post-destroy queries for:

- ECS clusters/services/tasks/task definitions;
- ELBv2 load balancers/listeners/rules/target groups;
- EC2 NAT gateways, EIPs, VPC endpoints, VPC/subnets/routes/security groups;
- Firehose streams and Scheduler schedules/groups;
- S3 buckets plus all current/noncurrent/delete-marker versions and incomplete multipart uploads;
- ECR repositories/images;
- CloudWatch log groups/alarms;
- SNS topics/subscriptions, SSM pointer locations, workload IAM roles, and the AWS Budget.

The teardown verifier produces one machine-readable payload containing Resource Groups tag inventory
plus exact service queries, including active and inactive ECS task definitions. The Python guard
rejects any tagged or service-specific residual. Retain the JSON under `reports/generated/phase-10/`
and run the verifier again after an eventual-consistency delay; an empty first response is not proof
by itself. Any query error fails closed instead of being normalized to an empty result.

The expected retained inventory is separate and explicit:

- bootstrap S3 state bucket and object versions/lock history;
- bootstrap KMS key/alias;
- GitHub OIDC provider;
- CI plan/deploy roles, state/PassRole inline policies, scoped CI managed policies, and attachments;
- mandatory workload boundary policy;
- human-owned ACM certificate and SecureString if they predated the demo.

The demo must not delete the SecureString or ACM certificate it does not own. Final bootstrap cleanup
is a later human/SSO-only saved plan after every demo backend user is gone and state is archived. It
requires a reviewed change removing `prevent_destroy`, explicit deletion of every state version and
lock object, and acknowledgment that the KMS key remains in a 30-day pending-deletion state. The
demo deploy role has no authority for that operation.

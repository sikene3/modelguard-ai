# Phase 08 — Terraform AWS Infrastructure

## Recommended mode
GPT-5.6 Sol, Max.

## Objective
Implement a secure, cost-aware, destroyable Terraform architecture for the temporary demo environment. Do not apply resources in this phase.

## Required resources/modules
- Separate human/SSO-applied bootstrap for a versioned/encrypted/public-blocked/TLS-only remote-state
  bucket with locking, GitHub OIDC provider/plan/deploy roles, and a mandatory permission boundary;
  disposable demo state must not own, mutate, or delete this trust/state boundary.
- Two-AZ VPC: public ALB subnets, private ECS subnets with no public task IP, one documented non-HA
  NAT gateway, and an S3 gateway endpoint.
- ECR repositories for API/dashboard/monitor in the demo prerequisite stage; deploy task definitions
  by resolved digest, never mutable tag.
- S3 buckets/prefix policies for model bundles, prediction events, reports, and state.
- Kinesis Data Firehose delivery stream to partitioned S3 paths.
- ECS cluster, task definitions, services for API/dashboard, and scheduled monitor task.
- ALB listeners/rules, target groups, health checks.
- SSM active/previous model pointers containing exact model version plus manifest digest. Initial
  value is an explicit unset sentinel; promotion owns later value changes. In `https_token` mode,
  accept only the ARN of a pre-created SSM SecureString and inject it through ECS `secrets`; token
  bytes must never enter Terraform configuration, variables, state, plans, outputs, or evidence.
- CloudWatch log groups, metrics/alarms, finite retention.
- EventBridge Scheduler for monitor execution.
- SNS topic and optional subscription input; never commit an email address.
- Separate least-privilege roles for CI plan, CI deploy, ECS execution, API, dashboard, monitor,
  Firehose, and Scheduler; constrain `iam:PassRole`.
- OIDC trust pins `aud=sts.amazonaws.com`. Protected main-ref plan and protected-environment
  deploy/destroy subjects are exact alternative `sub` forms, not a combined wildcard. Fork/untrusted
  PR jobs get neither `id-token: write` nor remote-state/AWS credentials.
- ALB ingress requires an explicit restricted CIDR; reject world IPv4/IPv6 CIDRs. `https_token`
  requires ACM and the SecureString reference. Otherwise `http_cidr_only` is a disclosed temporary
  synthetic limitation and no reusable token is transmitted. Health routes are token-exempt;
  `/metrics` is not publicly routed.
- Tags, finite retention/object-version cleanup, AutoDestroyDate (reminder/guard, not automatic
  deletion), verified teardown, and mandatory small AWS Budget notification (not a hard cap). A
  noncommitted human budget destination and confirmed subscription are deployment requirements;
  the drift SNS subscription remains optional.
- ECS deployment circuit breaker with rollback.
- Alarm-source matrix: native ALB 5xx/latency/healthy hosts, native Firehose delivery, native
  Scheduler submission failures, EMF API event-write failures, and one EMF monitor
  completion/input/rejected/prediction/report-freshness heartbeat per run. Missing monitor heartbeat
  breaches; sparse API-failure metrics treat missing as not breaching. Scheduler submission is not
  monitor completion. Require a documented/tested source for every alarm; use ECS desired/running
  only if costed/tested Container Insights is explicitly enabled.
- Two-stage activation with two reviewed saved plans and no ad hoc targeting: prerequisite apply has
  API/dashboard desired count zero and schedule disabled; after image digests, bundle, pointer, and
  token prerequisites verify, an activation plan enables runtimes.

## Engineering requirements
- Reusable modules but avoid abstraction for one-line resources.
- Valid variable types, validation blocks, descriptions, and safe defaults.
- No `*` actions/resources unless unavoidable and documented.
- Bootstrap-owned roles/policies cannot be changed by demo deploy. Workload roles use the mandatory
  boundary and project path/name; `iam:PassRole` is limited to exact workload roles/services.
- No public S3 access.
- No long-lived AWS keys.
- No automatic Terraform apply workflow.
- Provider `allowed_account_ids`; plan/apply/destroy guard account, Region, environment, backend key,
  project tags, and saved-plan identity.
- Task ingress is ALB-security-group to exact ports. S3 uses its endpoint; required HTTPS AWS/ECR
  egress through the single NAT is an explicit MVP exception. Desired count one and one NAT are
  documented non-HA risks; do not add interface endpoints or a second NAT.
- No EKS, RDS, MSK, or always-on monitoring service.
- Document the HTTP demo limitation and preferred HTTPS-token demo path without claiming that either
  is an enterprise authentication platform.

## Validation only — do not apply

```bash
terraform fmt -recursive infrastructure
terraform -chdir=infrastructure/environments/demo init -backend=false -input=false -lockfile=readonly
terraform -chdir=infrastructure/environments/demo validate
checkov -d infrastructure
```

Where validation requires initialized providers/modules, use safe local initialization without creating resources.

## Required documentation
- Architecture and resource inventory.
- Bootstrap/deployment order.
- IAM permission table.
- Cost drivers and teardown.
- Variables example without secrets.
- Known region/service assumptions.
- Prerequisite/activation barrier, metric-source table, bootstrap-vs-demo ownership, retained
  inventory, and separate guarded final-bootstrap cleanup.

## Definition of done
Terraform formats, validates, passes security checks or has narrowly justified documented skips.
Mock/static tests cover guard refusal paths, activation default-off, permission-boundary/PassRole
scope, token-ARN-only handling, alarm sources, and post-destroy inventory logic. No apply is executed.

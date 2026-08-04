# Phase 08 Checklist

- [x] Human/SSO bootstrap ownership and separate final cleanup documented
- [x] Separate encrypted/versioned/locked state bootstrap
- [x] Restricted ALB CIDR; private tasks/no public IP
- [x] Two AZs, one NAT, S3 gateway endpoint
- [x] VPC/ALB/ECS
- [x] ECR/S3/Firehose
- [x] Scheduler/SNS/CloudWatch
- [x] SSM active version
- [x] Exact active/previous manifest identities and ARN-only SecureString injection
- [x] Least-privilege IAM
- [x] Separate plan/deploy/execution/API/dashboard/monitor/Firehose/Scheduler roles
- [x] GitHub OIDC role
- [x] Exact OIDC audience/repository/protected-subject claims
- [x] Bootstrap permission boundary prevents deploy-role self-escalation; scoped PassRole
- [x] Circuit breaker
- [x] Tags/lifecycle
- [x] Budget alert, alarm matrix, guarded verified destroy
- [x] Budget targets the non-secret alert-topic ARN; one confirmed noncommitted SNS email endpoint
      receives both budget and drift notifications
- [x] Native/EMF source defined and tested for every alarm
- [x] Prerequisites default runtimes off; second digest-pinned activation plan
- [x] Non-HA NAT/task and HTTPS egress exceptions documented
- [x] fmt/validate/Checkov

## Evidence

- Commands: exact Terraform format/init/validate/Checkov commands, focused/full Pytest, Ruff, Mypy,
  Bandit, Bash syntax, JSON, secret, whitespace, and dependency-audit gates are recorded in
  `reports/phase-08.md`.
- Test results: focused Phase 08/monitor regression set `26 passed`; full suite `216 passed` at
  84.74% branch coverage. Both Terraform roots validate with pinned AWS provider 6.46.0; Checkov
  3.3.9 reports 433 passed, 0 failed, and 54 resource-local documented skips. Ruff, strict Mypy,
  Bandit, Bash syntax, ShellCheck 0.11.0, JSON, hashed `pip-audit`, basic secret scan, and Terraform
  formatting pass.
- Artifact paths: both root `.terraform.lock.hcl` files, `infrastructure/alarm-sources.json`,
  `docs/TERRAFORM_AWS.md`, and `reports/phase-08.md`. Phase 10 teardown evidence is intentionally not
  generated in Phase 08.
- Commit: none; agents do not commit automatically.
- Residual risks: no AWS plan/apply/destroy or live IAM/runtime test ran. Activation remains
  fail-closed until the exact runtime image digests prove API/dashboard AWS startup and the monitor
  `aws-run` contract; live teardown proof remains a Phase 10 gate.

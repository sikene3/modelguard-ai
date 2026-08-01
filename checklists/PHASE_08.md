# Phase 08 Checklist

- [ ] Human/SSO bootstrap ownership and separate final cleanup documented
- [ ] Separate encrypted/versioned/locked state bootstrap
- [ ] Restricted ALB CIDR; private tasks/no public IP
- [ ] Two AZs, one NAT, S3 gateway endpoint
- [ ] VPC/ALB/ECS
- [ ] ECR/S3/Firehose
- [ ] Scheduler/SNS/CloudWatch
- [ ] SSM active version
- [ ] Exact active/previous manifest identities and ARN-only SecureString injection
- [ ] Least-privilege IAM
- [ ] Separate plan/deploy/execution/API/dashboard/monitor/Firehose/Scheduler roles
- [ ] GitHub OIDC role
- [ ] Exact OIDC audience/repository/protected-subject claims
- [ ] Bootstrap permission boundary prevents deploy-role self-escalation; scoped PassRole
- [ ] Circuit breaker
- [ ] Tags/lifecycle
- [ ] Budget alert, alarm matrix, guarded verified destroy
- [ ] Confirmed noncommitted budget recipient; optional drift subscription kept separate
- [ ] Native/EMF source defined and tested for every alarm
- [ ] Prerequisites default runtimes off; second digest-pinned activation plan
- [ ] Non-HA NAT/task and HTTPS egress exceptions documented
- [ ] fmt/validate/Checkov

## Evidence

- Commands:
- Test results:
- Artifact paths:
- Commit:
- Residual risks:

# AWS Cost Control

## Project principle

AWS is a temporary demo environment for this project, not a permanent service. Deploy it, capture
the video and screenshots, then destroy the demo resources.

## Terraform controls

- Use one intentional NAT Gateway, accepting that it is not highly available, plus an S3 Gateway
  Endpoint.
- Run only the minimum required ECS tasks.
- Use desired count 1 for the API and dashboard during the demo. With one NAT, this design is not
  highly available.
- Do not schedule the monitor more frequently than the demo requires.
- Keep CloudWatch retention short and configurable.
- Use S3 lifecycle policies to remove prediction events and reports after the demo retention period.
- Before deployment, manually create the retained `modelguard-ai-demo-monthly` AWS Cost Budget for
  USD 10 with 50%, 80%, and 100% actual plus 100% forecast alerts. Enter and confirm its endpoint
  only in the AWS Console. Never place it in source, Terraform, state, a saved plan, GitHub, a
  workflow artifact, report, log, command, or example. The read-only preflight verifies only name,
  amount, period, and thresholds and never reads subscribers. Budget alerts are warnings and do not
  guarantee a hard spending cap.
- Enroll the separate demo drift/alarm SNS endpoint only through the interactive human boundary;
  Terraform and workflows still carry no endpoint value.
- Tag every resource with `Project`, `Environment`, `Owner`, `ManagedBy`, and `AutoDestroyDate`.
  The date is a reminder and guard, not an automatic deletion mechanism.
- Keep state and locking in a separate bootstrap layer; demo destroy must not own the state bucket.
- Keep the exact-state-object CloudTrail trail, audit log bucket, and audit KMS key in the separate
  retained audit bootstrap. Its CloudTrail, S3, and KMS usage can incur ongoing cost.
- The create-only model publisher adds no service. One successful publication is bounded to seven
  small object puts/readbacks, one short-lived lock version, version-history inspection, and a few
  SSM String operations. Failed immutable prefixes and lock versions remain subject to demo lifecycle
  and teardown.

The operating target is no more than USD 10 for the demo month. This is an expected-spend ceiling for
human approval, not a technically enforceable maximum: AWS Budget alerts can arrive late and do not
stop resources. Do not approve a plan whose estimate could exceed USD 10, stop the demo when an alert
or unexpected charge appears, and destroy promptly after evidence capture. No finite maximum charge
can be guaranteed by the current architecture.

## Before apply

```bash
uv run --frozen --no-sync python -m scripts.human_aws_login dependency
# After separately approved browser login and identity verification, use only the guarded,
# stage-specific saved-plan flow in docs/08_AWS_DEPLOYMENT_ORDER.md.
terraform -chdir=infrastructure/environments/demo show prerequisites.tfplan
```

Review these cost drivers especially carefully:

- NAT Gateway.
- ECS service and task counts.
- Application Load Balancer.
- Interface VPC endpoints, if any are proposed.
- Log retention.
- S3 lifecycle configuration.

## After recording the demo

```bash
CONFIRM_DESTROY=YES \
AWS_PROFILE=modelguard-bootstrap \
DEPLOYMENT_GOVERNANCE_MODE="$DEPLOYMENT_GOVERNANCE_MODE" \
./scripts/safe_destroy.sh
```

Then verify through the console or CLI that the demo no longer has unintended:

- ECS services or tasks.
- ALBs or target groups.
- NAT Gateways or Elastic IPs.
- Firehose delivery streams.
- CloudWatch log groups.
- Large ECR images that are no longer needed.

## Resources not deleted automatically

Bootstrap state, OIDC, and the permission boundary remain separate from demo destroy; retaining them
must be intentional and documented. ECR, model, and data resources belong to the demo prerequisite
stage and must appear in the post-destroy inventory. Final bootstrap cleanup requires its own plan
and safeguards after confirming that the remote state is no longer needed.

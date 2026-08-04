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
- Require a small AWS Budget whose 80% notification targets the exact non-secret SNS topic ARN.
  After prerequisite apply, enroll one confirmed human email endpoint for both budget and drift
  alarms through the interactive human/SSO command; never place the address in Terraform, state, a
  saved plan, workflow input, or artifact. The notification is not a hard spending cap.
- Tag every resource with `Project`, `Environment`, `Owner`, `ManagedBy`, and `AutoDestroyDate`.
  The date is a reminder and guard, not an automatic deletion mechanism.
- Keep state and locking in a separate bootstrap layer; demo destroy must not own the state bucket.

## Before apply

```bash
aws sts get-caller-identity
aws configure get region
terraform -chdir=infrastructure/environments/demo plan -out=tfplan
terraform -chdir=infrastructure/environments/demo show tfplan
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
CONFIRM_DESTROY=YES ./scripts/safe_destroy.sh
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

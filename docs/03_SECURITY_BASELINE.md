# Security Baseline

## Identity and secrets

- GitHub Actions uses separate plan/deploy OIDC roles; trust pins audience and exact repository plus
  protected environment/ref subject.
- No AWS access key or secret key is stored in GitHub Secrets.
- `.env`, Terraform tfvars containing personal values, state, and generated credentials are ignored.
- The application does not log environment variables or AWS responses containing credentials.

## Application

- Strict Pydantic validation and size/range limits.
- Bounded body/concurrency/timeout/retry and the ADR-008 access modes: restricted CIDR everywhere;
  ACM HTTPS plus a bearer token for prediction in `https_token`, or temporary `http_cidr_only` with
  no reusable token and no authentication/secure-transport claim.
- Request IDs for traceability.
- No raw card numbers, names, emails, IP addresses, or real payment data.
- Error responses do not expose stack traces in production mode.
- Model bundles include checksums and schema versions.
- Readiness blocks an invalid bundle.
- Health routes are token-exempt/minimal for ALB checks; `/metrics` is not publicly routed in AWS.
- AWS token bytes come only from a pre-created SSM SecureString injected into ECS. Terraform receives
  the ARN only; rotation forces a controlled deployment and teardown verifies parameter cleanup.

## Containers

- Non-root user.
- Multi-stage build where useful.
- Pinned base image digest before final portfolio release.
- No compiler/build toolchain in runtime images where practical.
- Read-only root filesystem where the application supports it.
- Drop unnecessary Linux capabilities.
- Trivy scanning with documented exceptions and expiry.

## AWS

- ECS tasks have no public IP in private subnets; ALB ingress requires a restricted CIDR.
- Two AZs use one documented non-HA NAT and an S3 gateway endpoint.
- Security groups use service-to-service rules instead of broad CIDRs.
- S3 public access block enabled.
- Encryption at rest enabled for S3/ECR/CloudWatch-supported resources.
- IAM separates CI plan/deploy, ECS execution, API, dashboard, monitor, Firehose, and Scheduler.
- Human/SSO bootstrap owns OIDC roles and a mandatory permission boundary; demo deploy cannot alter
  it. Protected main-ref and protected-environment OIDC subjects are exact alternatives, and
  `iam:PassRole` is limited to exact bounded workload roles.
- S3 access limited to required prefixes.
- CloudWatch retention is finite and configurable.
- HTTPS uses ACM when available; restricted HTTP is only a disclosed short-lived limitation.
- S3 uses the gateway endpoint; required HTTPS registry/AWS egress through the single NAT is a
  documented exception. One NAT and desired count one mean the demo is not highly available.
- Terraform state is separately bootstrapped with encryption/versioning/TLS/public block/locking.

## CI/CD

- Ruff, Mypy, Pytest, Bandit, pip-audit, Trivy, and Checkov.
- Untrusted pull requests cannot obtain AWS credentials.
- Apply/deploy is manual or protected.
- Actions and release base images are pinned; one scanned Git-SHA image is deployed by digest.
- Terraform plan is an artifact for review.
- Raw saved plans are restricted, short-lived transfer artifacts; public evidence contains only a
  redacted summary and plan digest. A pinned history-aware secret scan emits no matched values.

## Security evidence

Capture:

- OIDC trust-policy excerpt with repository and branch/environment condition.
- Checkov summary.
- Trivy summary.
- IAM role diagram or table.
- Screenshot of failed CI when a deliberate security/lint issue is introduced, then removed.

## Known limitations to disclose

- Temporary demo dashboard lacks full user authentication.
- HTTP may be used when no custom domain is available.
- Synthetic data only.
- Drift is not equal to model-performance degradation.
- Restricted HTTP fallback is not authenticated or encrypted transport, and one-task/one-NAT service
  operation is not HA.

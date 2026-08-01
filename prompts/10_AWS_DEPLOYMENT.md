# Phase 10 — Controlled AWS Demo Deployment

## Recommended mode
GPT-5.6 Sol, Max. Human approval remains mandatory for every AWS mutation.

## Objective
Deploy the already-validated project to the intended AWS demo account/region with explicit human review at every infrastructure-changing boundary.

## Safety boundary
Do not execute `terraform apply`, `terraform destroy`, IAM changes, GitHub pushes, or model promotion without the user's immediate explicit action in the terminal. Prepare commands and inspect outputs; the human runs/approves destructive or billable steps.

## Required sequence
- Confirm expected/current AWS account, Region, environment, backend key, project tags, budget,
  confirmed noncommitted budget destination, AutoDestroyDate, restricted ingress CIDR, and selected
  `https_token` or `http_cidr_only` access mode. For HTTPS-token mode confirm ACM and only the ARN of
  a pre-created SSM SecureString; never capture its value.
- Confirm working tree and commit SHA.
- Bootstrap state/OIDC/permission-boundary trust with the human's short-lived SSO identity after plan
  review; demo deploy cannot later mutate it.
- Review and apply a saved prerequisite plan with services at desired count zero and monitor schedule
  disabled. This stage creates demo ECR/storage/pointer locations and other prerequisites.
- Build/scan each image once, push its Git-SHA tag, resolve and record the immutable ECR digest.
- Publish the no-overwrite model bundle, verify S3 bytes, and set/promote an exact
  `{model_version, manifest_sha256}` pointer through the controlled command.
- Prove image digests, verified bundle/pointer, budget recipient, and any token reference before
  reviewing/applying a second saved plan that activates digest-pinned services and schedule. Do not
  use `terraform -target`.
- Verify ECS tasks, target groups, API liveness/readiness, dashboard, Firehose delivery, scheduled monitor, logs, and alarms.
- Run AWS smoke script.
- Record deployment evidence and resource inventory.
- Verify the exact image digest/model bundle checksum, last-known-good rollback targets, state-lock
  behavior, alarms, and cleanup plan before declaring success.
- Promotion/rollback records exact old/new model identities and forces a controlled ECS deployment;
  startup-only model loading is the MVP contract.

## Failure handling
Diagnose the smallest layer first: identity → DNS/ALB → target health → task logs → IAM → S3/SSM/Firehose. Do not make broad IAM policies as a debugging shortcut.

## Required output
Update `reports/phase-10.md` with account ID redacted where appropriate, region, commit SHA, image tags, Terraform plan/apply summary, endpoints, smoke results, failures/fixes, and teardown command.
Never put a shared token, full account identifier, budget recipient, public endpoint with credential,
or sensitive Terraform plan/state in evidence. Raw plans are restricted transfer artifacts, not
portfolio evidence; record only their digest and a redacted summary.

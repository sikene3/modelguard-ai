# AWS Deployment Order

## 1. Verify the account and Region

```bash
aws sts get-caller-identity
export AWS_REGION=us-east-1
```

Use a separate demo account or environment whenever possible.

## 2. Bootstrap state, OIDC, and the permission boundary

```bash
cd infrastructure/bootstrap
terraform init
terraform plan
terraform apply
```

A human operator performs this step with a short-lived SSO identity. The bootstrap layer owns only
the state resources, OIDC roles, and permission boundary; the demo deployment cannot modify them.
Record the required outputs, and never place secrets in Git-tracked files.

## 3. Apply prerequisites with runtimes disabled

Use a saved, reviewed plan that creates the VPC, ECR repositories, S3 buckets, Firehose delivery
stream, pointer locations, and other prerequisites with `activate_services=false`. The desired count
for the API and dashboard must be zero, and the monitor schedule must remain disabled. Do not use
`terraform -target`.

```bash
terraform -chdir=infrastructure/environments/demo init -reconfigure
terraform -chdir=infrastructure/environments/demo fmt -check -recursive
terraform -chdir=infrastructure/environments/demo validate
terraform -chdir=infrastructure/environments/demo plan \
  -var='activate_services=false' -out=prerequisites.tfplan
terraform -chdir=infrastructure/environments/demo show prerequisites.tfplan
terraform -chdir=infrastructure/environments/demo apply prerequisites.tfplan
```

## 4. Build, scan, push, and resolve image digests

```bash
aws ecr get-login-password --region "$AWS_REGION" \
  | docker login --username AWS --password-stdin "$AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com"

GIT_SHA=$(git rev-parse --short=12 HEAD)
docker build -f docker/api.Dockerfile -t modelguard-api:$GIT_SHA .
trivy image modelguard-api:$GIT_SHA
docker tag modelguard-api:$GIT_SHA "$API_ECR_URI:$GIT_SHA"
docker push "$API_ECR_URI:$GIT_SHA"
API_IMAGE_DIGEST=$(aws ecr describe-images --repository-name modelguard-api \
  --image-ids imageTag="$GIT_SHA" --query 'imageDetails[0].imageDigest' --output text)
```

Repeat this process once for the dashboard and monitor images, or use a protected workflow. The tag
records provenance; activation uses `repository@sha256:...` and does not rebuild an image.

## 5. Publish, verify, and point to the model

```bash
make train
uv run python -m modelguard.training.cli publish \
  --bundle artifacts/model-bundles/1.0.0 \
  --target s3
```

Reject overwrites, verify the bytes stored in S3, and then perform a controlled promotion of the
`{model_version, manifest_sha256}` value in SSM. In `https_token` mode, create or verify the SSM
SecureString manually outside Terraform and pass only its ARN. Never expose the value in shell
history, a Terraform plan, or evidence artifacts.

## 6. Apply the activation plan with image digests

```bash
terraform -chdir=infrastructure/environments/demo plan \
  -var='activate_services=true' \
  -var="api_image_ref=$API_ECR_URI@$API_IMAGE_DIGEST" \
  -var="dashboard_image_ref=$DASHBOARD_ECR_URI@$DASHBOARD_IMAGE_DIGEST" \
  -var="monitor_image_ref=$MONITOR_ECR_URI@$MONITOR_IMAGE_DIGEST" \
  -out=activation.tfplan
terraform -chdir=infrastructure/environments/demo show activation.tfplan
terraform -chdir=infrastructure/environments/demo apply activation.tfplan
```

Before applying, prove that every digest exists, the bundle and pointer are valid, the budget
destination has been confirmed, and the token ARN is valid when required. Every plan must remain
bound to the same commit, account, Region, and backend.

## 7. Run smoke tests

```bash
curl -fsS "$API_URL/health/live"
curl -fsS "$API_URL/health/ready"
./scripts/smoke_aws.sh
```

## 8. Run the demo and capture evidence

Send baseline traffic, then drifted traffic, and run the monitor task. Capture the required
screenshots, logs, and report.

## 9. Perform a guarded destroy and verify cleanup

```bash
CONFIRM_DESTROY=YES ./scripts/safe_destroy.sh
```

Review the tagged inventory and affected services afterward to confirm deletion of the ALB, ECS
services, NAT gateway, EIP, Firehose stream, Scheduler resources, logs, alarms, data buckets and
object versions, ECR repositories, SNS resources, budget, and token parameter. Report retained
bootstrap resources separately. Final bootstrap cleanup requires its own plan and safeguards and
must not occur while remote state is still in use.

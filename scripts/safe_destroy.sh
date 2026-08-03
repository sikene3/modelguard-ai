#!/usr/bin/env bash
set -euo pipefail

if [[ "${CONFIRM_DESTROY:-}" != "YES" ]]; then
  echo "Refusing to destroy. Run with CONFIRM_DESTROY=YES after reviewing the target account, region, workspace, and plan."
  exit 1
fi

required_names=(
  EXPECTED_AWS_ACCOUNT_ID
  AWS_REGION
  BACKEND_BUCKET_NAME
  BACKEND_CONFIG
  TFVARS_FILE
  AUTO_DESTROY_DATE
)
for required_name in "${required_names[@]}"; do
  if [[ -z "${!required_name:-}" ]]; then
    echo "Refusing to destroy: $required_name is required."
    exit 1
  fi
done

if [[ ! "$EXPECTED_AWS_ACCOUNT_ID" =~ ^[0-9]{12}$ ]]; then
  echo "Refusing to destroy: EXPECTED_AWS_ACCOUNT_ID must contain 12 digits."
  exit 1
fi

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
env_dir="$repo_root/infrastructure/environments/demo"

if [[ ! -d "$env_dir" ]]; then
  echo "Terraform demo directory not found: $env_dir"
  exit 1
fi

guard=(uv run --frozen --no-sync python "$repo_root/scripts/terraform_demo_guard.py")
"${guard[@]}" verify-backend \
  --input "$BACKEND_CONFIG" \
  --bucket "$BACKEND_BUCKET_NAME" \
  --account-id "$EXPECTED_AWS_ACCOUNT_ID" \
  --region "$AWS_REGION"

actual_account="$(aws sts get-caller-identity --query Account --output text)"
if [[ "$actual_account" != "$EXPECTED_AWS_ACCOUNT_ID" ]]; then
  echo "Refusing to destroy: caller account does not match EXPECTED_AWS_ACCOUNT_ID."
  exit 1
fi

configured_region="$(aws configure get region)"
if [[ "$configured_region" != "$AWS_REGION" ]]; then
  echo "Refusing to destroy: configured AWS Region does not match AWS_REGION."
  exit 1
fi

terraform -chdir="$env_dir" init -reconfigure -backend-config="$BACKEND_CONFIG"
workspace="$(terraform -chdir="$env_dir" workspace show)"
if [[ "$workspace" != "default" ]]; then
  echo "Refusing to destroy: only the default Terraform workspace is permitted."
  exit 1
fi

printf 'Type the exact project name modelguard-ai to continue: '
read -r answer
if [[ "$answer" != "modelguard-ai" ]]; then
  echo "Confirmation mismatch."
  exit 1
fi

plan_path="$env_dir/destroy.tfplan"
manifest_path="$env_dir/destroy.tfplan.identity.json"
terraform -chdir="$env_dir" plan -destroy -var-file="$TFVARS_FILE" -out="$plan_path"
terraform -chdir="$env_dir" show "$plan_path"

activation_value="$(terraform -chdir="$env_dir" output -json activation_state | jq -r '.activate_services')"
if [[ "$activation_value" != "true" && "$activation_value" != "false" ]]; then
  echo "Refusing to destroy: current activation state is not a boolean."
  exit 1
fi

"${guard[@]}" seal-plan \
  --plan "$plan_path" \
  --var-file "$TFVARS_FILE" \
  --backend-config "$BACKEND_CONFIG" \
  --stage destroy \
  --account-id "$EXPECTED_AWS_ACCOUNT_ID" \
  --region "$AWS_REGION" \
  --repository "$repo_root" \
  --auto-destroy-date "$AUTO_DESTROY_DATE" \
  --activate-services "$activation_value" \
  --output "$manifest_path"

printf 'Type DESTROY to apply the reviewed destroy plan: '
read -r final
if [[ "$final" != "DESTROY" ]]; then
  echo "Destroy cancelled."
  exit 1
fi

"${guard[@]}" verify-plan \
  --plan "$plan_path" \
  --var-file "$TFVARS_FILE" \
  --backend-config "$BACKEND_CONFIG" \
  --stage destroy \
  --account-id "$EXPECTED_AWS_ACCOUNT_ID" \
  --region "$AWS_REGION" \
  --repository "$repo_root" \
  --manifest "$manifest_path"

terraform -chdir="$env_dir" apply "$plan_path"

inventory_path="${POST_DESTROY_INVENTORY:-$repo_root/reports/generated/phase-10/post-destroy-inventory.json}"
mkdir -p "$(dirname "$inventory_path")"
EXPECTED_AWS_ACCOUNT_ID="$EXPECTED_AWS_ACCOUNT_ID" \
  AWS_REGION="$AWS_REGION" \
  INVENTORY_OUTPUT="$inventory_path" \
  "$repo_root/scripts/verify_aws_teardown.sh"

echo "Tagged and service-specific demo inventories are empty. Bootstrap resources remain intentionally retained."

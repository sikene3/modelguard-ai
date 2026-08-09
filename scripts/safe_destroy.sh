#!/usr/bin/env bash
set -euo pipefail

governance_mode="${DEPLOYMENT_GOVERNANCE_MODE:-}"
if [[ -z "$governance_mode" ]]; then
  echo "Refusing to destroy: DEPLOYMENT_GOVERNANCE_MODE is required."
  exit 2
fi
if [[ "$governance_mode" != "team_protected" && "$governance_mode" != "solo_portfolio" ]]; then
  echo "Refusing to destroy: invalid deployment governance mode."
  exit 2
fi

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
  AWS_PROFILE
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
if [[ "$AWS_PROFILE" != "modelguard-bootstrap" ]]; then
  echo "Refusing to destroy: AWS_PROFILE must be modelguard-bootstrap."
  exit 1
fi
export AWS_PROFILE

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
env_dir="$repo_root/infrastructure/environments/demo"

if [[ ! -d "$env_dir" ]]; then
  echo "Terraform demo directory not found: $env_dir"
  exit 1
fi

guard=(uv run --frozen --no-sync python "$repo_root/scripts/terraform_demo_guard.py")
human_guard=(uv run --frozen --no-sync python -m scripts.human_aws_login verify)
"${guard[@]}" verify-backend \
  --input "$BACKEND_CONFIG" \
  --bucket "$BACKEND_BUCKET_NAME" \
  --account-id "$EXPECTED_AWS_ACCOUNT_ID" \
  --region "$AWS_REGION"

"${human_guard[@]}" \
  --profile "$AWS_PROFILE" \
  --region "$AWS_REGION" \
  --expected-account-id "$EXPECTED_AWS_ACCOUNT_ID" >/dev/null

actual_account="$(aws sts get-caller-identity --profile "$AWS_PROFILE" --region "$AWS_REGION" --query Account --output text)"
if [[ "$actual_account" != "$EXPECTED_AWS_ACCOUNT_ID" ]]; then
  echo "Refusing to destroy: caller account does not match EXPECTED_AWS_ACCOUNT_ID."
  exit 1
fi

configured_region="$(aws configure get region --profile "$AWS_PROFILE")"
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
tfvars_mode="$(jq -er '.deployment_governance_mode | select(. == "team_protected" or . == "solo_portfolio")' "$TFVARS_FILE")"
deployed_mode="$(terraform -chdir="$env_dir" output -raw deployment_governance_mode)"
if [[ "$tfvars_mode" != "$governance_mode" || "$deployed_mode" != "$governance_mode" ]]; then
  echo "Refusing to destroy: deployed governance mode cannot be downgraded or substituted."
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

expected_final="DESTROY TEAM modelguard-ai demo"
if [[ "$governance_mode" = "solo_portfolio" ]]; then
  expected_final="DESTROY SOLO modelguard-ai demo"
fi
printf 'Type the exact documented destroy confirmation to apply the reviewed plan: '
read -r final
if [[ "$final" != "$expected_final" ]]; then
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

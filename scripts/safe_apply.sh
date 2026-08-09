#!/usr/bin/env bash
set -euo pipefail

if [[ "${CONFIRM_APPLY:-}" != "YES" ]]; then
  echo "Refusing to apply. Set CONFIRM_APPLY=YES only after reviewing the saved plan."
  exit 1
fi

required_names=(
  EXPECTED_AWS_ACCOUNT_ID
  AWS_REGION
  BACKEND_BUCKET_NAME
  BACKEND_CONFIG
  TFVARS_FILE
  PLAN_STAGE
  AWS_PROFILE
  DEPLOYMENT_GOVERNANCE_MODE
)
for required_name in "${required_names[@]}"; do
  if [[ -z "${!required_name:-}" ]]; then
    echo "Refusing to apply: $required_name is required."
    exit 1
  fi
done

if [[ ! "$EXPECTED_AWS_ACCOUNT_ID" =~ ^[0-9]{12}$ ]]; then
  echo "Refusing to apply: EXPECTED_AWS_ACCOUNT_ID must contain 12 digits."
  exit 1
fi
if [[ "$PLAN_STAGE" != "prerequisites" && "$PLAN_STAGE" != "activation" ]]; then
  echo "Refusing to apply: PLAN_STAGE must be prerequisites or activation."
  exit 1
fi
if [[ "$AWS_PROFILE" != "modelguard-bootstrap" ]]; then
  echo "Refusing to apply: AWS_PROFILE must be modelguard-bootstrap."
  exit 1
fi
if [[ "$DEPLOYMENT_GOVERNANCE_MODE" != "team_protected" && "$DEPLOYMENT_GOVERNANCE_MODE" != "solo_portfolio" ]]; then
  echo "Refusing to apply: DEPLOYMENT_GOVERNANCE_MODE is invalid."
  exit 1
fi
export AWS_PROFILE

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
env_dir="$repo_root/infrastructure/environments/demo"
plan_path="$env_dir/$PLAN_STAGE.tfplan"
manifest_path="$env_dir/$PLAN_STAGE.tfplan.identity.json"
guard=(uv run --frozen --no-sync python "$repo_root/scripts/terraform_demo_guard.py")
human_guard=(uv run --frozen --no-sync python -m scripts.human_aws_login verify)

for input_path in "$BACKEND_CONFIG" "$TFVARS_FILE" "$plan_path" "$manifest_path"; do
  if [[ ! -f "$input_path" ]]; then
    echo "Refusing to apply: required input is missing: $input_path"
    exit 1
  fi
done

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
  echo "Refusing to apply: caller account does not match EXPECTED_AWS_ACCOUNT_ID."
  exit 1
fi

configured_region="$(aws configure get region --profile "$AWS_PROFILE")"
if [[ "$configured_region" != "$AWS_REGION" ]]; then
  echo "Refusing to apply: configured AWS Region does not match AWS_REGION."
  exit 1
fi

terraform -chdir="$env_dir" init -reconfigure -backend-config="$BACKEND_CONFIG"
workspace="$(terraform -chdir="$env_dir" workspace show)"
if [[ "$workspace" != "default" ]]; then
  echo "Refusing to apply: only the default Terraform workspace is permitted."
  exit 1
fi
tfvars_mode="$(jq -er '.deployment_governance_mode | select(. == "team_protected" or . == "solo_portfolio")' "$TFVARS_FILE")"
if [[ "$tfvars_mode" != "$DEPLOYMENT_GOVERNANCE_MODE" ]]; then
  echo "Refusing to apply: variable-file governance mode differs from the approved mode."
  exit 1
fi
if [[ "$PLAN_STAGE" = "activation" ]]; then
  deployed_mode="$(terraform -chdir="$env_dir" output -raw deployment_governance_mode)"
  if [[ "$deployed_mode" != "$DEPLOYMENT_GOVERNANCE_MODE" ]]; then
    echo "Refusing to apply: deployed governance mode cannot be downgraded or substituted."
    exit 1
  fi
fi

terraform -chdir="$env_dir" show "$plan_path"
"${guard[@]}" verify-plan \
  --plan "$plan_path" \
  --var-file "$TFVARS_FILE" \
  --backend-config "$BACKEND_CONFIG" \
  --stage "$PLAN_STAGE" \
  --account-id "$EXPECTED_AWS_ACCOUNT_ID" \
  --region "$AWS_REGION" \
  --repository "$repo_root" \
  --manifest "$manifest_path"

printf 'Type the exact reviewed stage %s to continue: ' "$PLAN_STAGE"
read -r answer
if [[ "$answer" != "$PLAN_STAGE" ]]; then
  echo "Apply cancelled."
  exit 1
fi

# Re-run every local identity check immediately before the only mutating command.
"${guard[@]}" verify-backend \
  --input "$BACKEND_CONFIG" \
  --bucket "$BACKEND_BUCKET_NAME" \
  --account-id "$EXPECTED_AWS_ACCOUNT_ID" \
  --region "$AWS_REGION"
"${guard[@]}" verify-plan \
  --plan "$plan_path" \
  --var-file "$TFVARS_FILE" \
  --backend-config "$BACKEND_CONFIG" \
  --stage "$PLAN_STAGE" \
  --account-id "$EXPECTED_AWS_ACCOUNT_ID" \
  --region "$AWS_REGION" \
  --repository "$repo_root" \
  --manifest "$manifest_path"

terraform -chdir="$env_dir" apply "$plan_path"

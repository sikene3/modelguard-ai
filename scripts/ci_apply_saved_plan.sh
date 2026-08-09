#!/usr/bin/env bash
set -euo pipefail

if [[ "${GITHUB_ACTIONS:-}" != "true" || "${GITHUB_EVENT_NAME:-}" != "workflow_dispatch" ]]; then
  echo "Refusing apply outside an explicitly dispatched GitHub Actions run."
  exit 1
fi
if [[ "${GITHUB_REF:-}" != "refs/heads/main" ]]; then
  echo "Refusing apply outside protected main."
  exit 1
fi
if [[ "${MODELGUARD_GITHUB_ENVIRONMENT:-}" != "demo" && "${MODELGUARD_GITHUB_ENVIRONMENT:-}" != "demo-destroy" ]]; then
  echo "Refusing apply outside an exact protected demo environment."
  exit 1
fi
if [[ "${CONFIRM_APPLY:-}" != "YES" ]]; then
  echo "Refusing apply without the exact protected-workflow confirmation."
  exit 1
fi

required_names=(
  EXPECTED_AWS_ACCOUNT_ID
  AWS_REGION
  BACKEND_BUCKET_NAME
  BACKEND_CONFIG
  TFVARS_FILE
  PLAN_STAGE
  PLAN_FILE
  PLAN_MANIFEST
  DEPLOYMENT_GOVERNANCE_MODE
  GITHUB_SHA
)
for required_name in "${required_names[@]}"; do
  if [[ -z "${!required_name:-}" ]]; then
    echo "Refusing apply: ${required_name} is required."
    exit 1
  fi
done
if [[ ! "$EXPECTED_AWS_ACCOUNT_ID" =~ ^[0-9]{12}$ ]]; then
  echo "Refusing apply: account identity is invalid."
  exit 1
fi
if [[ "$PLAN_STAGE" != "prerequisites" && "$PLAN_STAGE" != "activation" && "$PLAN_STAGE" != "destroy" ]]; then
  echo "Refusing apply: stage must be prerequisites, activation, or destroy."
  exit 1
fi
if [[ "$PLAN_STAGE" = "destroy" && "$MODELGUARD_GITHUB_ENVIRONMENT" != "demo-destroy" ]]; then
  echo "Refusing destroy outside the exact demo-destroy environment."
  exit 1
fi
if [[ "$PLAN_STAGE" != "destroy" && "$MODELGUARD_GITHUB_ENVIRONMENT" != "demo" ]]; then
  echo "Refusing non-destroy apply outside the exact demo environment."
  exit 1
fi
if [[ "$DEPLOYMENT_GOVERNANCE_MODE" != "team_protected" && "$DEPLOYMENT_GOVERNANCE_MODE" != "solo_portfolio" ]]; then
  echo "Refusing apply: deployment governance mode is invalid."
  exit 1
fi

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
env_dir="$repo_root/infrastructure/environments/demo"
guard=(uv run --frozen --no-sync python "$repo_root/scripts/terraform_demo_guard.py")

for input_path in "$BACKEND_CONFIG" "$TFVARS_FILE" "$PLAN_FILE" "$PLAN_MANIFEST"; do
  if [[ ! -f "$input_path" ]]; then
    echo "Refusing apply: one required same-run transfer file is missing."
    exit 1
  fi
done
if [[ "$(git -C "$repo_root" rev-parse HEAD)" != "$GITHUB_SHA" ]]; then
  echo "Refusing apply: checked-out commit differs from the workflow source commit."
  exit 1
fi
tfvars_mode="$(jq -er '.deployment_governance_mode | select(. == "team_protected" or . == "solo_portfolio")' "$TFVARS_FILE")"
if [[ "$tfvars_mode" != "$DEPLOYMENT_GOVERNANCE_MODE" ]]; then
  echo "Refusing apply: variable-file governance mode differs from the reviewed mode."
  exit 1
fi

"${guard[@]}" verify-backend \
  --input "$BACKEND_CONFIG" \
  --bucket "$BACKEND_BUCKET_NAME" \
  --account-id "$EXPECTED_AWS_ACCOUNT_ID" \
  --region "$AWS_REGION"

actual_account="$(aws sts get-caller-identity --query Account --output text)"
if [[ "$actual_account" != "$EXPECTED_AWS_ACCOUNT_ID" ]]; then
  echo "Refusing apply: OIDC caller account mismatch."
  exit 1
fi

terraform -chdir="$env_dir" init -input=false -reconfigure -lockfile=readonly \
  -backend-config="$BACKEND_CONFIG"
workspace="$(terraform -chdir="$env_dir" workspace show)"
if [[ "$workspace" != "default" ]]; then
  echo "Refusing apply: only the default workspace is permitted."
  exit 1
fi
if [[ "$PLAN_STAGE" != "prerequisites" ]]; then
  deployed_mode="$(terraform -chdir="$env_dir" output -raw deployment_governance_mode)"
  if [[ "$deployed_mode" != "$DEPLOYMENT_GOVERNANCE_MODE" ]]; then
    echo "Refusing apply: deployed governance mode cannot be downgraded or substituted."
    exit 1
  fi
fi

verify_plan() {
  "${guard[@]}" verify-plan \
    --plan "$PLAN_FILE" \
    --var-file "$TFVARS_FILE" \
    --backend-config "$BACKEND_CONFIG" \
    --stage "$PLAN_STAGE" \
    --account-id "$EXPECTED_AWS_ACCOUNT_ID" \
    --region "$AWS_REGION" \
    --repository "$repo_root" \
    --manifest "$PLAN_MANIFEST"
}

verify_plan
if [[ "$PLAN_STAGE" == "activation" ]]; then
  pointer_response="$(mktemp)"
  trap 'rm -f "$pointer_response"' EXIT
  if ! aws ssm get-parameter \
    --name /modelguard-ai/demo/models/active >"$pointer_response"; then
    echo "Refusing activation: live pointer read failed." >&2
    exit 1
  fi
  "${guard[@]}" verify-active-pointer \
    --pointer-response "$pointer_response" \
    --var-file "$TFVARS_FILE" \
    --account-id "$EXPECTED_AWS_ACCOUNT_ID" \
    --region "$AWS_REGION"
fi
# The protected environment approval is the human confirmation. Recheck identity immediately before
# the sole mutation; never render the raw plan because it can contain sensitive values.
verify_plan
if ! terraform -chdir="$env_dir" apply -input=false -auto-approve -no-color \
  "$PLAN_FILE" >/dev/null 2>&1; then
  echo "Saved-plan apply failed; raw Terraform output was suppressed." >&2
  exit 1
fi
echo '{"status":"passed","operation":"saved-plan-apply"}'

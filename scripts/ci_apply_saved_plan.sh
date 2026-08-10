#!/usr/bin/env bash
set -euo pipefail
umask 077

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
  EXPECTED_AWS_ROLE_ARN
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
if [[ "$AWS_REGION" != "us-east-1" ]]; then
  echo "Refusing apply: Region must be the canonical us-east-1."
  exit 1
fi
expected_deploy_role_arn="arn:aws:iam::${EXPECTED_AWS_ACCOUNT_ID}:role/modelguard-ai/bootstrap/modelguard-ai-ci-deploy"
if [[ "$EXPECTED_AWS_ROLE_ARN" != "$expected_deploy_role_arn" ]]; then
  echo "Refusing apply: expected deploy-role identity is invalid."
  exit 1
fi
if [[ -n "${AWS_PROFILE:-}" || -n "${AWS_DEFAULT_PROFILE:-}" ]]; then
  echo "Refusing apply: named AWS profiles are forbidden in the OIDC workflow."
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
private_runtime_dir=""
cleanup_private_runtime() {
  local original_status=$?
  local cleanup_failed=false
  trap - EXIT
  if [[ -z "$private_runtime_dir" ]]; then
    exit "$original_status"
  fi
  rm -f -- \
    "$private_runtime_dir/caller-identity.json" \
    "$private_runtime_dir/active-pointer.json" || cleanup_failed=true
  if [[ -d "$private_runtime_dir" && ! -L "$private_runtime_dir" && -O "$private_runtime_dir" ]]; then
    rmdir -- "$private_runtime_dir" 2>/dev/null || cleanup_failed=true
  else
    cleanup_failed=true
  fi
  if [[ "$cleanup_failed" = true ]]; then
    echo "Temporary workflow identity cleanup failed." >&2
    exit 1
  fi
  exit "$original_status"
}
if ! private_runtime_dir="$(mktemp -d)"; then
  echo "Refusing apply: secure workflow identity directory could not be created." >&2
  exit 1
fi
trap cleanup_private_runtime EXIT
if ! chmod 0700 "$private_runtime_dir" \
  || [[ ! -d "$private_runtime_dir" || -L "$private_runtime_dir" || ! -O "$private_runtime_dir" ]] \
  || [[ "$(stat -c '%a' -- "$private_runtime_dir" 2>/dev/null || true)" != "700" ]]; then
  echo "Refusing apply: workflow identity directory is not owner-only." >&2
  exit 1
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
verify_plan
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

verify_oidc_identity() {
  local actual_account
  local actual_arn
  local assumed_role_prefix
  local identity_file="$private_runtime_dir/caller-identity.json"
  local role_session_name
  if ! aws sts get-caller-identity \
    --region "$AWS_REGION" \
    --query '{Account:Account,Arn:Arn}' \
    --output json >"$identity_file" 2>/dev/null; then
    echo "Refusing apply: OIDC caller identity lookup failed." >&2
    return 1
  fi
  chmod 0600 "$identity_file"
  if ! jq -e '
    type == "object"
    and (keys | sort) == ["Account", "Arn"]
    and (.Account | type == "string")
    and (.Arn | type == "string")
  ' "$identity_file" >/dev/null 2>&1; then
    echo "Refusing apply: OIDC caller identity response is invalid." >&2
    return 1
  fi
  actual_account="$(jq -r '.Account' "$identity_file")"
  actual_arn="$(jq -r '.Arn' "$identity_file")"
  if [[ "$actual_account" != "$EXPECTED_AWS_ACCOUNT_ID" ]]; then
    echo "Refusing apply: OIDC caller account mismatch."
    return 1
  fi
  assumed_role_prefix="arn:aws:sts::${EXPECTED_AWS_ACCOUNT_ID}:assumed-role/modelguard-ai-ci-deploy/"
  if [[ "$actual_arn" != "$assumed_role_prefix"* ]]; then
    echo "Refusing apply: OIDC caller role mismatch."
    return 1
  fi
  role_session_name="${actual_arn#"$assumed_role_prefix"}"
  if [[ ! "$role_session_name" =~ ^[A-Za-z0-9+=,.@_-]{2,64}$ ]]; then
    echo "Refusing apply: OIDC role session is invalid."
    return 1
  fi
}

verify_oidc_identity

terraform -chdir="$env_dir" init -input=false -reconfigure -lockfile=readonly \
  -backend-config="$BACKEND_CONFIG"
workspace="$(terraform -chdir="$env_dir" workspace show)"
if [[ "$workspace" != "default" ]]; then
  echo "Refusing apply: only the default workspace is permitted."
  exit 1
fi
if [[ "$PLAN_STAGE" == "activation" ]]; then
  deployed_mode="$(terraform -chdir="$env_dir" output -raw deployment_governance_mode)"
  if [[ "$deployed_mode" != "$DEPLOYMENT_GOVERNANCE_MODE" ]]; then
    echo "Refusing apply: deployed governance mode cannot be downgraded or substituted."
    exit 1
  fi
fi

verify_plan
if [[ "$PLAN_STAGE" == "activation" ]]; then
  pointer_response="$private_runtime_dir/active-pointer.json"
  if ! aws ssm get-parameter \
    --name /modelguard-ai/demo/models/active \
    --region "$AWS_REGION" \
    --no-with-decryption >"$pointer_response" 2>/dev/null; then
    echo "Refusing activation: live pointer read failed." >&2
    exit 1
  fi
  chmod 0600 "$pointer_response"
  "${guard[@]}" verify-active-pointer \
    --pointer-response "$pointer_response" \
    --var-file "$TFVARS_FILE" \
    --account-id "$EXPECTED_AWS_ACCOUNT_ID" \
    --region "$AWS_REGION"
fi
# The protected environment approval is the human confirmation. Recheck the plan and exact OIDC
# identity immediately before the sole mutation; never render the raw plan because it can contain
# sensitive values.
verify_plan
verify_oidc_identity
if ! terraform -chdir="$env_dir" apply -input=false -auto-approve -no-color \
  "$PLAN_FILE" >/dev/null 2>&1; then
  echo "Saved-plan apply failed; raw Terraform output was suppressed." >&2
  exit 1
fi
echo '{"status":"passed","operation":"saved-plan-apply"}'

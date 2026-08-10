#!/usr/bin/env bash
set -euo pipefail
umask 077

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
if [[ "$AWS_REGION" != "us-east-1" ]]; then
  echo "Refusing to apply: AWS_REGION must be the canonical us-east-1."
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
plan_evidence=(uv run --frozen --no-sync python -m scripts.plan_evidence)
review_dir=""
evidence_json=""
evidence_markdown=""
pointer_response=""

verify_human_identity() {
  local actual_account
  local configured_region
  if ! "${human_guard[@]}" \
    --profile "$AWS_PROFILE" \
    --region "$AWS_REGION" \
    --expected-account-id "$EXPECTED_AWS_ACCOUNT_ID" >/dev/null 2>&1; then
    echo "Refusing to apply: browser-login identity verification failed." >&2
    return 1
  fi
  if ! actual_account="$(aws sts get-caller-identity \
    --profile "$AWS_PROFILE" \
    --region "$AWS_REGION" \
    --query Account \
    --output text 2>/dev/null)"; then
    echo "Refusing to apply: caller account lookup failed." >&2
    return 1
  fi
  if [[ "$actual_account" != "$EXPECTED_AWS_ACCOUNT_ID" ]]; then
    echo "Refusing to apply: caller account does not match EXPECTED_AWS_ACCOUNT_ID."
    return 1
  fi
  if ! configured_region="$(aws configure get region --profile "$AWS_PROFILE" 2>/dev/null)"; then
    echo "Refusing to apply: configured AWS Region lookup failed." >&2
    return 1
  fi
  if [[ "$configured_region" != "$AWS_REGION" ]]; then
    echo "Refusing to apply: configured AWS Region does not match AWS_REGION."
    return 1
  fi
}

cleanup_review_dir() {
  local original_status=$?
  local cleanup_failed=false
  local temporary_path
  trap - EXIT
  for temporary_path in "$pointer_response" "$evidence_json" "$evidence_markdown"; do
    if [[ -n "$temporary_path" ]] && ! rm -f -- "$temporary_path"; then
      cleanup_failed=true
    fi
  done
  if [[ -n "$review_dir" ]]; then
    if [[ -d "$review_dir" && ! -L "$review_dir" && -O "$review_dir" ]]; then
      if ! rmdir -- "$review_dir"; then
        cleanup_failed=true
      fi
    else
      cleanup_failed=true
    fi
  fi
  if [[ "$cleanup_failed" = true ]]; then
    echo "Temporary plan-review cleanup failed." >&2
    exit 1
  fi
  exit "$original_status"
}

if [[ ! -f "$TFVARS_FILE" || -L "$TFVARS_FILE" || ! -O "$TFVARS_FILE" ]]; then
  echo "Refusing to apply: TFVARS_FILE must be an operator-owned regular file, not a symlink."
  exit 1
fi
case "$TFVARS_FILE" in
  *.tfvars.json) ;;
  *)
    echo "Refusing to apply: TFVARS_FILE must be the rendered *.tfvars.json file."
    exit 1
    ;;
esac
tfvars_permissions="$(stat -c '%a' -- "$TFVARS_FILE" 2>/dev/null || true)"
if [[ "$tfvars_permissions" != "600" ]]; then
  echo "Refusing to apply: TFVARS_FILE must have exact mode 0600."
  exit 1
fi
if ! jq -e 'type == "object"' "$TFVARS_FILE" >/dev/null 2>&1; then
  echo "Refusing to apply: TFVARS_FILE must contain valid JSON rendered by scripts.render_ci_terraform."
  exit 1
fi

for input_path in "$BACKEND_CONFIG" "$plan_path" "$manifest_path"; do
  if [[ ! -f "$input_path" ]]; then
    echo "Refusing to apply: a required backend, saved-plan, or identity file is missing."
    exit 1
  fi
done

"${guard[@]}" verify-backend \
  --input "$BACKEND_CONFIG" \
  --bucket "$BACKEND_BUCKET_NAME" \
  --account-id "$EXPECTED_AWS_ACCOUNT_ID" \
  --region "$AWS_REGION"

verify_human_identity

terraform -chdir="$env_dir" init -input=false -reconfigure -lockfile=readonly \
  -backend-config="$BACKEND_CONFIG"
workspace="$(terraform -chdir="$env_dir" workspace show)"
if [[ "$workspace" != "default" ]]; then
  echo "Refusing to apply: only the default Terraform workspace is permitted."
  exit 1
fi
if ! tfvars_mode="$(jq -er '.deployment_governance_mode | select(. == "team_protected" or . == "solo_portfolio")' "$TFVARS_FILE" 2>/dev/null)"; then
  echo "Refusing to apply: rendered variable file has no valid deployment governance mode."
  exit 1
fi
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

"${guard[@]}" verify-plan \
  --plan "$plan_path" \
  --var-file "$TFVARS_FILE" \
  --backend-config "$BACKEND_CONFIG" \
  --stage "$PLAN_STAGE" \
  --account-id "$EXPECTED_AWS_ACCOUNT_ID" \
  --region "$AWS_REGION" \
  --repository "$repo_root" \
  --manifest "$manifest_path"

if ! review_dir="$(mktemp -d)"; then
  echo "Refusing to apply: secure temporary plan-review directory could not be created."
  exit 1
fi
trap cleanup_review_dir EXIT
if ! chmod 0700 "$review_dir" \
  || [[ ! -d "$review_dir" || -L "$review_dir" || ! -O "$review_dir" ]] \
  || [[ "$(stat -c '%a' -- "$review_dir" 2>/dev/null || true)" != "700" ]]; then
  echo "Refusing to apply: temporary plan-review directory is not owner-only."
  exit 1
fi
evidence_json="$review_dir/plan.redacted.json"
evidence_markdown="$review_dir/plan.redacted.md"
if ! terraform -chdir="$env_dir" show -json "$plan_path" 2>/dev/null \
  | "${plan_evidence[@]}" \
      --plan "$plan_path" \
      --manifest "$manifest_path" \
      --output-json "$evidence_json" \
      --output-markdown "$evidence_markdown" \
      --repository local/operator \
      --run-id human \
      --run-attempt 1 \
      --workflow-ref local/operator >/dev/null 2>&1; then
  echo "Refusing to apply: sealed redacted plan evidence could not be rendered."
  exit 1
fi
if [[ ! -f "$evidence_json" || -L "$evidence_json" || ! -O "$evidence_json" \
  || ! -f "$evidence_markdown" || -L "$evidence_markdown" || ! -O "$evidence_markdown" \
  || "$(stat -c '%a' -- "$evidence_json" 2>/dev/null || true)" != "600" \
  || "$(stat -c '%a' -- "$evidence_markdown" 2>/dev/null || true)" != "600" ]]; then
  echo "Refusing to apply: temporary plan-review evidence is not owner-only."
  exit 1
fi
if ! cat "$evidence_markdown"; then
  echo "Refusing to apply: sealed redacted plan evidence could not be displayed."
  exit 1
fi

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

if [[ "$PLAN_STAGE" = "activation" ]]; then
  pointer_response="$review_dir/active-pointer.json"
  if ! aws ssm get-parameter \
    --name /modelguard-ai/demo/models/active \
    --profile "$AWS_PROFILE" \
    --region "$AWS_REGION" \
    --no-with-decryption \
    --no-cli-pager \
    --output json >"$pointer_response" 2>/dev/null; then
    echo "Refusing to apply: live active-pointer read failed."
    exit 1
  fi
  if [[ ! -f "$pointer_response" || -L "$pointer_response" || ! -O "$pointer_response" \
    || "$(stat -c '%a' -- "$pointer_response" 2>/dev/null || true)" != "600" ]]; then
    echo "Refusing to apply: temporary active-pointer response is not owner-only."
    exit 1
  fi
  "${guard[@]}" verify-active-pointer \
    --pointer-response "$pointer_response" \
    --var-file "$TFVARS_FILE" \
    --account-id "$EXPECTED_AWS_ACCOUNT_ID" \
      --region "$AWS_REGION"
fi

verify_human_identity
if ! terraform -chdir="$env_dir" apply -input=false -auto-approve -no-color \
  "$plan_path" >/dev/null 2>&1; then
  echo "Saved-plan apply failed; raw Terraform output was suppressed." >&2
  exit 1
fi
echo '{"status":"passed","operation":"saved-plan-apply"}'

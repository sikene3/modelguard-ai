#!/usr/bin/env bash
set -euo pipefail
umask 077

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
  TEARDOWN_AUTHORIZED
  AWS_PROFILE
  POST_DESTROY_INVENTORY
)
for required_name in "${required_names[@]}"; do
  if [[ -z "${!required_name:-}" ]]; then
    echo "Refusing to destroy: $required_name is required."
    exit 1
  fi
done

if [[ "$TEARDOWN_AUTHORIZED" != "true" ]]; then
  echo "Refusing to destroy: TEARDOWN_AUTHORIZED must be exactly true for this one guarded run."
  exit 1
fi

if [[ ! "$EXPECTED_AWS_ACCOUNT_ID" =~ ^[0-9]{12}$ ]]; then
  echo "Refusing to destroy: EXPECTED_AWS_ACCOUNT_ID must contain 12 digits."
  exit 1
fi
if [[ "$AWS_PROFILE" != "modelguard-bootstrap" ]]; then
  echo "Refusing to destroy: AWS_PROFILE must be modelguard-bootstrap."
  exit 1
fi
if [[ "$AWS_REGION" != "us-east-1" ]]; then
  echo "Refusing to destroy: AWS_REGION must be the canonical us-east-1."
  exit 1
fi
export AWS_PROFILE

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
env_dir="$repo_root/infrastructure/environments/demo"

if [[ ! -d "$env_dir" ]]; then
  echo "Refusing to destroy: Terraform demo directory is missing."
  exit 1
fi

if [[ "$POST_DESTROY_INVENTORY" != /* ]]; then
  echo "Refusing to destroy: POST_DESTROY_INVENTORY must be an absolute new evidence path."
  exit 1
fi
inventory_parent="$(dirname -- "$POST_DESTROY_INVENTORY")"
if [[ ! -d "$inventory_parent" || -L "$inventory_parent" || ! -O "$inventory_parent" \
  || "$(stat -c '%a' -- "$inventory_parent" 2>/dev/null || true)" != "700" ]]; then
  echo "Refusing to destroy: the inventory evidence parent must already be owner-only mode 0700."
  exit 1
fi
if [[ -e "$POST_DESTROY_INVENTORY" || -L "$POST_DESTROY_INVENTORY" ]]; then
  echo "Refusing to destroy: POST_DESTROY_INVENTORY must not already exist."
  exit 1
fi

plan_path="$env_dir/destroy.tfplan"
manifest_path="$env_dir/destroy.tfplan.identity.json"
evidence_json="$plan_path.redacted.json"
evidence_markdown="$plan_path.redacted.md"
for planned_output in "$plan_path" "$manifest_path" "$evidence_json" "$evidence_markdown"; do
  if [[ -e "$planned_output" || -L "$planned_output" ]]; then
    echo "Refusing to destroy: a destroy plan, identity, or redacted-evidence target already exists."
    exit 1
  fi
done

guard=(uv run --frozen --no-sync python "$repo_root/scripts/terraform_demo_guard.py")
human_guard=(uv run --frozen --no-sync python -m scripts.human_aws_login verify)
plan_evidence=(uv run --frozen --no-sync python -m scripts.plan_evidence)

verify_human_identity() {
  local actual_account
  local configured_region
  if ! "${human_guard[@]}" \
    --profile "$AWS_PROFILE" \
    --region "$AWS_REGION" \
    --expected-account-id "$EXPECTED_AWS_ACCOUNT_ID" >/dev/null 2>&1; then
    echo "Refusing to destroy: browser-login identity verification failed." >&2
    return 1
  fi
  if ! actual_account="$(aws sts get-caller-identity \
    --profile "$AWS_PROFILE" \
    --region "$AWS_REGION" \
    --query Account \
    --output text 2>/dev/null)"; then
    echo "Refusing to destroy: caller account lookup failed." >&2
    return 1
  fi
  if [[ "$actual_account" != "$EXPECTED_AWS_ACCOUNT_ID" ]]; then
    echo "Refusing to destroy: caller account does not match EXPECTED_AWS_ACCOUNT_ID."
    return 1
  fi
  if ! configured_region="$(aws configure get region --profile "$AWS_PROFILE" 2>/dev/null)"; then
    echo "Refusing to destroy: configured AWS Region lookup failed." >&2
    return 1
  fi
  if [[ "$configured_region" != "$AWS_REGION" ]]; then
    echo "Refusing to destroy: configured AWS Region does not match AWS_REGION."
    return 1
  fi
}

if [[ ! -f "$TFVARS_FILE" || -L "$TFVARS_FILE" || ! -O "$TFVARS_FILE" ]]; then
  echo "Refusing to destroy: TFVARS_FILE must be an operator-owned regular file, not a symlink."
  exit 1
fi
case "$TFVARS_FILE" in
  *.tfvars.json) ;;
  *)
    echo "Refusing to destroy: TFVARS_FILE must be the rendered *.tfvars.json file."
    exit 1
    ;;
esac
tfvars_permissions="$(stat -c '%a' -- "$TFVARS_FILE" 2>/dev/null || true)"
if [[ "$tfvars_permissions" != "600" ]]; then
  echo "Refusing to destroy: TFVARS_FILE must have exact mode 0600."
  exit 1
fi
if ! jq -e 'type == "object"' "$TFVARS_FILE" >/dev/null 2>&1; then
  echo "Refusing to destroy: TFVARS_FILE must contain valid JSON rendered by scripts.render_ci_terraform."
  exit 1
fi
if ! jq -e --arg auto_destroy_date "$AUTO_DESTROY_DATE" '
  .deployment_stage == "prerequisites" and
  .activate_services == false and
  .teardown_authorized == true and
  .runtime_contract_verified == false and
  .budget_prerequisite_verified == false and
  .auto_destroy_date == $auto_destroy_date and
  (has("api_image_ref") | not) and
  (has("dashboard_image_ref") | not) and
  (has("monitor_image_ref") | not) and
  (has("expected_model_version") | not) and
  (has("expected_model_manifest_sha256") | not) and
  (has("expected_model_object_version_ids") | not)
' "$TFVARS_FILE" >/dev/null 2>&1; then
  echo "Refusing to destroy: rendered inputs do not match the exact dormant teardown contract."
  exit 1
fi

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
  echo "Refusing to destroy: only the default Terraform workspace is permitted."
  exit 1
fi
if ! tfvars_mode="$(jq -er '.deployment_governance_mode | select(. == "team_protected" or . == "solo_portfolio")' "$TFVARS_FILE" 2>/dev/null)"; then
  echo "Refusing to destroy: rendered variable file has no valid deployment governance mode."
  exit 1
fi
if [[ "$tfvars_mode" != "$governance_mode" ]]; then
  echo "Refusing to destroy: rendered governance mode cannot be downgraded or substituted."
  exit 1
fi

printf 'Type the exact project name modelguard-ai to continue: '
read -r answer
if [[ "$answer" != "modelguard-ai" ]]; then
  echo "Confirmation mismatch."
  exit 1
fi

if ! terraform -chdir="$env_dir" plan -input=false -no-color -destroy \
  -var-file="$TFVARS_FILE" -out="$plan_path" >/dev/null 2>&1; then
  echo "Destroy-plan creation failed; raw Terraform output was suppressed." >&2
  exit 1
fi
if ! source_activation_state="$(
  terraform -chdir="$env_dir" show -json "$plan_path" 2>/dev/null |
    "${guard[@]}" classify-destroy-plan-source-state 2>/dev/null
)"; then
  echo "Refusing to destroy: saved-plan source-state classification failed." >&2
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
  --activate-services false \
  --source-activation-state "$source_activation_state" \
  --output "$manifest_path"

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
  echo "Refusing to destroy: sealed redacted plan evidence could not be rendered."
  exit 1
fi
if [[ ! -f "$evidence_json" || -L "$evidence_json" || ! -O "$evidence_json" \
  || ! -f "$evidence_markdown" || -L "$evidence_markdown" || ! -O "$evidence_markdown" \
  || "$(stat -c '%a' -- "$evidence_json" 2>/dev/null || true)" != "600" \
  || "$(stat -c '%a' -- "$evidence_markdown" 2>/dev/null || true)" != "600" ]]; then
  echo "Refusing to destroy: persistent redacted plan evidence is not owner-only."
  exit 1
fi
if ! cat "$evidence_markdown"; then
  echo "Refusing to destroy: sealed redacted plan evidence could not be displayed."
  exit 1
fi

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

verify_human_identity
if ! terraform -chdir="$env_dir" apply -input=false -auto-approve -no-color \
  "$plan_path" >/dev/null 2>&1; then
  echo "Saved destroy-plan apply failed; raw Terraform output was suppressed." >&2
  exit 1
fi

EXPECTED_AWS_ACCOUNT_ID="$EXPECTED_AWS_ACCOUNT_ID" \
  AWS_REGION="$AWS_REGION" \
  INVENTORY_OUTPUT="$POST_DESTROY_INVENTORY" \
  "$repo_root/scripts/verify_aws_teardown.sh"

echo "Tagged and service-specific demo inventories are empty. Bootstrap resources remain intentionally retained."

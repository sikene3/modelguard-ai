#!/usr/bin/env bash
set -euo pipefail
set +x

operation="${1:-}"
if [[ "$operation" != "upload" && "$operation" != "download" && "$operation" != "delete" ]]; then
  echo "Refusing confidential plan transfer: operation must be upload, download, or delete."
  exit 2
fi
if [[ "${GITHUB_ACTIONS:-}" != "true" || "${GITHUB_EVENT_NAME:-}" != "workflow_dispatch" ]]; then
  echo "Refusing confidential plan transfer outside an explicitly dispatched workflow."
  exit 2
fi
if [[ -n "${AWS_PROFILE:-}" ]]; then
  echo "Refusing confidential plan transfer with a human AWS profile in workflow mode."
  exit 2
fi

required_names=(
  AWS_ACCOUNT_ID
  AWS_REGION
  BACKEND_BUCKET
  BACKEND_KMS_KEY_ARN
  GITHUB_RUN_ID
  GITHUB_RUN_ATTEMPT
  PLAN_STAGE
  TRANSFER_DIRECTORY
)
for required_name in "${required_names[@]}"; do
  if [[ -z "${!required_name:-}" ]]; then
    echo "Refusing confidential plan transfer: ${required_name} is required."
    exit 2
  fi
done
if [[ ! "$AWS_ACCOUNT_ID" =~ ^[0-9]{12}$ || "$AWS_REGION" != "us-east-1" ]]; then
  echo "Refusing confidential plan transfer: account or Region identity is invalid."
  exit 2
fi
if [[ ! "$GITHUB_RUN_ID" =~ ^[0-9]+$ || ! "$GITHUB_RUN_ATTEMPT" =~ ^[0-9]+$ ]]; then
  echo "Refusing confidential plan transfer: run identity is invalid."
  exit 2
fi
if [[ "$PLAN_STAGE" != "prerequisites" && "$PLAN_STAGE" != "activation" && "$PLAN_STAGE" != "destroy" ]]; then
  echo "Refusing confidential plan transfer: stage is invalid."
  exit 2
fi
if [[ "$BACKEND_BUCKET" != "modelguard-ai-terraform-state-${AWS_ACCOUNT_ID}-${AWS_REGION}" ]]; then
  echo "Refusing confidential plan transfer: backend bucket identity is invalid."
  exit 2
fi
if [[ ! "$BACKEND_KMS_KEY_ARN" =~ ^arn:aws:kms:us-east-1:${AWS_ACCOUNT_ID}:key/[0-9a-f-]{36}$ ]]; then
  echo "Refusing confidential plan transfer: backend KMS identity is invalid."
  exit 2
fi

case "$PLAN_STAGE" in
  prerequisites) plan_name="prerequisites.tfplan" ;;
  activation) plan_name="activation.tfplan" ;;
  destroy) plan_name="destroy.tfplan" ;;
esac
transfer_names=("$plan_name" "${plan_name}.identity.json" "demo-ci.tfvars.json" "backend.hcl")
if [[ "$PLAN_STAGE" = "activation" ]]; then
  transfer_names+=("active-pointer.json")
fi
transfer_prefix="reviewed-plans/${GITHUB_RUN_ID}/${GITHUB_RUN_ATTEMPT}/${PLAN_STAGE}"

if [[ "$operation" = "upload" ]]; then
  for name in "${transfer_names[@]}"; do
    path="${TRANSFER_DIRECTORY}/${name}"
    if [[ ! -f "$path" || -L "$path" ]]; then
      echo "Refusing confidential plan upload: an exact regular transfer file is missing."
      exit 2
    fi
    aws s3api put-object \
      --bucket "$BACKEND_BUCKET" \
      --key "${transfer_prefix}/${name}" \
      --body "$path" \
      --server-side-encryption aws:kms \
      --ssekms-key-id "$BACKEND_KMS_KEY_ARN" \
      --if-none-match '*' \
      --expected-bucket-owner "$AWS_ACCOUNT_ID" >/dev/null
  done
elif [[ "$operation" = "download" ]]; then
  install -d -m 0700 "$TRANSFER_DIRECTORY"
  for name in "${transfer_names[@]}"; do
    path="${TRANSFER_DIRECTORY}/${name}"
    if [[ -e "$path" || -L "$path" ]]; then
      echo "Refusing confidential plan download over an existing path."
      exit 2
    fi
    aws s3api get-object \
      --bucket "$BACKEND_BUCKET" \
      --key "${transfer_prefix}/${name}" \
      --checksum-mode ENABLED \
      --expected-bucket-owner "$AWS_ACCOUNT_ID" \
      "$path" >/dev/null
    chmod 0600 "$path"
  done
else
  for name in "${transfer_names[@]}"; do
    aws s3api delete-object \
      --bucket "$BACKEND_BUCKET" \
      --key "${transfer_prefix}/${name}" \
      --expected-bucket-owner "$AWS_ACCOUNT_ID" >/dev/null
  done
fi

printf '{"operation":"%s","stage":"%s","status":"passed"}\n' "$operation" "$PLAN_STAGE"

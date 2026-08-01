#!/usr/bin/env bash
set -euo pipefail

if [[ "${CONFIRM_DESTROY:-}" != "YES" ]]; then
  echo "Refusing to destroy. Run with CONFIRM_DESTROY=YES after reviewing the target account, region, workspace, and plan."
  exit 1
fi

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
env_dir="$repo_root/infrastructure/environments/demo"

if [[ ! -d "$env_dir" ]]; then
  echo "Terraform demo directory not found: $env_dir"
  exit 1
fi

aws sts get-caller-identity
printf 'Type the exact project name modelguard-ai to continue: '
read -r answer
if [[ "$answer" != "modelguard-ai" ]]; then
  echo "Confirmation mismatch."
  exit 1
fi

terraform -chdir="$env_dir" plan -destroy -out=destroy.tfplan
terraform -chdir="$env_dir" show destroy.tfplan
printf 'Type DESTROY to apply the reviewed destroy plan: '
read -r final
if [[ "$final" != "DESTROY" ]]; then
  echo "Destroy cancelled."
  exit 1
fi
terraform -chdir="$env_dir" apply destroy.tfplan

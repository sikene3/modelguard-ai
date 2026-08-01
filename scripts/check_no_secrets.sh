#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"

if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  echo "Secret/file check requires a Git work tree."
  exit 2
fi

bad=0

ignored_examples=(
  ".env"
  "config/.env.production"
  "infrastructure/environments/demo/demo.tfvars"
  "infrastructure/environments/demo/demo.tfvars.json"
  "infrastructure/environments/demo/demo.auto.tfvars"
  "infrastructure/environments/demo/terraform.tfstate"
  "infrastructure/environments/demo/terraform.tfstate.backup"
  "infrastructure/environments/demo/apply.tfplan"
)

for path in "${ignored_examples[@]}"; do
  if ! git check-ignore -q -- "$path"; then
    printf '%s: [REDACTED expected sensitive/generated path is not ignored]\n' "$path"
    bad=1
  fi
done

allowed_examples=(
  ".env.example"
  "infrastructure/environments/demo/demo.tfvars.example"
  "infrastructure/environments/demo/demo.tfvars.json.example"
  "infrastructure/environments/demo/demo.auto.tfvars.example"
)

for path in "${allowed_examples[@]}"; do
  if git check-ignore -q -- "$path"; then
    printf '%s: [REDACTED safe example path is unexpectedly ignored]\n' "$path"
    bad=1
  fi
done

secret_pattern='(AKIA|ASIA)[0-9A-Z]{16}|github_pat_[[:alnum:]_]{20,}|gh[pousr]_[[:alnum:]]{20,}|xox[baprs]-[[:alnum:]-]{20,}|sk_live_[[:alnum:]]{20,}|aws_secret_access_key[[:space:]]*[:=][[:space:]]*"?[[:alnum:]/+=]{20,}|-----BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY-----'

while IFS= read -r -d '' path; do
  basename="${path##*/}"

  case "$basename" in
    .env | .env.* | *.tfstate | *.tfstate.* | *.tfplan | *.tfplan.* | tfplan | tfplan.* | \
      *.tfvars | *.tfvars.json | *.pem | *.key | *.p12)
      if [[ "$basename" != ".env.example" && "$basename" != *.tfvars.example && \
        "$basename" != *.tfvars.json.example && "$basename" != *.auto.tfvars.example ]]; then
        printf '%s: [REDACTED sensitive/generated file is tracked or not ignored]\n' "$path"
        bad=1
      fi
      ;;
  esac

  if [[ "$path" == "scripts/check_no_secrets.sh" ]]; then
    continue
  fi

  while IFS=: read -r line_number _; do
    printf '%s:%s: [REDACTED potential secret pattern]\n' "$path" "$line_number"
    bad=1
  done < <(LC_ALL=C grep -IEn -- "$secret_pattern" "$path" 2>/dev/null || true)
done < <(git ls-files --cached --others --exclude-standard -z)

if [[ "$bad" -ne 0 ]]; then
  echo "Basic repository secret/file check failed; inspect the redacted locations."
  exit 1
fi

echo "Basic repository secret/file check passed (defense in depth; not a full secret scanner)."

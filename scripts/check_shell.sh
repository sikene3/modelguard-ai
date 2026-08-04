#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"

shellcheck_bin="$(uv run --frozen --no-sync python -m scripts.security_tools path shellcheck)"
mapfile -d '' -t shell_files < <(
  git ls-files --cached --others --exclude-standard -z -- '*.sh' | sort -z
)
if [[ "${#shell_files[@]}" -eq 0 ]]; then
  echo "No repository shell scripts were found." >&2
  exit 2
fi
for shell_file in "${shell_files[@]}"; do
  bash -n "$shell_file"
done

"$shellcheck_bin" --external-sources "${shell_files[@]}"
printf '{"bash_syntax":"passed","shellcheck":"passed","files":%d}\n' \
  "${#shell_files[@]}"

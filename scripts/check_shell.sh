#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"

mapfile -t shell_files < <(find scripts -maxdepth 1 -type f -name '*.sh' -print | sort)
for shell_file in "${shell_files[@]}"; do
  bash -n "$shell_file"
done

if command -v shellcheck >/dev/null 2>&1; then
  shellcheck --external-sources "${shell_files[@]}"
  printf '{"bash_syntax":"passed","shellcheck":"passed","files":%d}\n' \
    "${#shell_files[@]}"
else
  printf '{"bash_syntax":"passed","shellcheck":"skipped_unavailable","files":%d}\n' \
    "${#shell_files[@]}"
fi

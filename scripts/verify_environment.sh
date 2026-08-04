#!/usr/bin/env bash
set -uo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root" || exit 1

required=(git make uv)
optional=(codex docker terraform aws jq)
missing=0

echo "== Required tools =="
for cmd in "${required[@]}"; do
  if command -v "$cmd" >/dev/null 2>&1; then
    printf "[OK] %-12s %s\n" "$cmd" "$(command -v "$cmd")"
  else
    printf "[MISSING] %s\n" "$cmd"
    missing=1
  fi
done

echo
echo "== Python contract =="
if [[ ! -f .python-version ]]; then
  echo "[MISSING] .python-version"
  missing=1
elif [[ "$(tr -d '[:space:]' < .python-version)" != "3.12" ]]; then
  echo "[INVALID] .python-version must contain 3.12"
  missing=1
else
  echo "[OK] .python-version pins Python 3.12"
fi

if command -v uv >/dev/null 2>&1; then
  python_path="$(uv python find 3.12 2>/dev/null || true)"
  if [[ -z "$python_path" ]]; then
    echo "[MISSING] uv cannot resolve a Python 3.12 interpreter"
    missing=1
  else
    python_minor="$("$python_path" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
    if [[ "$python_minor" != "3.12" ]]; then
      echo "[INVALID] uv resolved a non-3.12 interpreter"
      missing=1
    else
      printf '[OK] %-12s %s\n' "Python 3.12" "$python_path"
      "$python_path" -VV
    fi
  fi
fi

echo
echo "== Later-phase optional tools =="
for cmd in "${optional[@]}"; do
  if command -v "$cmd" >/dev/null 2>&1; then
    printf "[OK] %-12s %s\n" "$cmd" "$(command -v "$cmd")"
  else
    printf "[OPTIONAL MISSING] %s\n" "$cmd"
  fi
done

echo
echo "== Repository-local security scanners =="
if [[ -f .cache/security-tools/install-state.json && -d .venv ]]; then
  uv run --frozen --no-sync python -m scripts.security_tools check
else
  echo "[OPTIONAL MISSING] run make security-tools-bootstrap after uv sync"
fi

echo
echo "== Core versions =="
git --version 2>/dev/null || true
uv --version 2>/dev/null || true

if [[ "$missing" -ne 0 ]]; then
  echo
  echo "Missing Phase 01 requirements. Read the manual-only guide: ./scripts/setup_ubuntu.sh"
  exit 1
fi

echo
echo "Phase 01 environment looks ready."

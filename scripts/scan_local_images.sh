#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"

if ! command -v trivy >/dev/null 2>&1; then
  echo "Trivy is required; install it from the official Aqua Security distribution." >&2
  exit 2
fi
if ! command -v uv >/dev/null 2>&1; then
  echo "uv is required to validate the machine-readable scan evidence." >&2
  exit 2
fi

scan_stamp="$(date -u +%Y%m%dT%H%M%SZ)"
evidence_dir="${TRIVY_EVIDENCE_DIR:-artifacts/phase-07-evidence/trivy-${scan_stamp}}"
mkdir -p "$evidence_dir"
chmod 0700 "$evidence_dir"

declare -a scans=()
for component in api dashboard monitor; do
  image="modelguard-${component}:local"
  output="$evidence_dir/${component}.trivy.json"
  echo "Scanning ${image} for critical vulnerabilities."
  trivy image --quiet --scanners vuln --severity CRITICAL --format json \
    --output "$output" "$image"
  scans+=(--scan "$output")
done

UV_CACHE_DIR="$repo_root/.cache/uv" uv run --frozen --no-sync python \
  scripts/evaluate_trivy_scan.py \
  "${scans[@]}" \
  --exceptions configs/trivy-exceptions.json \
  --output "$evidence_dir/summary.json"
echo "Trivy evidence: ${evidence_dir}/summary.json"

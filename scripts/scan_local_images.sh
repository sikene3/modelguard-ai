#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"

if ! command -v uv >/dev/null 2>&1; then
  echo "uv is required to verify and run the repository-local Trivy binary." >&2
  exit 2
fi

uv run --frozen --no-sync python -m scripts.security_tools check --tool trivy >/dev/null

scan_stamp="$(date -u +%Y%m%dT%H%M%SZ)"
evidence_dir="${TRIVY_EVIDENCE_DIR:-artifacts/phase-07-evidence/trivy-${scan_stamp}}"
mkdir -p "$evidence_dir"
chmod 0700 "$evidence_dir"

for component in api dashboard monitor; do
  image="modelguard-${component}:local"
  image_id="$(docker image inspect --format '{{.Id}}' "$image")"
  echo "Scanning ${image} at ${image_id} for high and critical vulnerabilities."
  SECURITY_SCAN_OUTPUT_DIR="$evidence_dir/sarif" \
    ./scripts/security_scan.sh image \
      --image "$image_id" \
      --component "$component" \
      --output-dir "$evidence_dir"
done

echo "Trivy CycloneDX and sanitized SARIF evidence: ${evidence_dir}"

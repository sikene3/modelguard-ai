#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"
# shellcheck source=scripts/local_compose_lib.sh
source scripts/local_compose_lib.sh

modelguard_require_command docker
modelguard_require_command git
modelguard_require_command sha256sum
modelguard_detect_compose

SOURCE_REVISION="$(modelguard_source_revision)"
export SOURCE_REVISION
UV_LOCK_SHA256="$(sha256sum uv.lock | awk '{print $1}')"
export UV_LOCK_SHA256

echo "Building source revision: ${SOURCE_REVISION}"
echo "Building uv.lock identity: ${UV_LOCK_SHA256}"
modelguard_compose build "$@"

evidence_dir="artifacts/phase-07-evidence/build"
mkdir -p "$evidence_dir"
chmod 0700 "$evidence_dir"
docker image inspect \
  modelguard-api:local \
  modelguard-dashboard:local \
  modelguard-monitor:local >"$evidence_dir/images.json"
echo "Image metadata evidence: ${evidence_dir}/images.json"

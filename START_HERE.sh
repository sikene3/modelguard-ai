#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$repo_root"

./scripts/verify_environment.sh
make setup
uv run --frozen --no-sync python -m scripts.human_aws_login dependency
make test

cat <<'EOF'

ModelGuard AI is locally implemented and validated through the Phase 10 code-only readiness segment.

Recommended next action:
1. Review reports/phase-10.md and checklists/PHASE_10.md.
2. Confirm the current clean Phase 10 commit and every recorded local gate.
3. Resolve the remaining external prerequisites in the documented order with explicit approval at
   each mutation boundary.

Do not run AWS login, Terraform apply/destroy, GitHub mutation, image/model publication, or Phase 11
from this bootstrap workflow. START_HERE is local and network-free after the locked dependency sync.
EOF

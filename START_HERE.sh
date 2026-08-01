#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$repo_root"

./scripts/verify_environment.sh
make setup
make test

cat <<'EOF'

ModelGuard AI is implemented through the audited Phase 02 training workflow.

Recommended next action:
1. On a clean clone, run: make train
2. Run: make inspect-model && make verify
3. Review reports/phase-02.md before beginning Phase 03.

API serving and later product phases are not implemented yet.
EOF

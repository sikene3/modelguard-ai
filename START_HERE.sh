#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$repo_root"

./scripts/verify_environment.sh
make setup
make test

cat <<'EOF'

ModelGuard AI is implemented through Phase 06 read-only operations dashboard.

Recommended next action:
1. On a clean clone, run: make train
2. In one terminal run: make api
3. Send predictions, stop cleanly, and finalize explicit healthy/drifted monitor windows
4. In another terminal run: make dashboard
5. Run: make load-test && make verify
6. Review reports/phase-06.md before beginning Phase 07.

Containers and later AWS/delivery phases are not implemented yet.
EOF

#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$repo_root"

./scripts/verify_environment.sh
make setup
make test

cat <<'EOF'

ModelGuard AI is implemented through Phase 04 versioned prediction-event logging.

Recommended next action:
1. On a clean clone, run: make train
2. In one terminal run: make api
3. Send multiple predictions, stop cleanly, and parse artifacts/predictions/*.jsonl
4. Run: make load-test && make verify
5. Review reports/phase-04.md before beginning Phase 05.

Drift monitoring and later product phases are not implemented yet.
EOF

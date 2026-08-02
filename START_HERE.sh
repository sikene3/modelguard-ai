#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$repo_root"

./scripts/verify_environment.sh
make setup
make test

cat <<'EOF'

ModelGuard AI is implemented through the typed Phase 03 FastAPI inference service.

Recommended next action:
1. On a clean clone, run: make train
2. In one terminal run: make api
3. Check readiness/prediction, run: make load-test && make verify
4. Review reports/phase-03.md before beginning Phase 04.

Prediction-event persistence and later product phases are not implemented yet.
EOF

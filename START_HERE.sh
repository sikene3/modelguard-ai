#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$repo_root"

./scripts/verify_environment.sh
make setup
make test

cat <<'EOF'

ModelGuard AI is implemented and validated through Phase 07.

Recommended next action:
1. Review every Phase 07 path, reports/phase-07.md, and checklists/PHASE_07.md.
2. Confirm the recorded image, Compose, smoke, demo, E2E, Trivy, and quality gates.
3. Stage only the approved Phase 07 paths and create a manual commit.
4. Confirm the worktree is clean before considering Phase 08.

Do not begin Phase 08 before that independent review and manual commit.
Terraform, AWS infrastructure, workflows, and later delivery phases are not implemented yet.
EOF

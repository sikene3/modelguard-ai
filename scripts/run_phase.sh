#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 1 || $# -gt 2 ]]; then
  echo "Usage: $0 <phase: 00-13> [xhigh|max|ultra]"
  exit 2
fi

phase="$(printf '%02d' "$((10#$1))")"
effort="${2:-xhigh}"
repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"

case "$phase" in
  00) prompt="prompts/00_ULTRA_ARCHITECTURE_REVIEW.md" ;;
  01) prompt="prompts/01_REPO_BOOTSTRAP.md" ;;
  02) prompt="prompts/02_DATA_AND_TRAINING.md" ;;
  03) prompt="prompts/03_API_SERVICE.md" ;;
  04) prompt="prompts/04_PREDICTION_LOGGING.md" ;;
  05) prompt="prompts/05_DRIFT_MONITOR.md" ;;
  06) prompt="prompts/06_DASHBOARD.md" ;;
  07) prompt="prompts/07_DOCKER_LOCAL.md" ;;
  08) prompt="prompts/08_TERRAFORM_AWS.md" ;;
  09) prompt="prompts/09_CICD_SECURITY.md" ;;
  10) prompt="prompts/10_AWS_DEPLOYMENT.md" ;;
  11) prompt="prompts/11_FAILURE_DEMO.md" ;;
  12) prompt="prompts/12_ULTRA_FINAL_AUDIT.md" ;;
  13) prompt="prompts/13_PORTFOLIO_ASSETS.md" ;;
  *) echo "Unknown phase: $phase"; exit 2 ;;
esac

if [[ ! -f "$prompt" ]]; then
  echo "Prompt not found: $prompt"
  exit 1
fi

if [[ "$effort" == "ultra" ]]; then
  cat <<EOF
Ultra should be selected interactively so you can inspect agent/subagent activity.
Run:
  codex
Then use /model -> GPT-5.6 Sol -> Ultra and send:
  Read AGENTS.md and $prompt. Execute only this phase.
EOF
  exit 0
fi

case "$effort" in
  xhigh|max) ;;
  *) echo "Unsupported effort: $effort"; exit 2 ;;
esac

mkdir -p logs
stamp="$(date -u +%Y%m%dT%H%M%SZ)"
log="logs/phase-${phase}-${effort}-${stamp}.log"

echo "Running Phase $phase with GPT-5.6 Sol / $effort"
echo "Prompt: $prompt"
echo "Log: $log"

codex exec \
  --model gpt-5.6-sol \
  --sandbox workspace-write \
  -c "model_reasoning_effort=\"$effort\"" \
  - < "$prompt" | tee "$log"

echo
echo "Review changes before committing:"
git status --short || true
git diff --stat || true

echo
echo "Run the phase validation commands and make verify before commit."

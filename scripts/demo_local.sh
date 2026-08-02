#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"
# shellcheck source=scripts/local_compose_lib.sh
source scripts/local_compose_lib.sh

modelguard_require_command docker
modelguard_require_command curl
modelguard_require_command uv
modelguard_detect_compose
modelguard_require_bundle

run_stamp="$(modelguard_utc_run_stamp)"
export DEMO_RUN_ID="${DEMO_RUN_ID:-demo-${run_stamp}-$$}"
modelguard_validate_name "$DEMO_RUN_ID" "DEMO_RUN_ID"

healthy_rows="${DEMO_HEALTHY_ROWS:-1000}"
drifted_rows="${DEMO_DRIFTED_ROWS:-1000}"
for row_count in "$healthy_rows" "$drifted_rows"; do
  if [[ ! "$row_count" =~ ^[0-9]+$ || "$row_count" -lt 500 ]]; then
    echo "Demo row counts must be integers of at least 500." >&2
    exit 2
  fi
done

evidence_root="artifacts/phase-07-evidence/${DEMO_RUN_ID}"
mkdir -p "$evidence_root/healthy" "$evidence_root/drifted"
chmod 0700 "$evidence_root" "$evidence_root/healthy" "$evidence_root/drifted"
api_origin="http://127.0.0.1:${MODELGUARD_API_PORT:-8000}"
dashboard_origin="http://127.0.0.1:${MODELGUARD_DASHBOARD_PORT:-8501}"

run_stage() {
  local event_set="$1"
  local scenario="$2"
  local row_count="$3"
  local expected_drift="$4"
  local stage_dir="$5"
  local window_end

  export DEMO_EVENT_SET="$event_set"
  modelguard_validate_name "$DEMO_EVENT_SET" "DEMO_EVENT_SET"
  echo "Generating ${scenario} traffic (${row_count} predictions)."
  modelguard_compose up --detach --force-recreate api dashboard
  modelguard_wait_api
  modelguard_wait_dashboard

  UV_CACHE_DIR="$repo_root/.cache/uv" uv run --frozen --no-sync python \
    scripts/generate_local_traffic.py \
    --scenario "$scenario" \
    --row-count "$row_count" \
    --url "$api_origin" \
    --evidence "$stage_dir/traffic.json" >/dev/null
  curl --fail --silent --show-error "$api_origin/metrics" >"$stage_dir/api-metrics.prom"

  modelguard_close_event_file
  window_end="$(modelguard_finalized_timestamp)"
  modelguard_run_monitor "$window_end" "$stage_dir/monitor.json"
  modelguard_copy_latest_report "$stage_dir/latest-report.json"

  UV_CACHE_DIR="$repo_root/.cache/uv" uv run --frozen --no-sync python \
    scripts/validate_local_evidence.py scenario \
    --traffic "$stage_dir/traffic.json" \
    --monitor "$stage_dir/monitor.json" \
    --report "$stage_dir/latest-report.json" \
    --expected-scenario "$scenario" \
    --expected-accepted "$row_count" \
    --expected-quality valid \
    --expected-drift "$expected_drift" \
    --summary "$stage_dir/summary.json" >/dev/null
}

run_stage healthy baseline "$healthy_rows" healthy "$evidence_root/healthy"
echo "Healthy state proved; switching to an isolated drifted event stream."
run_stage drifted drifted "$drifted_rows" degraded "$evidence_root/drifted"

curl --fail --silent --show-error "$dashboard_origin/_stcore/health" \
  >"$evidence_root/dashboard-health.txt"
curl --fail --silent --show-error "$dashboard_origin/" >"$evidence_root/dashboard.html"

UV_CACHE_DIR="$repo_root/.cache/uv" uv run --frozen --no-sync python \
  scripts/validate_local_evidence.py \
  demo \
  --healthy-summary "$evidence_root/healthy/summary.json" \
  --drifted-summary "$evidence_root/drifted/summary.json" \
  --dashboard-health "$evidence_root/dashboard-health.txt" \
  --summary "$evidence_root/demo-summary.json"

echo "Healthy -> Drifted demo passed. Evidence: ${evidence_root}/demo-summary.json"

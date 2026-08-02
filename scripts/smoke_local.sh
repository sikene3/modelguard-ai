#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"
# shellcheck source=scripts/local_compose_lib.sh
source scripts/local_compose_lib.sh

modelguard_require_command docker
modelguard_require_command curl
modelguard_require_command git
modelguard_require_command uv
modelguard_detect_compose
modelguard_require_bundle

run_stamp="$(modelguard_utc_run_stamp)"
export DEMO_RUN_ID="${DEMO_RUN_ID:-smoke-${run_stamp}-$$}"
export DEMO_EVENT_SET="baseline"
modelguard_validate_name "$DEMO_RUN_ID" "DEMO_RUN_ID"
modelguard_validate_name "$DEMO_EVENT_SET" "DEMO_EVENT_SET"

traffic_rows="${SMOKE_TRAFFIC_ROWS:-600}"
source_revision="$(modelguard_source_revision)"
if [[ ! "$traffic_rows" =~ ^[0-9]+$ || "$traffic_rows" -lt 500 ]]; then
  echo "SMOKE_TRAFFIC_ROWS must be an integer of at least 500." >&2
  exit 2
fi

evidence_dir="artifacts/phase-07-evidence/${DEMO_RUN_ID}"
mkdir -p "$evidence_dir"
chmod 0700 "$evidence_dir"

api_origin="http://127.0.0.1:${MODELGUARD_API_PORT:-8000}"
dashboard_origin="http://127.0.0.1:${MODELGUARD_DASHBOARD_PORT:-8501}"

echo "Starting isolated smoke namespace: ${DEMO_RUN_ID}"
modelguard_compose up --detach --force-recreate api dashboard
modelguard_wait_api
modelguard_wait_dashboard

curl --fail --silent --show-error "$api_origin/health/live" >"$evidence_dir/api-live.json"
curl --fail --silent --show-error "$api_origin/health/ready" >"$evidence_dir/api-ready.json"
curl --fail --silent --show-error "$api_origin/version" >"$evidence_dir/api-version.json"
curl --fail --silent --show-error \
  --header 'Content-Type: application/json' \
  --data @examples/prediction-request.json \
  "$api_origin/v1/predict" >"$evidence_dir/prediction.json"

UV_CACHE_DIR="$repo_root/.cache/uv" uv run --frozen --no-sync python scripts/generate_local_traffic.py \
  --scenario baseline \
  --row-count "$traffic_rows" \
  --url "$api_origin" \
  --evidence "$evidence_dir/traffic.json" >/dev/null

curl --fail --silent --show-error "$api_origin/metrics" >"$evidence_dir/api-metrics.prom"
modelguard_close_event_file
window_end="$(modelguard_finalized_timestamp)"
modelguard_run_monitor "$window_end" "$evidence_dir/monitor.json"
modelguard_copy_latest_report "$evidence_dir/latest-report.json"
modelguard_copy_latest_html "$evidence_dir/monitor-report.html"

curl --fail --silent --show-error "$dashboard_origin/_stcore/health" \
  >"$evidence_dir/dashboard-health.txt"
curl --fail --silent --show-error "$dashboard_origin/" >"$evidence_dir/dashboard.html"

docker image inspect \
  modelguard-api:local \
  modelguard-dashboard:local \
  modelguard-monitor:local >"$evidence_dir/images.json"

check_image_contents() {
  local image_name="$1"
  docker run --rm --network none --entrypoint python "$image_name" -c \
    'import os; from pathlib import Path; forbidden=(Path("/app/artifacts"),Path("/app/.env")); model=Path("/model"); clean=os.geteuid()==10001 and os.getegid()==10001 and not any(p.exists() for p in forbidden) and not any(model.iterdir()); raise SystemExit(0 if clean else 1)'
  printf 'clean'
}

api_contents="$(check_image_contents modelguard-api:local)"
dashboard_contents="$(check_image_contents modelguard-dashboard:local)"
monitor_contents="$(check_image_contents modelguard-monitor:local)"
printf '{"api":"%s","dashboard":"%s","monitor":"%s"}\n' \
  "$api_contents" "$dashboard_contents" "$monitor_contents" \
  >"$evidence_dir/image-files.json"

UV_CACHE_DIR="$repo_root/.cache/uv" uv run --frozen --no-sync python \
  scripts/validate_local_evidence.py \
  smoke \
  --evidence-dir "$evidence_dir" \
  --traffic-events "$traffic_rows" \
  --expected-source-revision "$source_revision" \
  --summary "$evidence_dir/smoke-summary.json"

echo "Local smoke passed. Evidence: ${evidence_dir}/smoke-summary.json"

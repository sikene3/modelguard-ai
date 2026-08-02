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
export DEMO_RUN_ID="${DEMO_RUN_ID:-e2e-${run_stamp}-$$}"
modelguard_validate_name "$DEMO_RUN_ID" "DEMO_RUN_ID"
export DEMO_EVENT_SET="tiny"

corrupt_port="${E2E_CORRUPT_PORT:-18081}"
sink_port="${E2E_SINK_PORT:-18082}"
for port in "$corrupt_port" "$sink_port"; do
  if [[ ! "$port" =~ ^[0-9]+$ || "$port" -lt 1024 || "$port" -gt 65535 ]]; then
    echo "E2E ports must be integers in [1024,65535]." >&2
    exit 2
  fi
done
if [[ "$corrupt_port" == "$sink_port" ]]; then
  echo "E2E_CORRUPT_PORT and E2E_SINK_PORT must differ." >&2
  exit 2
fi

evidence_root="artifacts/phase-07-evidence/${DEMO_RUN_ID}"
mkdir -p \
  "$evidence_root/insufficient" \
  "$evidence_root/corrupt-bundle" \
  "$evidence_root/sink-outage"
chmod 0700 \
  "$evidence_root" \
  "$evidence_root/insufficient" \
  "$evidence_root/corrupt-bundle" \
  "$evidence_root/sink-outage"

declare -a ephemeral_containers=()
cleanup_ephemeral_containers() {
  local container_name
  set +e
  for container_name in "${ephemeral_containers[@]}"; do
    docker container stop --time 20 "$container_name" >/dev/null 2>&1
    docker container rm "$container_name" >/dev/null 2>&1
  done
}
trap cleanup_ephemeral_containers EXIT

remove_ephemeral_container() {
  local container_name="$1"
  docker container stop --time 20 "$container_name" >/dev/null
  docker container rm "$container_name" >/dev/null
}

echo "Running insufficient-data container scenario."
modelguard_compose up --detach --force-recreate api dashboard
modelguard_wait_api
modelguard_wait_dashboard
api_origin="http://127.0.0.1:${MODELGUARD_API_PORT:-8000}"
UV_CACHE_DIR="$repo_root/.cache/uv" uv run --frozen --no-sync python \
  scripts/generate_local_traffic.py \
  --scenario tiny \
  --row-count 25 \
  --url "$api_origin" \
  --evidence "$evidence_root/insufficient/traffic.json" >/dev/null
modelguard_close_event_file
window_end="$(modelguard_finalized_timestamp)"
modelguard_run_monitor "$window_end" "$evidence_root/insufficient/monitor.json"
modelguard_copy_latest_report "$evidence_root/insufficient/latest-report.json"
UV_CACHE_DIR="$repo_root/.cache/uv" uv run --frozen --no-sync python \
  scripts/validate_local_evidence.py scenario \
  --traffic "$evidence_root/insufficient/traffic.json" \
  --monitor "$evidence_root/insufficient/monitor.json" \
  --report "$evidence_root/insufficient/latest-report.json" \
  --expected-scenario tiny \
  --expected-accepted 25 \
  --expected-quality insufficient_data \
  --expected-drift unknown \
  --summary "$evidence_root/insufficient/summary.json" >/dev/null

echo "Running corrupt-bundle readiness scenario."
modelguard_compose run --rm --no-deps -T \
  --env "DEMO_RUN_ID=${DEMO_RUN_ID}" \
  --entrypoint python monitor -c \
  'import os,shutil; from pathlib import Path; destination=Path("/runtime")/os.environ["DEMO_RUN_ID"]/"corrupt-bundle"; destination.mkdir(parents=True); [shutil.copy2(path,destination/path.name) for path in Path("/model").iterdir()]; (destination/"checksums.sha256").write_text("invalid\n",encoding="utf-8")'

corrupt_container="modelguard-${DEMO_RUN_ID}-corrupt"
ephemeral_containers+=("$corrupt_container")
modelguard_compose run --detach --no-deps \
  --name "$corrupt_container" \
  --publish "127.0.0.1:${corrupt_port}:8000" \
  --env "MODEL_BUNDLE_PATH=/runtime/${DEMO_RUN_ID}/corrupt-bundle" \
  api >"$evidence_root/corrupt-bundle/container-id.txt"
corrupt_origin="http://127.0.0.1:${corrupt_port}"
modelguard_wait_http "$corrupt_origin/health/live" '{"status":"live"}'
printf '%s\n' "$(modelguard_http_status GET "$corrupt_origin/health/live" "$evidence_root/corrupt-bundle/live.json")" \
  >"$evidence_root/corrupt-bundle/live.status"
printf '%s\n' "$(modelguard_http_status GET "$corrupt_origin/health/ready" "$evidence_root/corrupt-bundle/ready.json")" \
  >"$evidence_root/corrupt-bundle/ready.status"
printf '%s\n' "$(modelguard_http_status GET "$corrupt_origin/version" "$evidence_root/corrupt-bundle/version.json")" \
  >"$evidence_root/corrupt-bundle/version.status"
printf '%s\n' "$(modelguard_http_status POST "$corrupt_origin/v1/predict" "$evidence_root/corrupt-bundle/predict.json" --header 'Content-Type: application/json' --data @examples/prediction-request.json)" \
  >"$evidence_root/corrupt-bundle/predict.status"
docker container logs "$corrupt_container" >"$evidence_root/corrupt-bundle/container.log" 2>&1
UV_CACHE_DIR="$repo_root/.cache/uv" uv run --frozen --no-sync python \
  scripts/validate_local_evidence.py corrupt-bundle \
  --evidence-dir "$evidence_root/corrupt-bundle" \
  --summary "$evidence_root/corrupt-bundle/summary.json" >/dev/null
remove_ephemeral_container "$corrupt_container"

echo "Running fail-open local sink outage scenario."
sink_container="modelguard-${DEMO_RUN_ID}-sink"
ephemeral_containers+=("$sink_container")
modelguard_compose run --detach --no-deps \
  --name "$sink_container" \
  --publish "127.0.0.1:${sink_port}:8000" \
  --env LOCAL_EVENT_DIR=/sys/modelguard-events \
  api >"$evidence_root/sink-outage/container-id.txt"
sink_origin="http://127.0.0.1:${sink_port}"
modelguard_wait_http "$sink_origin/health/ready" '{"status":"ready"}'
printf '%s\n' "$(modelguard_http_status GET "$sink_origin/health/ready" "$evidence_root/sink-outage/ready.json")" \
  >"$evidence_root/sink-outage/ready.status"
printf '%s\n' "$(modelguard_http_status POST "$sink_origin/v1/predict" "$evidence_root/sink-outage/predict.json" --header 'Content-Type: application/json' --data @examples/prediction-request.json)" \
  >"$evidence_root/sink-outage/predict.status"
modelguard_wait_metric \
  "$sink_origin/metrics" \
  'modelguard_event_sink_operations_total{outcome="local_failed"} 1.0' \
  "$evidence_root/sink-outage/metrics.prom"
docker container logs "$sink_container" >"$evidence_root/sink-outage/container.log" 2>&1
UV_CACHE_DIR="$repo_root/.cache/uv" uv run --frozen --no-sync python \
  scripts/validate_local_evidence.py sink-outage \
  --evidence-dir "$evidence_root/sink-outage" \
  --summary "$evidence_root/sink-outage/summary.json" >/dev/null
remove_ephemeral_container "$sink_container"

UV_CACHE_DIR="$repo_root/.cache/uv" uv run --frozen --no-sync python \
  scripts/validate_local_evidence.py \
  e2e \
  --insufficient-summary "$evidence_root/insufficient/summary.json" \
  --corrupt-summary "$evidence_root/corrupt-bundle/summary.json" \
  --sink-summary "$evidence_root/sink-outage/summary.json" \
  --summary "$evidence_root/e2e-summary.json"

echo "Failure-mode E2E scenarios passed. Evidence: ${evidence_root}/e2e-summary.json"

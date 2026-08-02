#!/usr/bin/env bash
set -euo pipefail

declare -a MODELGUARD_COMPOSE_COMMAND=()

modelguard_detect_compose() {
  local compose_major
  local compose_version
  if compose_version="$(docker compose version --short 2>/dev/null)"; then
    compose_major="${compose_version#v}"
    compose_major="${compose_major%%.*}"
  else
    compose_major=""
  fi
  if [[ "$compose_major" =~ ^[0-9]+$ && "$compose_major" -ge 2 ]]; then
    MODELGUARD_COMPOSE_COMMAND=(docker compose)
  else
    compose_major=""
    if command -v docker-compose >/dev/null 2>&1 \
      && compose_version="$(docker-compose version --short 2>/dev/null)"; then
      compose_major="${compose_version#v}"
      compose_major="${compose_major%%.*}"
    fi
    if [[ "$compose_major" =~ ^[0-9]+$ && "$compose_major" -ge 2 ]]; then
      MODELGUARD_COMPOSE_COMMAND=(docker-compose)
    else
      echo "Docker Compose 2 or newer (plugin or docker-compose executable) is required." >&2
      return 2
    fi
  fi
}

modelguard_compose() {
  if [[ "${#MODELGUARD_COMPOSE_COMMAND[@]}" -eq 0 ]]; then
    modelguard_detect_compose
  fi
  "${MODELGUARD_COMPOSE_COMMAND[@]}" "$@"
}

modelguard_require_command() {
  local command_name="$1"
  if ! command -v "$command_name" >/dev/null 2>&1; then
    printf 'Required command is unavailable: %s\n' "$command_name" >&2
    return 2
  fi
}

modelguard_require_bundle() {
  local bundle_root="artifacts/model-bundles/1.0.0"
  local filename
  local required_files=(
    model.joblib
    manifest.json
    input_schema.json
    metrics.json
    threshold.json
    baseline_profile.json
    checksums.sha256
  )
  for filename in "${required_files[@]}"; do
    if [[ ! -f "$bundle_root/$filename" ]]; then
      echo "Verified model bundle is missing; run 'make train' first." >&2
      return 2
    fi
  done
}

modelguard_validate_name() {
  local value="$1"
  local field_name="$2"
  if [[ ! "$value" =~ ^[a-z0-9][a-z0-9-]{0,63}$ ]]; then
    printf '%s must match ^[a-z0-9][a-z0-9-]{0,63}$\n' "$field_name" >&2
    return 2
  fi
}

modelguard_utc_run_stamp() {
  date -u +%Y%m%dt%H%M%Sz
}

modelguard_source_revision() {
  local revision
  revision="$(git rev-parse --verify HEAD)"
  if [[ -n "$(git status --porcelain --untracked-files=normal)" ]]; then
    revision="${revision}-dirty"
  fi
  printf '%s\n' "$revision"
}

modelguard_wait_http() {
  local url="$1"
  local expected_body="${2:-}"
  local attempts="${3:-60}"
  local body
  local attempt
  for ((attempt = 1; attempt <= attempts; attempt += 1)); do
    if body="$(curl --fail --silent --show-error --max-time 2 "$url" 2>/dev/null)"; then
      if [[ -z "$expected_body" || "$body" == "$expected_body" ]]; then
        return 0
      fi
    fi
    sleep 1
  done
  printf 'Timed out waiting for %s\n' "$url" >&2
  return 1
}

modelguard_wait_api() {
  local port="${MODELGUARD_API_PORT:-8000}"
  modelguard_wait_http "http://127.0.0.1:${port}/health/ready" '{"status":"ready"}'
}

modelguard_wait_dashboard() {
  local port="${MODELGUARD_DASHBOARD_PORT:-8501}"
  modelguard_wait_http "http://127.0.0.1:${port}/_stcore/health" "ok"
}

modelguard_close_event_file() {
  modelguard_compose restart api >/dev/null
  modelguard_wait_api
}

modelguard_finalized_timestamp() {
  sleep 1
  date -u +%Y-%m-%dT%H:%M:%SZ
}

modelguard_run_monitor() {
  local window_end="$1"
  local output_path="$2"
  modelguard_compose run --rm --no-deps -T monitor run \
    --config /app/configs/phase-07-monitoring.json \
    --bundle /model \
    --event-dir "/runtime/${DEMO_RUN_ID}/events/${DEMO_EVENT_SET}" \
    --report-dir "/runtime/${DEMO_RUN_ID}/reports" \
    --window-end "$window_end" \
    --as-of "$window_end" | tail -n 1 >"$output_path"
}

modelguard_copy_latest_report() {
  local output_path="$1"
  modelguard_compose exec -T dashboard python \
    -c 'import os,sys; from pathlib import Path; sys.stdout.buffer.write((Path(os.environ["LOCAL_REPORT_DIR"])/"latest.json").read_bytes())' \
    >"$output_path"
}

modelguard_copy_latest_html() {
  local output_path="$1"
  modelguard_compose exec -T dashboard python \
    -c 'import os,sys; from pathlib import Path; from modelguard.monitoring.report import MonitoringReport; root=Path(os.environ["LOCAL_REPORT_DIR"]); report=MonitoringReport.model_validate_json((root/"latest.json").read_bytes()); history=root/"history"/report.window.end.strftime("%Y%m%dT%H%M%SZ")/f"{report.report_id}.html"; sys.stdout.buffer.write(history.read_bytes())' \
    >"$output_path"
}

modelguard_http_status() {
  local method="$1"
  local url="$2"
  local output_path="$3"
  shift 3
  curl --silent --show-error --max-time 10 --request "$method" \
    --output "$output_path" --write-out '%{http_code}' "$@" "$url"
}

modelguard_wait_metric() {
  local url="$1"
  local metric="$2"
  local output_path="$3"
  local attempts="${4:-30}"
  local attempt
  for ((attempt = 1; attempt <= attempts; attempt += 1)); do
    if curl --fail --silent --show-error --max-time 2 "$url" >"$output_path" 2>/dev/null \
      && grep -Fq "$metric" "$output_path"; then
      return 0
    fi
    sleep 1
  done
  printf 'Timed out waiting for metric %s at %s\n' "$metric" "$url" >&2
  return 1
}

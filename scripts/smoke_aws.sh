#!/usr/bin/env bash
set +x
set -euo pipefail

required_names=(
  SMOKE_BASE_URL
  API_ACCESS_MODE
  EXPECTED_MODEL_VERSION
  EXPECTED_MODEL_MANIFEST_SHA256
  EVIDENCE_DIR
)
for required_name in "${required_names[@]}"; do
  if [[ -z "${!required_name:-}" ]]; then
    echo "AWS smoke test requires ${required_name}."
    exit 2
  fi
done
if [[ "$API_ACCESS_MODE" != "https_token" && "$API_ACCESS_MODE" != "http_cidr_only" ]]; then
  echo "AWS smoke test received an invalid access mode."
  exit 2
fi
unset bearer_token
declare bearer_token=""
if [[ "$API_ACCESS_MODE" == "https_token" ]]; then
  if [[ -z "${PREDICTION_BEARER_TOKEN:-}" ]]; then
    echo "AWS smoke test requires the protected bearer-token secret in HTTPS mode."
    exit 2
  fi
  bearer_token="${PREDICTION_BEARER_TOKEN}"
  unset PREDICTION_BEARER_TOKEN
  if ((${#bearer_token} < 32 || ${#bearer_token} > 512)) ||
    [[ ! "$bearer_token" =~ ^[A-Za-z0-9._~-]+$ ]]; then
    bearer_token=""
    unset bearer_token
    echo "AWS smoke test received an invalid protected bearer-token format." >&2
    exit 2
  fi
else
  unset PREDICTION_BEARER_TOKEN
fi

mkdir -p "$EVIDENCE_DIR"
chmod 0700 "$EVIDENCE_DIR"
base_url="${SMOKE_BASE_URL%/}"

curl --disable --fail --silent --show-error --connect-timeout 10 --max-time 30 --retry 0 \
  "$base_url/health/live" >"$EVIDENCE_DIR/live.json"
curl --disable --fail --silent --show-error --connect-timeout 10 --max-time 30 --retry 0 \
  "$base_url/health/ready" >"$EVIDENCE_DIR/ready.json"
curl --disable --fail --silent --show-error --connect-timeout 10 --max-time 30 --retry 0 \
  "$base_url/version" >"$EVIDENCE_DIR/version.json"

if [[ "$API_ACCESS_MODE" == "https_token" ]]; then
  if ! {
    builtin printf '%s\n' \
      "fail" \
      "silent" \
      "show-error" \
      "connect-timeout = 10" \
      "max-time = 30" \
      "retry = 0" \
      'header = "Content-Type: application/json"' \
      'data = "@examples/prediction-request.json"'
    builtin printf 'header = "Authorization: Bearer %s"\n' "$bearer_token"
  } | env -u PREDICTION_BEARER_TOKEN curl --disable --config - \
    "$base_url/v1/predict" >"$EVIDENCE_DIR/prediction.json"; then
    bearer_token=""
    unset bearer_token
    echo "AWS prediction smoke request failed." >&2
    exit 1
  fi
  bearer_token=""
  unset bearer_token
else
  curl --disable --fail --silent --show-error --connect-timeout 10 --max-time 30 --retry 0 \
    --header "Content-Type: application/json" \
    --data @examples/prediction-request.json \
    "$base_url/v1/predict" >"$EVIDENCE_DIR/prediction.json"
fi

uv run --frozen --no-sync python - \
  "$EVIDENCE_DIR" "$EXPECTED_MODEL_VERSION" "$EXPECTED_MODEL_MANIFEST_SHA256" <<'PY'
import json
import math
import pathlib
import sys
from uuid import UUID

evidence = pathlib.Path(sys.argv[1])
expected_version = sys.argv[2]
expected_manifest = sys.argv[3]
live = json.loads((evidence / "live.json").read_text(encoding="utf-8"))
ready = json.loads((evidence / "ready.json").read_text(encoding="utf-8"))
version = json.loads((evidence / "version.json").read_text(encoding="utf-8"))
prediction = json.loads((evidence / "prediction.json").read_text(encoding="utf-8"))
risk_score = prediction.get("risk_score")
latency_ms = prediction.get("latency_ms")
try:
    UUID(prediction.get("request_id", ""))
    request_id_valid = True
except (TypeError, ValueError, AttributeError):
    request_id_valid = False
valid = (
    live.get("status") == "live"
    and ready.get("status") == "ready"
    and version.get("model_ready") is True
    and version.get("model_version") == expected_version
    and version.get("manifest_sha256") == expected_manifest
    and isinstance(version.get("service_version"), str)
    and bool(version["service_version"])
    and prediction.get("model_version") == expected_version
    and prediction.get("decision") in {"low_risk", "high_risk"}
    and isinstance(risk_score, (int, float))
    and not isinstance(risk_score, bool)
    and math.isfinite(risk_score)
    and 0 <= risk_score <= 1
    and isinstance(latency_ms, (int, float))
    and not isinstance(latency_ms, bool)
    and math.isfinite(latency_ms)
    and latency_ms >= 0
    and request_id_valid
)
if not valid:
    raise SystemExit("smoke response contract failed")
summary = {
    "schema_version": "modelguard.aws-smoke-evidence.v1",
    "status": "passed",
    "checks": ["live", "ready", "version", "prediction"],
    "model_version": expected_version,
    "model_manifest_sha256": expected_manifest,
}
(evidence / "summary.json").write_text(
    json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
)
PY

echo "AWS live, ready, version, and prediction smoke checks passed."

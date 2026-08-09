#!/usr/bin/env bash
set -euo pipefail

required_names=(API_IMAGE_REF DASHBOARD_IMAGE_REF MONITOR_IMAGE_REF)
verification_mode="${RUNTIME_VERIFICATION_MODE:-immutable_digest}"
source_commit="${SOURCE_COMMIT:-}"
output_path="${RUNTIME_VERIFICATION_OUTPUT:-}"
temporary_output=""

cleanup_temporary_output() {
  if [[ -n "$temporary_output" && -f "$temporary_output" ]]; then
    rm -f -- "$temporary_output"
  fi
}
trap cleanup_temporary_output EXIT

# A failed rerun must not leave an older passing record available to activation. Refuse links and
# non-regular destinations, then remove only the exact caller-selected regular output before any
# validation or Docker probe begins.
if [[ -n "$output_path" ]]; then
  output_parent="$(dirname -- "$output_path")"
  mkdir -p -- "$output_parent"
  if [[ -L "$output_path" || ( -e "$output_path" && ! -f "$output_path" ) ]]; then
    echo "Runtime verification output must be a regular file path." >&2
    exit 2
  fi
  rm -f -- "$output_path"
fi

if [[ ! "$source_commit" =~ ^[0-9a-f]{40}$ ]]; then
  echo "Runtime contract verification requires an exact source commit."
  exit 2
fi
if [[ "$verification_mode" != "immutable_digest" && "$verification_mode" != "local_image_id" ]]; then
  echo "Runtime contract verification mode is invalid."
  exit 2
fi
for required_name in "${required_names[@]}"; do
  if [[ -z "${!required_name:-}" ]]; then
    echo "Runtime contract verification requires all three digest references."
    exit 2
  fi
  if [[ "$verification_mode" = "immutable_digest" ]]; then
    if [[ ! "${!required_name}" =~ @sha256:[0-9a-f]{64}$ ]]; then
      echo "Runtime contract verification refuses a mutable image reference."
      exit 2
    fi
  elif [[ ! "${!required_name}" =~ ^sha256:[0-9a-f]{64}$ ]]; then
    echo "Local runtime verification accepts only an exact Docker image ID."
    exit 2
  fi
done

image_refs=("$API_IMAGE_REF" "$DASHBOARD_IMAGE_REF" "$MONITOR_IMAGE_REF")
components=(api dashboard monitor)
expected_source_revision="$source_commit"
uv_lock_sha256="$(sha256sum uv.lock | awk '{print $1}')"
if [[ ! "$uv_lock_sha256" =~ ^[0-9a-f]{64}$ ]]; then
  echo "Runtime contract verification could not bind the dependency lock." >&2
  exit 2
fi
if [[ "$verification_mode" = "local_image_id" ]]; then
  expected_source_revision="${source_commit}-dirty"
fi
for index in "${!image_refs[@]}"; do
  image_ref="${image_refs[$index]}"
  test "$(docker image inspect --format '{{.Config.User}}' "$image_ref")" = "10001:10001"
  test "$(docker image inspect --format '{{ index .Config.Labels "org.opencontainers.image.revision" }}' "$image_ref")" = "$expected_source_revision"
  test "$(docker image inspect --format '{{ index .Config.Labels "io.modelguard.component" }}' "$image_ref")" = "${components[$index]}"
  test "$(docker image inspect --format '{{ index .Config.Labels "io.modelguard.uv-lock.sha256" }}' "$image_ref")" = "$uv_lock_sha256"
done

test "$(docker image inspect --format '{{json .Config.Entrypoint}}' "$API_IMAGE_REF")" = "null"
test "$(docker image inspect --format '{{json .Config.Cmd}}' "$API_IMAGE_REF")" = '["python","-m","uvicorn","modelguard.api.main:app","--host","0.0.0.0","--port","8000","--workers","1","--limit-concurrency","64","--timeout-keep-alive","5","--timeout-graceful-shutdown","10","--no-access-log"]'
test "$(docker image inspect --format '{{json .Config.Entrypoint}}' "$DASHBOARD_IMAGE_REF")" = "null"
test "$(docker image inspect --format '{{json .Config.Cmd}}' "$DASHBOARD_IMAGE_REF")" = '["python","-m","streamlit","run","src/modelguard/dashboard/app.py","--server.address","0.0.0.0","--server.port","8501","--server.headless","true","--server.fileWatcherType","none","--browser.gatherUsageStats","false"]'
test "$(docker image inspect --format '{{json .Config.Entrypoint}}' "$MONITOR_IMAGE_REF")" = '["python","-m","modelguard.monitoring.cli"]'
test "$(docker image inspect --format '{{json .Config.Cmd}}' "$MONITOR_IMAGE_REF")" = '["--help"]'

if ! docker run --rm --network none --read-only --cap-drop ALL \
  --security-opt no-new-privileges \
  --tmpfs /tmp:rw,nosuid,nodev,noexec,size=32m,mode=1777 \
  --entrypoint /bin/true "$API_IMAGE_REF"; then
  echo "Runtime contract verification requires a Docker host that enforces no-new-privileges." >&2
  exit 3
fi

runtime_args=(
  --rm
  --network none
  --read-only
  --cap-drop ALL
  --security-opt no-new-privileges
  --tmpfs "/tmp:rw,nosuid,nodev,noexec,size=32m,mode=1777"
  --env HOME=/tmp
  --entrypoint python
)
docker run "${runtime_args[@]}" "$API_IMAGE_REF" -m modelguard.runtime_contracts api
docker run "${runtime_args[@]}" "$DASHBOARD_IMAGE_REF" -m modelguard.runtime_contracts dashboard
docker run "${runtime_args[@]}" "$MONITOR_IMAGE_REF" -m modelguard.runtime_contracts monitor
docker run --rm --network none --read-only --cap-drop ALL \
  --security-opt no-new-privileges "$MONITOR_IMAGE_REF" aws-run --help >/dev/null

evidence="$({
  printf '{"contracts":{"api":"hydration-fail-closed","dashboard":"typed-aws-health","monitor":"one-shot-aws-run"},'
  printf '"images":{"api":"%s","dashboard":"%s","monitor":"%s"},' \
    "$API_IMAGE_REF" "$DASHBOARD_IMAGE_REF" "$MONITOR_IMAGE_REF"
  printf '"mode":"%s","schema_version":"modelguard.runtime-contract-verification.v2",' \
    "$verification_mode"
  printf '"source_commit":"%s","source_revision":"%s","status":"passed",' \
    "$source_commit" "$expected_source_revision"
  printf '"uv_lock_sha256":"%s"}\n' "$uv_lock_sha256"
})"
if [[ -n "$output_path" ]]; then
  temporary_output="$(mktemp "$output_parent/.runtime-contract.XXXXXX")"
  chmod 0600 "$temporary_output"
  printf '%s\n' "$evidence" >"$temporary_output"
  sync -f "$temporary_output"
  mv -fT -- "$temporary_output" "$output_path"
  temporary_output=""
  chmod 0600 "$output_path"
  sync -f "$output_parent"
fi
printf '%s\n' "$evidence"

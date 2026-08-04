#!/usr/bin/env bash
set -euo pipefail

required_names=(API_IMAGE_REF DASHBOARD_IMAGE_REF MONITOR_IMAGE_REF)
for required_name in "${required_names[@]}"; do
  if [[ -z "${!required_name:-}" ]]; then
    echo "Runtime contract verification requires all three digest references."
    exit 2
  fi
  if [[ ! "${!required_name}" =~ @sha256:[0-9a-f]{64}$ ]]; then
    echo "Runtime contract verification refuses a mutable image reference."
    exit 2
  fi
done

docker run --rm --network none --entrypoint python "$API_IMAGE_REF" -c \
  'import os; import modelguard.api.schemas; raise SystemExit(0 if os.geteuid() == 10001 else 1)'
docker run --rm --network none --entrypoint python "$DASHBOARD_IMAGE_REF" -c \
  'import os; from pathlib import Path; import modelguard.dashboard.repository; required=Path("/app/configs/phase-05-monitoring.json"); raise SystemExit(0 if os.geteuid() == 10001 and required.is_file() else 1)'

# This deliberately fails for the current Phase 08 image. Activation stays closed until the
# scheduled container exposes and tests the one-shot AWS orchestration contract.
docker run --rm --network none "$MONITOR_IMAGE_REF" aws-run --help >/dev/null

printf '{"status":"passed","api":"nonroot-import","dashboard":"nonroot-aws-config","monitor":"aws-run"}\n'

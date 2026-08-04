#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"

cache_root="$repo_root/.cache/security-tools"
output_root="${SECURITY_SCAN_OUTPUT_DIR:-$repo_root/artifacts/security}"
python_runner=(uv run --frozen --no-sync python)

tool_path() {
  "${python_runner[@]}" -m scripts.security_tools path "$1"
}

check_tool() {
  "${python_runner[@]}" -m scripts.security_tools check --tool "$1" >/dev/null
}

new_raw_dir() {
  mkdir -p "$cache_root/tmp"
  chmod 0700 "$cache_root/tmp"
  mktemp -d "$cache_root/tmp/scan.XXXXXX"
}

sanitize_sarif() {
  local mode="$1"
  local input="$2"
  local output="$3"
  local scanner="$4"
  "${python_runner[@]}" -m scripts.sanitize_sarif "$mode" \
    --input "$input" --output "$output" --scanner "$scanner"
}

scan_actionlint() {
  check_tool actionlint
  check_tool shellcheck
  local actionlint_bin shellcheck_bin
  actionlint_bin="$(tool_path actionlint)"
  shellcheck_bin="$(tool_path shellcheck)"
  mapfile -d '' -t workflows < <(
    find .github/workflows -maxdepth 1 -type f \( -name '*.yml' -o -name '*.yaml' \) \
      -print0 | sort -z
  )
  if [[ "${#workflows[@]}" -eq 0 ]]; then
    echo "actionlint gate found no GitHub Actions workflows." >&2
    return 2
  fi
  "$actionlint_bin" -no-color -shellcheck "$shellcheck_bin" "${workflows[@]}"
}

scan_shellcheck() {
  check_tool shellcheck
  "${python_runner[@]}" -m scripts.security_policy >/dev/null
  ./scripts/check_shell.sh
}

scan_checkov() {
  check_tool checkov
  "${python_runner[@]}" -m scripts.security_policy >/dev/null
  local checkov_image raw_dir raw_sarif sanitized status
  checkov_image="$("${python_runner[@]}" -m scripts.security_tools image checkov)"
  raw_dir="$(new_raw_dir)"
  raw_sarif="$raw_dir/checkov/results_sarif.sarif"
  sanitized="$output_root/sarif/checkov.sarif"
  mkdir -p "$raw_dir/checkov" "$output_root/sarif"
  set +e
  docker run --rm \
    --network none \
    --read-only \
    --cap-drop ALL \
    --user "$(id -u):$(id -g)" \
    --tmpfs /tmp:rw,noexec,nosuid,size=64m \
    --env HOME=/tmp \
    --volume "$repo_root:/workspace:ro" \
    --volume "$raw_dir/checkov:/output:rw" \
    --workdir /workspace \
    "$checkov_image" \
    -d /workspace \
    --framework terraform dockerfile github_actions \
    --skip-download --quiet --compact \
    -o sarif --output-file-path /output
  status=$?
  set -e
  if [[ -f "$raw_sarif" ]]; then
    sanitize_sarif sarif "$raw_sarif" "$sanitized" checkov || status=2
  else
    echo "Checkov did not create its expected SARIF output." >&2
    status=2
  fi
  rm -rf -- "$raw_dir"
  return "$status"
}

scan_gitleaks() {
  check_tool gitleaks
  "${python_runner[@]}" -m scripts.security_policy >/dev/null
  local gitleaks_bin gitleaks_version raw_dir history_raw history_safe worktree_raw snapshot
  local history_status history_policy_status worktree_status
  gitleaks_bin="$(tool_path gitleaks)"
  gitleaks_version="$("${python_runner[@]}" -m scripts.security_tools version gitleaks)"
  raw_dir="$(new_raw_dir)"
  history_raw="$raw_dir/gitleaks-history-raw.json"
  history_safe="$raw_dir/gitleaks-history-safe.json"
  worktree_raw="$raw_dir/gitleaks-worktree-raw.json"
  snapshot="$raw_dir/worktree"
  mkdir -p "$snapshot" "$output_root/sarif"

  set +e
  "$gitleaks_bin" git \
    --no-banner --no-color --redact=100 --ignore-gitleaks-allow \
    --timeout 300 --log-opts=--all --exit-code=1 \
    --config "$repo_root/.gitleaks.toml" \
    --report-format json --report-path "$history_raw" "$repo_root"
  history_status=$?
  set -e
  if [[ "$history_status" -gt 1 || ! -f "$history_raw" ]]; then
    echo "Gitleaks full-history scan failed internally." >&2
    rm -rf -- "$raw_dir"
    return 2
  fi
  set +e
  "${python_runner[@]}" -m scripts.secret_scan_policy report \
    --input "$history_raw" \
    --allowlist .github/secret-scanning-allowlist.json \
    --output "$history_safe" \
    --scanner-version "$gitleaks_version"
  history_policy_status=$?
  set -e
  if [[ -f "$history_safe" ]]; then
    sanitize_sarif gitleaks-evidence "$history_safe" \
      "$output_root/sarif/gitleaks-history.sarif" gitleaks-history || \
      history_policy_status=2
  else
    history_policy_status=2
  fi

  while IFS= read -r -d '' path; do
    if [[ -f "$path" && ! -L "$path" ]]; then
      mkdir -p "$snapshot/$(dirname "$path")"
      cp --preserve=mode,timestamps -- "$path" "$snapshot/$path"
    fi
  done < <(git ls-files --cached --others --exclude-standard -z)
  set +e
  (
    cd "$snapshot"
    "$gitleaks_bin" dir \
      --no-banner --no-color --redact=100 --ignore-gitleaks-allow \
      --timeout 300 --exit-code=1 \
      --config "$repo_root/.gitleaks.toml" \
      --report-format json --report-path "$worktree_raw" .
  )
  worktree_status=$?
  set -e
  if [[ "$worktree_status" -gt 1 || ! -f "$worktree_raw" ]]; then
    echo "Gitleaks working-tree scan failed internally." >&2
    worktree_status=2
  else
    sanitize_sarif gitleaks-raw "$worktree_raw" \
      "$output_root/sarif/gitleaks-worktree.sarif" gitleaks-worktree || \
      worktree_status=2
  fi
  rm -rf -- "$raw_dir"
  if [[ "$history_policy_status" -ne 0 || "$worktree_status" -ne 0 ]]; then
    return 1
  fi
  return 0
}

trivy_common_args() {
  printf '%s\0' \
    --cache-dir "$cache_root/trivy" \
    --quiet \
    --timeout 10m
}

scan_trivy_repository() {
  check_tool trivy
  "${python_runner[@]}" -m scripts.security_policy >/dev/null
  local trivy_bin raw_dir fs_raw config_raw fs_status config_status
  trivy_bin="$(tool_path trivy)"
  raw_dir="$(new_raw_dir)"
  fs_raw="$raw_dir/trivy-fs.raw.sarif"
  config_raw="$raw_dir/trivy-config.raw.sarif"
  mkdir -p "$cache_root/trivy" "$output_root/sarif"
  mapfile -d '' -t common_args < <(trivy_common_args)
  local -a skips=(
    --skip-dirs .git
    --skip-dirs .cache
    --skip-dirs .venv
    --skip-dirs artifacts
    --skip-dirs mlruns
    --skip-dirs reports/generated
  )
  set +e
  "$trivy_bin" "${common_args[@]}" fs \
    --scanners vuln,secret --severity HIGH,CRITICAL --exit-code 1 \
    --ignorefile "$repo_root/security/trivy-ignore.yaml" \
    --format sarif --output "$fs_raw" "${skips[@]}" "$repo_root"
  fs_status=$?
  set -e
  if [[ -f "$fs_raw" ]]; then
    sanitize_sarif sarif "$fs_raw" "$output_root/sarif/trivy-filesystem.sarif" \
      trivy-filesystem || fs_status=2
  else
    fs_status=2
  fi
  set +e
  "$trivy_bin" "${common_args[@]}" config \
    --severity HIGH,CRITICAL --exit-code 1 \
    --ignorefile "$repo_root/security/trivy-ignore.yaml" \
    --format sarif --output "$config_raw" "${skips[@]}" "$repo_root"
  config_status=$?
  set -e
  if [[ -f "$config_raw" ]]; then
    sanitize_sarif sarif "$config_raw" "$output_root/sarif/trivy-configuration.sarif" \
      trivy-configuration || config_status=2
  else
    config_status=2
  fi
  rm -rf -- "$raw_dir"
  if [[ "$fs_status" -ne 0 || "$config_status" -ne 0 ]]; then
    return 1
  fi
  return 0
}

scan_trivy_image() {
  check_tool trivy
  local image="" component="" destination=""
  shift
  while [[ "$#" -gt 0 ]]; do
    case "$1" in
      --image)
        image="${2:-}"
        shift 2
        ;;
      --component)
        component="${2:-}"
        shift 2
        ;;
      --output-dir)
        destination="${2:-}"
        shift 2
        ;;
      *)
        echo "Unknown image-scan argument: $1" >&2
        return 2
        ;;
    esac
  done
  if [[ ! "$image" =~ ^(sha256:[0-9a-f]{64}|[a-zA-Z0-9./_-]+@sha256:[0-9a-f]{64})$ ]]; then
    echo "Trivy image gate requires an exact immutable image digest." >&2
    return 2
  fi
  if [[ ! "$component" =~ ^(api|dashboard|monitor)$ || -z "$destination" ]]; then
    echo "Trivy image gate requires an approved component and output directory." >&2
    return 2
  fi
  if ! docker image inspect "$image" >/dev/null 2>&1; then
    echo "Exact image digest is not present in the local Docker daemon." >&2
    return 2
  fi
  local trivy_bin cdx status
  trivy_bin="$(tool_path trivy)"
  mkdir -p "$cache_root/trivy" "$destination" "$output_root/sarif"
  cdx="$destination/${component}.cdx.json"
  mapfile -d '' -t common_args < <(trivy_common_args)
  set +e
  "$trivy_bin" "${common_args[@]}" image \
    --scanners vuln --severity HIGH,CRITICAL --exit-code 1 \
    --format cyclonedx --output "$cdx" "$image"
  status=$?
  set -e
  if [[ -f "$cdx" ]]; then
    sanitize_sarif cyclonedx "$cdx" \
      "$output_root/sarif/trivy-image-${component}.sarif" "trivy-image-${component}" || \
      status=2
  else
    status=2
  fi
  return "$status"
}

usage() {
  cat <<'EOF'
Usage: security_scan.sh repository|actionlint|shellcheck|checkov|gitleaks|trivy-repository
       security_scan.sh image --image <sha256> --component <name> --output-dir <path>
EOF
}

command="${1:-}"
case "$command" in
  repository)
    "${python_runner[@]}" -m scripts.security_policy
    "${python_runner[@]}" -m scripts.security_gate_runner --script "$0"
    ;;
  actionlint)
    scan_actionlint
    ;;
  shellcheck)
    scan_shellcheck
    ;;
  checkov)
    scan_checkov
    ;;
  gitleaks)
    scan_gitleaks
    ;;
  trivy-repository)
    scan_trivy_repository
    ;;
  image)
    scan_trivy_image "$@"
    ;;
  *)
    usage >&2
    exit 2
    ;;
esac

# Commands Cheat Sheet

## Codex

```bash
codex
codex doctor --summary
codex exec --model gpt-5.6-sol --sandbox workspace-write -c 'model_reasoning_effort="xhigh"' - < prompts/01_REPO_BOOTSTRAP.md
```

## Python and uv

```bash
uv sync --all-groups --locked
uv run ruff format --check .
uv run ruff check .
uv run mypy src
uv run pytest -q
uv run pytest --cov=src/modelguard --cov-report=term-missing
```

## Phase 02 training

```bash
make train
make inspect-model
make verify-model
make verify
```

## Phase 03 API and Phase 04 events

```bash
make api
curl -fsS http://127.0.0.1:8000/health/live
curl -fsS http://127.0.0.1:8000/health/ready
curl --fail-with-body -H 'Content-Type: application/json' \
  --data @examples/prediction-request.json http://127.0.0.1:8000/v1/predict
make load-test
uv run pytest tests/unit tests/contract tests/integration -q
find artifacts/predictions -maxdepth 1 -type f -name '*.jsonl' -print
```

Local prediction events are written to active `*.jsonl.open` files and published under final
`*.jsonl` names only on rotation or clean shutdown; the sink never reopens a closed file.

## Phase 05 deterministic monitoring

```bash
uv run python scripts/generate_monitoring_fixture.py \
  --scenario baseline --window-end 2026-01-01T01:00:00Z
uv run python -m modelguard.monitoring.cli run \
  --window-end 2026-01-01T01:00:00Z --as-of 2026-01-01T01:10:00Z
uv run python scripts/generate_monitoring_fixture.py \
  --scenario drifted --window-end 2026-01-01T02:00:00Z
uv run python -m modelguard.monitoring.cli run \
  --window-end 2026-01-01T02:00:00Z --as-of 2026-01-01T02:10:00Z
make export-monitor-schema
make monitor-status MONITOR_AS_OF=2026-01-01T04:10:00Z
```

Generated monitoring history/latest/run-status/alert artifacts live under ignored
`artifacts/reports/`.

## Phase 06 operations dashboard

```bash
make dashboard
uv run pytest tests/unit/test_dashboard_repository_parsing_phase06.py -q
uv run pytest tests/smoke/test_dashboard_startup_phase06.py -q
```

Local mode opens at `http://127.0.0.1:8501` and reads only the configured model/report/policy
artifacts. S3 mode requires private model/report buckets and returns a short-lived HTTPS report
download rather than a public object URL.

## Docker

```bash
./scripts/build_local_images.sh
docker compose up -d
docker compose ps
./scripts/smoke_local.sh
./scripts/demo_local.sh
./scripts/e2e_local.sh
./scripts/scan_local_images.sh
docker compose logs --tail=100 api dashboard
docker compose down -v
```

The scripts create validated JSON under `artifacts/phase-07-evidence/<run-id>/`; see
`docs/CONTAINER_LOCAL_DEMO.md`. The monitor is a scale-zero one-shot Compose service and is not a
long-running process; target it with `docker compose run monitor ...` when invoking it manually.

## Terraform

```bash
terraform fmt -recursive infrastructure
terraform -chdir=infrastructure/environments/demo init -backend=false
terraform -chdir=infrastructure/environments/demo validate
make security-tools-bootstrap
make security-scan
```

## Reproducible security release gates

```bash
make security-tools-bootstrap
make security-tools-check
make security-scan
make release-gates
./scripts/scan_local_images.sh  # exact existing api/dashboard/monitor image IDs
```

The bootstrap writes only to ignored `.cache/security-tools/`. The lock, shared policy, and generated
sanitized-SARIF contract are documented in `docs/CICD_SECURITY.md`.

## Git

```bash
git status
git diff --check
git diff --stat
git add -A
git commit -m "phase XX: message"
```

## AWS

```bash
aws sts get-caller-identity
aws ecs list-services --cluster "$CLUSTER_NAME"
aws ecs list-tasks --cluster "$CLUSTER_NAME"
aws logs tail "$LOG_GROUP" --follow
```

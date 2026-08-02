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
`artifacts/reports/`. The dashboard remains a later phase.

## Docker

```bash
docker compose up --build -d
docker compose ps
docker compose logs -f api
docker compose down -v
```

## Terraform

```bash
terraform fmt -recursive infrastructure
terraform -chdir=infrastructure/environments/demo init -backend=false
terraform -chdir=infrastructure/environments/demo validate
checkov -d infrastructure
```

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

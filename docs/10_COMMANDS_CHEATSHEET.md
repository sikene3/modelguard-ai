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

The API, dashboard, and monitoring commands belong to later phases and are not implemented yet.

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

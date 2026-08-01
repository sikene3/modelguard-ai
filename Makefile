SHELL := /usr/bin/env bash
.DEFAULT_GOAL := help

UV ?= uv
UV_RUN ?= $(UV) run
UV_CACHE_DIR ?= $(CURDIR)/.cache/uv
export UV_CACHE_DIR
PIP_AUDIT_CACHE_DIR ?= .cache/pip-audit
PIP_AUDIT_REQUIREMENTS ?= .cache/audit-requirements.txt
TRAINING_CONFIG ?= configs/phase-02-training.json
TRAINING_OUTPUT_ROOT ?= artifacts
MODEL_VERSION ?= 1.0.0
MODEL_BUNDLE ?= $(TRAINING_OUTPUT_ROOT)/model-bundles/$(MODEL_VERSION)

.PHONY: help setup format lint typecheck test security generate-data train inspect-model verify-model verify clean

help:
	@echo "ModelGuard AI commands"
	@echo "  make setup       Install/sync all dependency groups"
	@echo "  make format      Format source and tests"
	@echo "  make lint        Check formatting and lint"
	@echo "  make typecheck   Run mypy"
	@echo "  make test        Run pytest and enforce coverage"
	@echo "  make security    Run Bandit, pip-audit, and the basic secret/file check"
	@echo "  make train       Generate audited data/splits, train, track, and bundle"
	@echo "  make inspect-model  Validate bundle metadata without joblib loading"
	@echo "  make verify-model   Verify bundle and run one trusted local smoke prediction"
	@echo "  make verify      Run quality/security gates and verify the generated bundle"

setup:
	$(UV) sync --all-groups --locked

format:
	$(UV_RUN) ruff format .
	$(UV_RUN) ruff check --fix .

lint:
	$(UV_RUN) ruff format --check .
	$(UV_RUN) ruff check .

typecheck:
	$(UV_RUN) mypy src

test:
	$(UV_RUN) pytest -q

security:
	$(UV_RUN) bandit -q -r src
	mkdir -p $(dir $(PIP_AUDIT_REQUIREMENTS))
	$(UV) export --quiet --all-groups --frozen --no-emit-project \
		--output-file $(PIP_AUDIT_REQUIREMENTS)
	$(UV_RUN) pip-audit --strict --require-hashes --disable-pip --progress-spinner=off \
		--cache-dir $(PIP_AUDIT_CACHE_DIR) --requirement $(PIP_AUDIT_REQUIREMENTS)
	./scripts/check_no_secrets.sh

generate-data:
	$(UV_RUN) python -m modelguard.training.cli generate \
		--config "$(TRAINING_CONFIG)" --output-root "$(TRAINING_OUTPUT_ROOT)"

train: generate-data
	$(UV_RUN) python -m modelguard.training.cli train \
		--config "$(TRAINING_CONFIG)" --output-root "$(TRAINING_OUTPUT_ROOT)" \
		--repository-root "$(CURDIR)"

inspect-model:
	$(UV_RUN) python -m modelguard.training.cli inspect --bundle "$(MODEL_BUNDLE)"

verify-model:
	$(UV_RUN) python -m modelguard.training.cli verify \
		--bundle "$(MODEL_BUNDLE)" --trusted-origin

verify: lint typecheck test security verify-model

clean:
	rm -rf .pytest_cache .mypy_cache .ruff_cache htmlcov .coverage coverage.xml build dist
	find src tests -type d -name __pycache__ -prune -exec rm -rf {} +

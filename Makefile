SHELL := /usr/bin/env bash
.DEFAULT_GOAL := help

UV ?= uv
UV_RUN ?= $(UV) run
UV_CACHE_DIR ?= $(CURDIR)/.cache/uv
export UV_CACHE_DIR
MLFLOW_DISABLE_TELEMETRY ?= true
export MLFLOW_DISABLE_TELEMETRY
PIP_AUDIT_CACHE_DIR ?= .cache/pip-audit
PIP_AUDIT_REQUIREMENTS ?= .cache/audit-requirements.txt
TRAINING_CONFIG ?= configs/phase-02-training.json
MONITORING_CONFIG ?= configs/phase-05-monitoring.json
MONITOR_WINDOW_END ?=
MONITOR_AS_OF ?=
TRAINING_OUTPUT_ROOT ?= artifacts
MODEL_VERSION ?= 1.0.0
MODEL_BUNDLE ?= $(TRAINING_OUTPUT_ROOT)/model-bundles/$(MODEL_VERSION)
API_HOST ?= 127.0.0.1
API_PORT ?= 8000
API_MAX_CONCURRENCY ?= 64
API_INFERENCE_WORKERS ?= 1
API_GRACEFUL_SHUTDOWN_TIMEOUT_SECONDS ?= 10
API_KEEP_ALIVE_SECONDS ?= 5
LOAD_REQUESTS ?= 100
LOAD_CONCURRENCY ?= 4
DASHBOARD_HOST ?= 127.0.0.1
DASHBOARD_PORT ?= 8501
PHASE11_RUN_ID ?=
PHASE11_ANCHOR ?=
PHASE11_EVIDENCE_ROOT ?= artifacts/phase-11-evidence
PHASE11_FIRST_SUMMARY ?=
PHASE11_SECOND_SUMMARY ?=
PHASE11_REPEATABILITY_OUTPUT ?= $(PHASE11_EVIDENCE_ROOT)/local-repeatability.json
PHASE11_TEARDOWN_SUMMARY ?=

.PHONY: help setup format lint typecheck test security security-tools-bootstrap security-tools-check security-scan release-gates generate-data train inspect-model verify-model api load-test export-monitor-schema monitor monitor-status dashboard docker-build docker-up smoke-local demo-local e2e-local phase11-demo-local phase11-compare-local phase11-verify-teardown portfolio-check scan-images shell-check verify clean

help:
	@echo "ModelGuard AI commands"
	@echo "  make setup       Install/sync all dependency groups"
	@echo "  make format      Format source and tests"
	@echo "  make lint        Check formatting and lint"
	@echo "  make typecheck   Run mypy"
	@echo "  make test        Run pytest and enforce coverage"
	@echo "  make security    Run Bandit, pip-audit, and the basic secret/file check"
	@echo "  make security-tools-bootstrap  Install the checksum/digest-pinned local scanners"
	@echo "  make security-tools-check  Verify every cached scanner against the lock"
	@echo "  make security-scan  Run actionlint, ShellCheck, Checkov, Gitleaks, and Trivy"
	@echo "  make release-gates  Run the full verification and reproducible security gates"
	@echo "  make train       Generate audited data/splits, train, track, and bundle"
	@echo "  make inspect-model  Validate bundle metadata without joblib loading"
	@echo "  make verify-model   Verify bundle and run one trusted local smoke prediction"
	@echo "  make api         Start the bounded local FastAPI service"
	@echo "  make load-test   Measure a running local API against Phase 03 targets"
	@echo "  make export-monitor-schema  Re-export the strict Phase 05 report JSON Schema"
	@echo "  make monitor      Run one explicit finalized window (MONITOR_WINDOW_END/MONITOR_AS_OF)"
	@echo "  make monitor-status  Read run health at explicit MONITOR_AS_OF"
	@echo "  make dashboard    Start the read-only local Streamlit operations dashboard"
	@echo "  make docker-build Build three provenance-labeled local runtime images"
	@echo "  make docker-up    Start the local API and dashboard through Compose"
	@echo "  make smoke-local  Prove API/event/monitor/dashboard container integration"
	@echo "  make demo-local   Prove the containerized Healthy -> Drifted flow"
	@echo "  make e2e-local    Prove insufficient/corrupt-bundle/sink-outage scenarios"
	@echo "  make phase11-demo-local  Run one explicit-window Phase 11 evidence cycle"
	@echo "  make phase11-compare-local  Compare two completed Phase 11 local cycles"
	@echo "  make phase11-verify-teardown  Recheck one Phase 11 local closure summary"
	@echo "  make portfolio-check  Validate Phase 13 public assets, links, claims, and hygiene"
	@echo "  make scan-images  Scan images and enforce bounded Trivy exceptions"
	@echo "  make shell-check  Run Bash syntax and the verified repository-local ShellCheck"
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
	$(UV_RUN) mypy src scripts

test:
	$(UV_RUN) pytest -q

security:
	$(UV_RUN) bandit -q -r src scripts
	mkdir -p $(dir $(PIP_AUDIT_REQUIREMENTS))
	$(UV) export --quiet --all-groups --frozen --no-emit-project \
		--output-file $(PIP_AUDIT_REQUIREMENTS)
	$(UV_RUN) pip-audit --strict --require-hashes --disable-pip --progress-spinner=off \
		--cache-dir $(PIP_AUDIT_CACHE_DIR) --requirement $(PIP_AUDIT_REQUIREMENTS)
	./scripts/check_no_secrets.sh

security-tools-bootstrap:
	uv run --frozen --no-sync python -m scripts.security_tools bootstrap

security-tools-check:
	uv run --frozen --no-sync python -m scripts.security_tools check

security-scan: security-tools-check
	./scripts/security_scan.sh repository

release-gates: verify security-scan portfolio-check

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

api:
	# Keep explicit process bounds separate from the public Make target name.
	API_MAX_CONCURRENCY="$(API_MAX_CONCURRENCY)" \
	API_INFERENCE_WORKERS="$(API_INFERENCE_WORKERS)" \
	GRACEFUL_SHUTDOWN_TIMEOUT_SECONDS="$(API_GRACEFUL_SHUTDOWN_TIMEOUT_SECONDS)" \
	$(UV_RUN) uvicorn modelguard.api.main:app \
		--host "$(API_HOST)" --port "$(API_PORT)" --workers 1 \
		--limit-concurrency "$(API_MAX_CONCURRENCY)" \
		--timeout-keep-alive "$(API_KEEP_ALIVE_SECONDS)" \
		--timeout-graceful-shutdown "$(API_GRACEFUL_SHUTDOWN_TIMEOUT_SECONDS)" \
		--no-access-log

load-test:
	$(UV_RUN) python scripts/load_test_api.py \
		--url "http://$(API_HOST):$(API_PORT)" \
		--requests "$(LOAD_REQUESTS)" --concurrency "$(LOAD_CONCURRENCY)"

export-monitor-schema:
	$(UV_RUN) python scripts/export_monitoring_report_schema.py \
		--output contracts/monitoring-report-v1.schema.json

monitor:
	@test -n "$(MONITOR_WINDOW_END)" || { echo "MONITOR_WINDOW_END is required (UTC ...Z)" >&2; exit 2; }
	@test -n "$(MONITOR_AS_OF)" || { echo "MONITOR_AS_OF is required (UTC ...Z)" >&2; exit 2; }
	$(UV_RUN) python -m modelguard.monitoring.cli run \
		--config "$(MONITORING_CONFIG)" --window-end "$(MONITOR_WINDOW_END)" \
		--as-of "$(MONITOR_AS_OF)"

monitor-status:
	@test -n "$(MONITOR_AS_OF)" || { echo "MONITOR_AS_OF is required (UTC ...Z)" >&2; exit 2; }
	$(UV_RUN) python -m modelguard.monitoring.cli status --as-of "$(MONITOR_AS_OF)"

dashboard:
	$(UV_RUN) streamlit run src/modelguard/dashboard/app.py \
		--server.address "$(DASHBOARD_HOST)" --server.port "$(DASHBOARD_PORT)" \
		--server.headless true --browser.gatherUsageStats false

docker-build:
	./scripts/build_local_images.sh

docker-up:
	bash -c 'source scripts/local_compose_lib.sh && modelguard_compose up -d'

smoke-local:
	./scripts/smoke_local.sh

demo-local:
	./scripts/demo_local.sh

e2e-local:
	./scripts/e2e_local.sh

phase11-demo-local:
	@test -n "$(PHASE11_RUN_ID)" || { echo "PHASE11_RUN_ID is required." >&2; exit 2; }
	@test -n "$(PHASE11_ANCHOR)" || { echo "PHASE11_ANCHOR is required (UTC ...Z)." >&2; exit 2; }
	$(UV_RUN) python scripts/phase11_demo.py run-local \
		--run-id "$(PHASE11_RUN_ID)" --anchor "$(PHASE11_ANCHOR)" \
		--evidence-root "$(PHASE11_EVIDENCE_ROOT)"

phase11-compare-local:
	@test -n "$(PHASE11_FIRST_SUMMARY)" || { echo "PHASE11_FIRST_SUMMARY is required." >&2; exit 2; }
	@test -n "$(PHASE11_SECOND_SUMMARY)" || { echo "PHASE11_SECOND_SUMMARY is required." >&2; exit 2; }
	$(UV_RUN) python scripts/phase11_demo.py compare-local-runs \
		--first "$(PHASE11_FIRST_SUMMARY)" --second "$(PHASE11_SECOND_SUMMARY)" \
		--output "$(PHASE11_REPEATABILITY_OUTPUT)"

phase11-verify-teardown:
	@test -n "$(PHASE11_TEARDOWN_SUMMARY)" || { echo "PHASE11_TEARDOWN_SUMMARY is required." >&2; exit 2; }
	$(UV_RUN) python scripts/phase11_demo.py verify-local-teardown \
		--summary "$(PHASE11_TEARDOWN_SUMMARY)"

portfolio-check:
	$(UV_RUN) python -m scripts.validate_portfolio

scan-images:
	./scripts/scan_local_images.sh

shell-check:
	./scripts/check_shell.sh

verify: lint typecheck test security verify-model

clean:
	rm -rf .pytest_cache .mypy_cache .ruff_cache htmlcov .coverage coverage.xml build dist
	find src tests -type d -name __pycache__ -prune -exec rm -rf {} +

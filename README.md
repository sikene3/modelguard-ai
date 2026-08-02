# ModelGuard AI

ModelGuard AI is a production-style AWS MLOps portfolio project for a versioned synthetic
fraud-risk model, observable inference, and deterministic drift incident handling.

## Current status

Phase 03 serves the audited Phase 02 model bundle through a typed FastAPI application. Startup checks
the exact bundle file set, checksums, strict manifests, schema, lineage, configured version, trusted
origin, and a smoke prediction before readiness succeeds. Liveness remains available when loading
fails. Prediction events are still a no-op interface seam; persistence, monitoring, dashboard,
containers, and AWS deployment remain future-phase work.

The architecture and acceptance contract are defined in [ARCHITECTURE.md](ARCHITECTURE.md),
[PROJECT_SPEC.md](PROJECT_SPEC.md), and [ACCEPTANCE_CRITERIA.md](ACCEPTANCE_CRITERIA.md).

## Requirements and setup

- Git, Make, and uv 0.12.x.
- Python is pinned by `.python-version` and `requires-python` to Python 3.12; developer commands use
  `uv run` and never rely on the host's unversioned `python3` command.

```bash
./scripts/verify_environment.sh
uv sync --all-groups --locked
uv run python -c 'import modelguard; print(modelguard.__version__)'
```

`scripts/setup_ubuntu.sh` is a manual-only installation guide. It deliberately does not execute
remote installer scripts whose artifacts are not pinned and verified in this repository.

## Quality gates

```bash
make format       # apply Ruff formatting and safe lint fixes
make lint         # formatting and lint checks
make typecheck    # strict Mypy checks for src/
make test         # Pytest with branch coverage
make security     # Bandit, pip-audit, and a basic redacted secret/file check
make api          # bounded local FastAPI server on 127.0.0.1:8000
make load-test    # test a separately running local API against explicit load targets
make verify       # quality/security gates plus verification of the generated bundle
```

The repository-level secret check is intentionally basic defense in depth; it does not replace a
dedicated scanner or review of staged changes.

## Audited local training

The committed [Phase 02 configuration](configs/phase-02-training.json) fixes every seed, split,
preprocessing, estimator, calibration, threshold, and baseline parameter. After `make setup`, run:

```bash
make train          # one clean run; refuses an existing data directory or model version
make inspect-model  # verifies structure, checksums, strict JSON, and identities; no joblib load
make verify-model   # repeats metadata checks, confirms trusted local origin, then smoke-predicts
```

`make train` creates exactly one local MLflow run under `mlruns/` and generated evidence under
`artifacts/`. It is intentionally not an overwrite command. To create another model, review and
version the committed configuration and select a new immutable model version rather than deleting or
reusing an existing bundle identity.

The workflow has explicit evidence boundaries:

1. Generate and validate independent synthetic rows with stable `event_id` values; latent logits and
   probabilities never leave generator memory.
2. Persist and re-verify the canonical train/validation/test assignment and all membership hashes.
3. Fit and five-fold sigmoid-calibrate using training rows only.
4. Select and lock `score >= threshold` on validation over all 1,001 integer-thousandth candidates.
5. Freeze training-reference feature/score/decision distributions without making training-performance
   claims.
6. Score the held-out test once and publish those results as the public evaluation.

Generated outputs are:

```text
artifacts/data/                    dataset, config/quality manifests, split CSV/manifest
artifacts/training/1.0.0/          model card, data card, reliability/confusion plots
artifacts/model-bundles/1.0.0/     exact seven-file immutable bundle
mlruns/                            local file-backed MLflow experiment and one run
```

The bundle identity is `{model_version, manifest_sha256}`. Checksums detect accidental or malicious
byte changes but do not authenticate a joblib file's origin; deserialization therefore requires an
explicit trusted-origin confirmation after every structural, checksum, contract, and identity check.

## Local inference API

Create the immutable bundle once with `make train`, then start the API in a separate terminal:

```bash
make api
```

Liveness reports only process health. Readiness succeeds only after the bundle is fully verified and
loaded once; the service never reloads the model per request.

```bash
curl -fsS http://127.0.0.1:8000/health/live
curl -fsS http://127.0.0.1:8000/health/ready
curl -fsS http://127.0.0.1:8000/version
curl -fsS http://127.0.0.1:8000/metrics | head
```

Local mode is intentionally open. Send the exact extra-field-forbidding Phase 02 feature contract:

```bash
curl --fail-with-body \
  -H 'Content-Type: application/json' \
  --data '{
    "amount": 4200.0,
    "transaction_hour": 2,
    "velocity_1h": 8,
    "distance_from_home_km": 180.0,
    "device_risk_score": 0.82,
    "merchant_risk_score": 0.64,
    "is_new_device": true,
    "country_code": "EG",
    "device_type": "mobile"
  }' \
  http://127.0.0.1:8000/v1/predict
```

The successful response contains a server-generated request ID, a finite `[0,1]` risk score, the
locked-threshold decision, model version, and measured service latency. Application logs are
one-line JSON and deliberately omit request bodies, query strings, authorization headers, token
values, feature values, filesystem paths, and environment dumps. Uvicorn access logs are disabled
because they can include query strings.

The measured local gate uses 100 requests at concurrency 4 and requires at least 25 requests/second,
zero errors, and p95 latency at most 250 ms:

```bash
make load-test
```

### AWS access-mode contract

Phase 03 implements the application boundary but does not create AWS clients or infrastructure.
Every later AWS ALB must use an explicit restricted `ALB_ALLOWED_CIDR`; settings reject a missing,
world-open, or noncanonical CIDR.

- `https_token` requires ALB-provided HTTPS, then checks `Authorization: Bearer` in constant time.
  ECS must inject `PREDICTION_BEARER_TOKEN` from the separately configured pre-created SSM
  SecureString ARN in `PREDICTION_TOKEN_SSM_ARN`. The token value must never enter Terraform state,
  files, command history, logs, screenshots, or metric dimensions. Query parameters are forbidden.
- `http_cidr_only` accepts prediction requests without a reusable token and rejects an Authorization
  header. It is a short-lived, restricted-CIDR, synthetic-only fallback. It provides neither secure
  transport nor authentication.

Health routes are token-exempt and minimal for ALB checks. `/version` remains CIDR-restricted at the
ALB. `/metrics` is a local/test Prometheus surface: the application returns 404 for it in AWS mode,
and the ALB must not route it publicly. AWS custom application signals use fixed-dimension EMF JSON
on stdout instead.

An illustrative HTTPS request uses a token already present in the process environment (never a query
parameter):

```bash
curl --fail-with-body --proto '=https' \
  -H "Authorization: Bearer ${PREDICTION_BEARER_TOKEN:?not_set}" \
  -H 'Content-Type: application/json' \
  --data @examples/prediction-request.json \
  https://restricted-demo.example/v1/predict
```

The restricted HTTP fallback deliberately sends no credential:

```bash
curl --fail-with-body \
  -H 'Content-Type: application/json' \
  --data @examples/prediction-request.json \
  http://restricted-demo.example/v1/predict
```

## Local configuration

Copy `.env.example` to `.env` only when local, non-secret overrides are needed. Defaults load without
AWS credentials or network access. Request bodies are capped at 16 KiB, request admission at 64,
model inference workers at one, concurrency waiting at one second, the no-op event-sink call at 100
ms, and graceful shutdown at ten seconds. `make api` also applies Uvicorn connection concurrency,
keep-alive, and graceful-shutdown bounds. The locked Phase 05 monitoring minimum is
`MIN_MONITORING_SAMPLES=500`; small windows will later be classified as insufficient data rather
than healthy.

## Repository layout

```text
src/modelguard/       training, inference, API, configuration, logging, and telemetry packages
tests/                unit, API contract, integration/load, and smoke test roots
scripts/              bootstrap, validation, and safety helpers
prompts/              phase implementation contracts
checklists/           phase completion gates
reports/              phase evidence reports
artifacts/            ignored generated datasets, evidence, and immutable local bundles
configs/              committed versioned training behavior
mlruns/               ignored local MLflow file store created by Phase 02
```

## Security and limitations

This is a synthetic, temporary, production-style demo—not a production service. Calibrated scores
are meaningful only for the generator distribution, and the `10 × FN + FP` threshold is a synthetic
policy rather than a real economic optimum. Do not commit
credentials, `.env` files, Terraform variables/state/plans, generated model artifacts, or real
payment data. See [docs/03_SECURITY_BASELINE.md](docs/03_SECURITY_BASELINE.md) for the broader
security contract.

# ModelGuard AI

ModelGuard AI is a production-style AWS MLOps portfolio project for a versioned synthetic
fraud-risk model, observable inference, and deterministic drift incident handling.

## Current status

Phase 02 provides an audited, deterministic synthetic-data and model-training workflow. It persists
one hashed stratified split before fitting, calibrates a preprocessing-plus-logistic-regression
Pipeline on training rows only, locks a validation-only synthetic-cost threshold, evaluates the
held-out test once, records an explicit local MLflow run, and publishes a verified immutable model
bundle. API serving, prediction events, monitoring, dashboard, containers, and AWS deployment remain
future-phase work.

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

## Local configuration

Copy `.env.example` to `.env` only when local overrides are needed. Defaults load without AWS
credentials or network access. The locked Phase 05 monitoring minimum is
`MIN_MONITORING_SAMPLES=500`; small windows will later be classified as insufficient data rather
than healthy.

## Repository layout

```text
src/modelguard/       importable package and phase-scoped subpackages
tests/                unit, contract, integration, and smoke test roots
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

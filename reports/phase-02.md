# Phase 02 Report

## Objective

Build a deterministic synthetic-data and calibrated logistic-regression workflow whose split,
evaluation sequence, MLflow record, baseline distributions, immutable bundle, and artifact lineage
can be audited without using training performance as public evidence.

## Scope completed

- Added independent, prefix-stable per-row synthetic generation. Stable `event_id` values derive
  only from the generator version, seed, and row index; latent logits/probabilities never enter the
  persisted dataframe.
- Added the locked request/data schema and quality rules for exact columns/order, stable unique IDs,
  missing/non-finite values, bounds, categorical domains, binary labels, both classes, and explicit
  generator-only/leakage rejection.
- Added order-independent canonical SHA-256 records that name algorithm, canonicalization version,
  ordering, and exclusions. Dataset, configuration, complete split mapping, each split membership,
  source tree, raw artifacts, and `uv.lock` use explicit identities.
- Added an atomic pre-fit data stage containing the dataset, dataset/config/quality manifests, one
  persisted stratified assignment, and a split manifest. Training recomputes every dataset/split
  identity and the exact configured canonical assignment, and blocks before fit on any mismatch.
- Added a strict feature allowlist and one sklearn Pipeline containing explicit imputers, scaling,
  one-hot encoding, a ColumnTransformer, and LogisticRegression. The entire Pipeline is wrapped by
  `CalibratedClassifierCV` with shuffled five-fold training-only `StratifiedKFold`, sigmoid method,
  and ensemble enabled. All constructor parameters and seeds are present in versioned configuration;
  `class_weight` is null and no sampler exists.
- Added the exact validation grid `0/1000` through `1000/1000`, `score >= threshold`, cost
  `10 × FN + FP`, and tie order: cost, fewer FN, fewer FP, then lowest threshold. The threshold
  contract is locked before any canonical test prediction.
- Added support-aware finite metric contracts for average precision, prevalence/AP lift, ROC-AUC,
  Brier score, log loss, confusion counts/rates, reliability bins, synthetic cost, and held-out
  synthetic cost per event. Undefined/zero-denominator values carry JSON `null`, operands, and a
  reason; strict writers reject NaN/Infinity.
- Added a training-only baseline with collapsed quantile-decile edges, constant flags, missingness,
  raw counts/proportions, explicit underflow/overflow semantics, complete categorical universes, and
  post-lock training-reference calibrated-score and decision distributions. It has no label or
  training-performance contract.
- Added explicit local `file:` MLflow tracking with no autologging. The canonical run contains 78
  parameters, 18 metrics, 10 tags, data/config/split artifacts, two plots, both cards, and the exact
  bundle files.
- Added the exact seven-file bundle. Construction uses a temporary sibling, refuses an existing
  version, hashes every payload except `checksums.sha256`, verifies the temporary bundle, and then
  atomically renames it.
- Added ordered verification: reject root/child symlinks and missing/extra/non-files; validate
  checksum syntax and byte hashes; parse duplicate-key/non-finite/extra-field-rejecting JSON
  contracts; validate the smoke row's types and domains; reconcile identities, configured seeds,
  split/calibration parameters and supports, feature order, threshold evidence, timestamps, and
  baseline/test memberships; only then permit trusted-origin joblib loading and one schema-valid
  smoke prediction. Checksums are explicitly documented as corruption detection, not authenticity.
- Added generate/train/inspect/verify CLI commands, Make targets, README instructions, model/data
  cards, plots, acceptance updates, and comprehensive unit/integration evidence.

## Files changed

- Configuration/tooling: `configs/phase-02-training.json`, `Makefile`, `pyproject.toml`, `README.md`,
  `ACCEPTANCE_CRITERIA.md`, `FILE_MANIFEST.txt`.
- Core lineage/serialization: `src/modelguard/core/hashing.py`,
  `src/modelguard/core/serialization.py`.
- Data: `src/modelguard/data/generator.py`, `src/modelguard/data/schema.py`,
  `src/modelguard/data/split.py`, `src/modelguard/data/validation.py`.
- Training: `src/modelguard/training/baseline.py`, `bundle.py`, `cli.py`, `config.py`, `evaluate.py`,
  `pipeline.py`, `tracking.py`, and `workflow.py`.
- Tests: `tests/conftest.py`, `tests/unit/test_data_phase02.py`,
  `test_split_pipeline_phase02.py`, `test_evaluate_baseline_phase02.py`,
  `test_bundle_phase02.py`, and `tests/integration/test_training_workflow_phase02.py`.
- Phase records: `checklists/PHASE_02.md`, `tasks/phase_status.json`, and this report.

## Commands and evidence

```text
make train
PASS — final clean generation plus canonical 5,000-row training run; one finished MLflow run and
bundle 1.0.0 created. The generated-only earlier snapshot was moved aside before this final run so
the immutable bundle records the final repaired source tree, then deleted after final verification.

make inspect-model
PASS — strict metadata/checksum/identity verification with deserialized_model=false; 750 test rows.

make verify-model
PASS — trusted local joblib loaded only after verification; smoke score 0.9981110662188358.

uv run pytest tests/unit tests/integration -q
PASS — 52 passed in 4.60s; 84.87% total branch coverage.

make verify
PASS — Ruff, strict Mypy, 54 tests, 84.87% coverage, Bandit, a live hashed-lock pip-audit, the
secret/file scan, and trusted bundle verification all completed with exit code 0. Pip-audit reported
`No known vulnerabilities found`.

UV_CACHE_DIR=.cache/uv uv run ruff format --check . && ... ruff check .
PASS — 96 files formatted; all lint checks passed.

UV_CACHE_DIR=.cache/uv uv run mypy src
PASS — no issues in 25 source files under strict mode.

UV_CACHE_DIR=.cache/uv uv run bandit -q -r src
PASS — no findings.

./scripts/check_no_secrets.sh
PASS — ignore contract and redacted tracked/untracked content scan passed.

UV_CACHE_DIR=.cache/uv uv lock --check --offline
PASS — resolved 159 packages from the unchanged lock.

verify deliberately modified copy of metrics.json
EXPECTED REJECTION — `byte checksum mismatch: metrics.json`; model loader was not reached. The
parameterized focused command passed 7/7 cases, changing every bundle file and proving pre-load
rejection. Additional tests recompute checksums/manifest payload hashes and still reject inconsistent
threshold evidence and manifest seeds.
```

## Canonical held-out result

The public headline result is the single canonical held-out test evaluation after threshold lock:

- Split support: train 3,500; validation 750; test 750.
- Locked validation threshold: `0.075` using `score >= threshold`.
- Test prevalence: `0.188` (141 / 750).
- Average precision: `0.40842191798974226`; AP lift: `2.1724570105837353`.
- ROC-AUC: `0.7291222676402427`.
- Brier score: `0.13517268524374973`; log loss: `0.42991718637314047`.
- Confusion counts: TN 61, FP 548, FN 2, TP 139.
- Precision `0.20232896652110627`; recall `0.9858156028368794`; F1
  `0.3357487922705314`; false-positive rate `0.8998357963875205`.
- Synthetic cost: 568; held-out synthetic cost per event: `0.7573333333333333`.

The low threshold/high false-positive rate follows the locked 10:1 false-negative cost and is not
retuned to make the demo look better. These figures describe only this synthetic generator and are
not real fraud probabilities or business economics.

## Generated artifacts and identities

- Canonical data: `artifacts/data/synthetic_fraud.csv` (byte SHA-256
  `c5c77aca4c28aa2d1adf91597a559c093455eff9808ce0d53ab498683d18f26e`; canonical semantic dataset
  SHA-256 `e4440dddbea5b4f79dfcc8b20b8002a986a3432c1ff3eaaa20b0ac04b9c60234`).
- Canonical split assignment SHA-256:
  `fdf4a875c827d5fe9f0aca9791404a57e8a31d83b75bbb64fe156ad44bef8259`.
- Configuration SHA-256:
  `6ab49206ab79add3837d7fb65dd836e85d989eab0a243f793a00cb1e7a8bdf8b`.
- MLflow: `mlruns/`, experiment `modelguard-phase-02`, finished run
  `df920ce2d27e4d82823a60fe008bb8c0`; exactly one run, 78 parameters, 18 metrics, and 10 tags.
- Cards/plots: `artifacts/training/1.0.0/{data_card.md,model_card.md,reliability_plot.html,confusion_matrix_plot.html}`.
- Bundle: `artifacts/model-bundles/1.0.0/`; durable identity
  `{model_version: 1.0.0, manifest_sha256:
  49cbe04bc4285fc71463d0071e3babc3a5f5c20011541a072b4844bb5c78afd9}`.
- Bundle payload SHA-256 values:
  - `model.joblib`: `5f3e1e5d1b81917e64eba2c83e037b75fd2e2589e8e9bb78daa89c89db810f15`.
  - `manifest.json`: `49cbe04bc4285fc71463d0071e3babc3a5f5c20011541a072b4844bb5c78afd9`.
  - `input_schema.json`: `8d4c87375cdf14fb271c32fbe613c9ce44b441ae5b153488e814cf94fe6cfed6`.
  - `metrics.json`: `b4781eb42ccf1b7b8b9ef102a9e43b4f2c3e14916453ebeecb7e211a017374d5`.
  - `threshold.json`: `d181eee5374eacd11ff5df32a7b63da68be24cd33e4e624141f6917255e5ea1c`.
  - `baseline_profile.json`: `46c7a64c76ca67bab07a3ec8ac0051d37920b30c36974854c539e7e105ab093b`.
- Training-time source-tree SHA-256:
  `264da7f57f96596ce535030203f0b01d172d90d621e649e9a4b1504d586748ab`;
  independently recomputed from the final working tree and matched the manifest.
- `uv.lock` SHA-256:
  `e2239d71d962cd30324a948f0757f66c01150d2c03b131798903a3e28812c10e`.

Generated data, MLflow state, and model artifacts are intentionally ignored and must not be committed.

## Decisions and assumptions

- CSV is the canonical local dataset format for this phase. Semantic identity hashes normalized
  JSON records sorted by `event_id`, so physical CSV/row ordering does not define the dataset.
- The current locked sklearn version uses its explicit `penalty="deprecated"` sentinel with
  `l1_ratio=0.0`, which is the current non-warning L2 API behavior; all other LogisticRegression
  constructor values are explicit and manifest-versioned.
- The MLflow file store is a sibling `mlruns/`, not `artifacts/mlruns/`. Current MLflow rejects any
  tracking-store path below a path component literally named `artifacts` because that name is
  reserved for run artifacts.
- The launch kit has no Git commit/HEAD. The manifest therefore records Git as unavailable with an
  explicit reason and relies on canonical source-tree plus dependency-lock hashes.
- Bundle inspection never deserializes joblib. Verification requires an explicit trusted-origin
  confirmation; later publishers must preserve both semantic version and manifest digest.

## Residual risks

- The repository still has no commit history and every supplied/implemented file is untracked. The
  bundle records and matches the final source-tree hash, but no Git SHA can anchor that snapshot.
- Joblib is pickle-based and unsafe from an untrusted source. Checksums detect corruption only; they
  do not provide signing or provenance authentication.
- Synthetic independence and calibration do not establish real-world fraud validity. The cost rule
  is a versioned demo heuristic, and the canonical result's high false-positive rate is retained
  honestly.

## Acceptance checklist status

All Phase 02 functional/statistical/artifact checklist items are implemented and evidenced. The
required commands and the full live quality/security/model gate exit zero. Phase 02 is complete and
is a GO for Phase 03.

## Suggested commit message

`feat: add audited Phase 02 training and immutable bundle`

## Next manual action

Review `FILE_MANIFEST.txt` itself and its 125 listed untracked commit-candidate paths (not ignored
`artifacts/` or `mlruns/`), then create the manual commit with the suggested message. Phase 03 may
begin only after that review/commit decision.

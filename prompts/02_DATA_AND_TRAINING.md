# Phase 02 — Synthetic Data, Training, Evaluation, and Model Bundle

## Recommended mode
GPT-5.6 Sol, XHigh. Use Max for unresolved statistical/leakage/calibration failures.

## Objective
Build a deterministic training workflow whose evaluation and artifact lineage can be audited.

## Read first
Core specs, `AGENTS.md`, `checklists/PHASE_02.md`, ADR-002, ADR-004, and ADR-006.

## Locked statistical contract
- Independent synthetic rows only; stable synthetic `event_id`; never persist latent probability/logit.
- Persist one canonical stratified train/validation/test assignment **before fitting**; verify
  disjointness, exhaustiveness, both classes, dataset hash, and per-split membership hashes.
- Strict feature allowlist excludes ID, label, split, manifests, and generator-only values.
- Put preprocessing and LogisticRegression in one sklearn Pipeline, with every estimator parameter
  explicit in versioned config. Wrap that entire pipeline in `CalibratedClassifierCV` using
  `StratifiedKFold(n_splits=5, shuffle=True, random_state=calibration_seed)`, `method="sigmoid"`, and
  `ensemble=True`; all folds contain training rows only.
- No oversampling/balanced weights unless measured evidence justifies their probability impact.
- Select `decision = score >= threshold` on validation only over integer thousandths `0/1000`
  through `1000/1000`. Minimize `10 × FN + 1 × FP`; ties choose fewer FN, then fewer FP, then the
  lowest remaining threshold. Lock threshold before the test is evaluated once.
- Primary ranking metric is `average_precision`, compared with prevalence and
  `ap_lift = average_precision / prevalence`. Also report ROC-AUC, Brier, log loss, confusion
  metrics/rates, synthetic cost, and `synthetic_cost_per_event = (10*FN + FP)/N`. Reliability bins
  are `[0.0,0.1), ... [0.8,0.9), [0.9,1.0]` and store count/mean score/observed prevalence. Empty or
  zero-denominator results serialize as JSON `null` with numerator, denominator, and reason—never
  NaN/Infinity. Namespace validation threshold-selection evidence separately; public headline
  evaluation metrics are the once-per-training-invocation held-out-test results after threshold
  lock, not training metrics.

## Required artifacts
- Dataset/config/quality manifests and persisted split assignments.
- MLflow local `file:` tracking only; explicit params, metrics, tags, plots, and artifacts—no autolog.
- Training-only baseline: fixed decile bins with duplicate edges collapsed, raw
  proportions/counts, missingness, constant flags, and categorical universe plus `__OTHER__` and
  `__MISSING__`. Outer numeric bins are represented by explicit underflow/overflow semantics, not
  JSON Infinity. After threshold lock, score the training reference with the final deployed model
  solely to freeze calibrated score bins/counts/proportions and locked-decision counts/proportions;
  these are distribution references, never training-performance evidence.
- Exact seven-file immutable bundle from `ARCHITECTURE.md`. Build in a temporary sibling, refuse an
  existing version, and checksum every payload except `checksums.sha256` itself.
- Manifest includes dataset/config/split/schema/baseline/source-tree/`uv.lock` hashes, all seeds and
  parameters, MLflow run ID, Python/sklearn versions, and Git SHA/dirty state when available. Every
  canonical hash records algorithm/canonicalization version, sorted path or ID ordering, and explicit
  exclusions so order changes do not alter identity. Bundle identity is `{model_version,
  manifest_sha256}`; later publishers must preserve it without overwrite.

## Verification order
Reject symlinks/missing/extra files → validate checksum-file syntax and byte hashes → parse strict
JSON contracts → cross-check identities/feature order/split hashes → only then load trusted-origin
joblib → run one schema-valid smoke prediction. Checksums prove corruption detection, not model
authenticity.

## Mandatory tests
- Generator determinism/prefix stability, seed change, stable unique IDs, no latent columns.
- Quality rejects duplicate/missing/non-finite/extra/leaky/out-of-domain/single-class data.
- Split is deterministic, stratified, disjoint, exhaustive; hash mismatch blocks training.
- Fit sees training IDs only; changing validation/test cannot change fitted model; changing test
  cannot change validation score/threshold; test prediction happens only after threshold lock.
- Known-vector threshold/metric/reliability tests; baseline train-only/constant-bin tests.
- Exact calibration-fold/method/ensemble, threshold-grid/tie, null-serialization, AP-lift, and
  test-reference synthetic-cost tests.
- Bundle overwrite/partial cleanup, each-file corruption, recomputed-checksum cross-file mismatch,
  verify-before-joblib-load, and reloaded prediction parity.
- MLflow content and end-to-end generate → train → inspect → verify CLI tests.

## Constraints
No XGBoost/cloud upload/automatic retraining/promotion. No training-set claims, JSON NaN/Infinity,
or threshold tuning to make the demo look better.

## Validation
```bash
make train
uv run pytest tests/unit tests/integration -q
make verify
```
Prove a valid bundle verifies and a changed payload fails before deserialization.

## Definition of done
A clean local command creates the audited dataset/split, one MLflow run, verified immutable bundle,
baseline, model/data cards, and stable tests. Update checklist, evidence, and `reports/phase-02.md`.

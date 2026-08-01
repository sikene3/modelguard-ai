# Phase 02 Checklist

- [x] Deterministic/prefix-stable generator; no latent columns
- [x] Strict schema/data-quality validation
- [x] Persisted split is deterministic, disjoint, exhaustive, stratified, and hashed
- [x] Feature allowlist excludes ID/label/split/leakage fields
- [x] Full sklearn Pipeline is wrapped by train-only cross-fitted calibration
- [x] Explicit five-fold/sigmoid/ensemble calibration; no library-default semantics
- [x] Exact validation grid/tie policy; locked threshold; test evaluated once afterward
- [x] AP vs prevalence/lift, ROC-AUC, Brier/log-loss/reliability/confusion metrics
- [x] Null/zero-denominator conventions and held-out synthetic-cost-per-event reference
- [x] Local MLflow params/metrics/tags/plots/artifacts
- [x] Training-only versioned baseline profile
- [x] Training-reference prediction-score and locked-decision distribution baselines
- [x] Immutable seven-file bundle and full lineage
- [x] Canonical hash algorithms/ordering/exclusions and version+manifest durable identity
- [x] Verify hashes/contracts before trusted joblib load
- [x] Corruption/cross-file mismatch/overwrite/partial-cleanup tests
- [x] Reloaded predictions match in-memory predictions
- [x] Model/data cards, evidence, and phase report

## Evidence
- Commands: `make train`, `make inspect-model`, `make verify-model`,
  `uv run pytest tests/unit tests/integration -q`, and `make verify`; exact outputs are in
  `reports/phase-02.md`.
- Test results: 54 full-suite tests passed with 84.87% coverage; the required unit/integration subset
  passed 52 tests. Ruff, strict Mypy, Bandit, live hashed-lock pip-audit, secret/file checks, and
  trusted bundle verification passed.
- Artifact paths/hashes: `artifacts/model-bundles/1.0.0/`, manifest SHA-256
  `49cbe04bc4285fc71463d0071e3babc3a5f5c20011541a072b4844bb5c78afd9`; dataset and
  split identities are recorded in `reports/phase-02.md`.
- Commit: Not created automatically; suggested
  `feat: add audited Phase 02 training and immutable bundle`.
- Residual risks: no Git commit/HEAD is available; joblib still requires trusted provenance; model
  evidence is limited to the synthetic generator and locked demo cost policy.

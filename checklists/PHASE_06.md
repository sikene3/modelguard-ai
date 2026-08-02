# Phase 06 Checklist

- [x] Separate run/data-quality/drift/performance status and freshness
- [x] Active model identity is distinct from report target identity
- [x] Accepted target volume and exact reconciled count buckets
- [x] Top drifting features
- [x] Distribution charts
- [x] Stale/missing handling
- [x] Local repository tests
- [x] App smoke test

## Evidence

- Commands: focused Phase 06 tests; `uv run pytest tests/unit tests/smoke -q`; `make verify`;
  `uv lock --check --offline`; live healthy/degraded `make dashboard` runs; real-browser desktop and
  responsive checks; manifest, Arabic-character, syntax, disposable-file, and future-scope scans.
- Test results: focused dashboard `13 passed`; required unit/smoke `158 passed`, 76.05% coverage;
  full suite `184 passed`, 84.71% coverage; Ruff, strict Mypy, Bandit, pip-audit, secret scan,
  trusted-bundle verification, live health, and browser checks passed.
- Artifact paths: `artifacts/phase-06-validation/{healthy,degraded}/reports/` (ignored) and
  `reports/evidence/phase-06/{healthy-dashboard,degraded-dashboard}.png` with hashes recorded in
  `reports/evidence/phase-06/README.md`.
- Commit: none; agents do not commit automatically.
- Residual risks: screenshots prove local synthetic scenarios only; S3 deployment, IAM, networking,
  object lifecycle, and run-status writing remain Phase 08 scope.

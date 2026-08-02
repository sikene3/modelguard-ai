# Phase 07 Checklist

- [x] Non-root images
- [x] Health checks
- [x] Compose starts
- [x] Local smoke passes
- [x] Healthy-to-drift demo passes
- [x] Trivy run
- [x] No secrets/model artifacts baked in

## Evidence

- Commands: image build and exact Compose `up --build`; smoke, demo, E2E, Trivy, live headless
  Chrome, ShellCheck, image/runtime hardening inspection, focused regressions, `make verify`, offline
  lock, manifest, language, syntax, secret, and future-scope gates. Exact commands and results are in
  `reports/phase-07.md`.
- Test results: focused Phase 07 `14 passed`; affected Phase 04/07 regression set `26 passed`; full
  suite `199 passed` at 84.74% branch coverage. Ruff, strict Mypy, Bandit, strict hashed
  `pip-audit`, the secret scan, trusted-bundle verification, Bash syntax, and ShellCheck 0.11.0 all
  passed.
- Runtime evidence: smoke run `smoke-20260802t194142z-91810` persisted 601 events and produced
  `succeeded/valid/healthy/unknown`; demo run `demo-20260802t194241z-94190` proved Healthy to
  Drifted; E2E run `e2e-20260802t194449z-98262` passed insufficient-data, corrupt-bundle, and
  sink-outage scenarios.
- Security evidence: Trivy 0.72.0 with the 2026-08-02 database reported zero critical findings and
  zero exceptions in all three images. Numeric UID/GID, read-only roots, dropped capabilities,
  loopback ports, stripped setuid/setgid files, role imports, and absence of build/dev tooling were
  inspected on the final images.
- Artifact paths: ignored `artifacts/phase-07-evidence/build/images.json`,
  `artifacts/phase-07-evidence/trivy-20260802T200112Z/summary.json`, and the three run-specific
  summary paths above.
- Commit: none; agents do not commit automatically.
- Residual risks: evidence is host- and time-bound; the dirty-worktree image revision must be rebuilt
  from the reviewed commit for any later release. This local synthetic demo does not claim
  production readiness or AWS deployment.

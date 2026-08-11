# Phase 11 Checklist

- [x] Healthy demo uses explicit window/as-of and accepted-sample headroom
- [x] Drifted demo uses a separate explicit non-overlapping window
- [x] Dashboard transition
- [x] Four dimensions shown; unlabeled performance remains unknown
- [x] Active and report-target model identities are distinguished
- [x] Incident JSON/HTML
- [x] Alert evidence
- [x] Recovery evidence
- [x] Demo runbook
- [x] Screenshots/video paths
- [x] Teardown

## Evidence

- Commands: `make phase11-demo-local` twice with fixed anchor `2026-08-11T19:46:00Z`;
  `make phase11-compare-local`; `make phase11-verify-teardown` for both summaries; focused/full
  Pytest, Ruff, Mypy, model verification, Bandit, ShellCheck, secret check, and `git diff --check`.
- Test results: both demos, deterministic comparison, and teardown checks passed; 6 focused tests
  passed; final unrestricted `make test` passed all 590 tests at 83.56% branch coverage, including
  the unchanged 25 requests/second performance gate. Ruff, Mypy, Bandit, pip-audit, Actionlint,
  ShellCheck, fresh Checkov, Gitleaks, Trivy filesystem/configuration, the basic secret/file check,
  and `git diff --check` passed. `uv lock --check` passed for 128 packages. The lock-digest focused
  regression tests passed after rebinding the three Dockerfiles and Compose default to `uv.lock`.
- Artifact paths: `artifacts/phase-11-evidence/phase11-final-local-03/`,
  `artifacts/phase-11-evidence/phase11-final-local-04/`,
  `artifacts/phase-11-evidence/local-repeatability.json`, `reports/evidence/phase-11/`, and
  `reports/phase-11.md`.
- Commit: recorded by the commit containing this checklist with message
  `feat: add repeatable Phase 11 monitoring recovery demo`.
- Residual risks: no fresh live-browser or Phase 11 SNS/CloudWatch evidence in the local-only run;
  performance remains unknown without labels; AWS teardown was not live-reverified. No local release
  gate remains unresolved.

# Phase 05 Checklist

- [x] PSI/JS-distance reference vectors, zero bins, constants, empty/non-finite cases
- [x] UTC half-open window, grace, and explicit-time tests
- [x] Frozen snapshot and finalization grace do not claim row-level delivery lateness
- [x] Raw/rejected/outside-window/known-non-target/duplicate/accepted-target counts reconcile
- [x] Identical/conflicting duplicates and input-order determinism tested
- [x] Explicit target identity; known non-target excluded/warns; unknown/conflicting identity invalid
- [x] Baseline identity derives from verified bundle; monitor config is a run-level hash
- [x] Independent run/data-quality/drift/performance states and precedence
- [x] Stationary repeated windows stay healthy; shifted fixtures degrade
- [x] Tiny data is insufficient/unknown, never healthy
- [x] Delayed-label coverage/orphans/conflicts/adequacy/performance tests
- [x] Locked synthetic-cost delta state boundaries and labeled-subset wording tested
- [x] Canonical report ID, JSON contract, escaped deterministic HTML
- [x] Report ID survives reorder/repartition/unrelated append; latest is atomic and monotonic
- [x] Repeat/restart/concurrent conditional alert dedupe without exactly-once claim
- [x] Bounded/redacted EMF completion/count/freshness record
- [x] No drift-as-accuracy claim
- [x] Evidence directory and phase report updated

## Evidence

- Commands: dedicated independent review of all 39 paths; explicit baseline/drifted fixture and
  monitor commands; exact shifted rerun; explicit stale status; focused Phase 05 and affected
  Phase 03/04 regressions; required unit/integration suite; full `make verify`; schema export;
  offline lock, secret, model, whitespace, manifest, scope, and language checks. See
  `reports/phase-05.md`.
- Test results: focused Phase 05 suite `61 passed`; required suite `162 passed`, no warnings,
  `85.87%` coverage; final full repository suite `171 passed`, `86.08%` coverage; Ruff, strict Mypy,
  Bandit, strict hashed `pip-audit`, secret scan, schema reproduction, trusted bundle verification,
  and all 47 affected Phase 03/04 API/event regressions passed.
- Artifact paths/hashes: indexed in `reports/evidence/phase-05/README.md`; baseline report
  `ba471dc6...` is healthy, shifted report `682cf4af...` is degraded, and their exact JSON/HTML
  SHA-256 values are recorded there.
- Commit: authorized by an explicit dedicated independent-review request with message
  `feat: add deterministic Phase 05 monitoring and reports`; the resulting hash is recorded in Git
  history.
- Residual risks: AWS paths remain injected/mock-tested until the infrastructure phases;
  conditional alerts explicitly do not guarantee exactly-once delivery; partial-label selection
  bias remains disclosed.

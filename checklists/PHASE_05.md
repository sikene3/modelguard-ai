# Phase 05 Checklist

- [ ] PSI/JS-distance reference vectors, zero bins, constants, empty/non-finite cases
- [ ] UTC half-open window, grace, and explicit-time tests
- [ ] Frozen snapshot and finalization grace do not claim row-level delivery lateness
- [ ] Raw/rejected/outside-window/known-non-target/duplicate/accepted-target counts reconcile
- [ ] Identical/conflicting duplicates and input-order determinism tested
- [ ] Explicit target identity; known non-target excluded/warns; unknown/conflicting identity invalid
- [ ] Baseline identity derives from verified bundle; monitor config is a run-level hash
- [ ] Independent run/data-quality/drift/performance states and precedence
- [ ] Stationary repeated windows stay healthy; shifted fixtures degrade
- [ ] Tiny data is insufficient/unknown, never healthy
- [ ] Delayed-label coverage/orphans/conflicts/adequacy/performance tests
- [ ] Locked synthetic-cost delta state boundaries and labeled-subset wording tested
- [ ] Canonical report ID, JSON contract, escaped deterministic HTML
- [ ] Report ID survives reorder/repartition/unrelated append; latest is atomic and monotonic
- [ ] Repeat/restart/concurrent conditional alert dedupe without exactly-once claim
- [ ] Bounded/redacted EMF completion/count/freshness record
- [ ] No drift-as-accuracy claim
- [ ] Evidence directory and phase report updated

## Evidence
- Commands:
- Test results:
- Artifact paths/hashes:
- Commit:
- Residual risks:

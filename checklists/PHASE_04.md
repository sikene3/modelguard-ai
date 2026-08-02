# Phase 04 Checklist

- [x] Versioned event schema
- [x] Retry-stable event/request IDs, UTC timestamp, and exact model/manifest/input-schema identity
- [x] Local sink
- [x] Firehose sink with fake client
- [x] Failure does not fail prediction
- [x] Producer acceptance/failure is not mislabeled as Firehose/S3 delivery
- [x] Atomic single-writer local JSONL and frozen/closed-window read contract
- [x] JSONL newline/GZIP/physical date-hour Firehose contract; model identity is payload-only
- [x] Bounded timeout/retry and downstream freshness signals
- [x] No sensitive fields

## Evidence

- Commands: dedicated review of all 29 paths; 37 focused event/API tests; the 108-test required
  unit/contract/integration gate; `make verify`; model inspection and trusted verification; offline
  lock, shell/JSON, manifest, Arabic, secret, scope, staged-file, and diff checks; literal local
  Uvicorn/TCP multi-request smoke.
- Test results: the authorized human-review gate repeated 37 focused tests, 108 required tests, and
  all 110 repository tests with 85.78% branch coverage; Ruff, strict Mypy, Bandit, hashed
  `pip-audit`, and the secret scan passed.
- Artifact paths: `contracts/prediction-event-v1.schema.json`,
  `docs/PREDICTION_EVENT_CONTRACT.md`, and `reports/phase-04.md`; local smoke JSONL was validated in
  an isolated temporary directory and removed.
- Commit: authorized by an explicit dedicated human-review request with message
  `feat: add versioned Phase 04 prediction event logging`; the resulting hash is recorded in Git
  history.
- Residual risks: the Firehose resource, physical GZIP S3 delivery, and downstream delivery/freshness
  signals remain intentionally deferred; a response-loss retry can create a stable-ID duplicate.

# Phase 04 Report

## Objective

Construct one privacy-safe, versioned event for every successful prediction and route it through a
configurable local, AWS Firehose, or disabled sink, while keeping prediction success independent
from sink availability and preserving precise producer-versus-delivery telemetry semantics.

## Scope completed

- Added the strict, frozen `modelguard.prediction-event.v1` Pydantic v2 contract plus a portable
  committed JSON Schema and compatibility fixture. It contains a server-generated event UUID,
  server request UUID, UTC event timestamp, exact model version/manifest digest/input-schema
  version, the nine approved synthetic features, score, decision, and non-negative scoring latency.
  Missing version identity, extra fields, non-finite values, invalid types/domains, noncanonical
  timestamp text, and sensitive fields are rejected.
- Added one event-construction boundary that generates the event UUID and canonical newline-JSON
  bytes once after successful scoring. Sinks receive only that immutable record. A repeated request
  creates a new event, while Firehose retries reuse the same bytes and event ID so ambiguous
  at-least-once duplicates remain deduplicable.
- Added `local | aws | disabled` settings. AWS application mode rejects local event persistence;
  `EVENT_SINK=aws` requires a stream name. Firehose connect/read timeouts, maximum attempts, and
  exponential retry base delay are bounded and typed.
- Replaced the Phase 03 no-op default with a local JSONL sink. Each sink creates a unique mode-0600
  `*.jsonl.open` file, owns its only writer, serializes appends through one worker, issues one
  `O_APPEND` write and `fsync` per accepted record, and never retries an ambiguous local append.
- Added safe local rotation: sync/close first, atomically publish a non-overwriting hard link under
  `*.jsonl`, then remove the active name. The sink never reopens a closed file. The frozen snapshot
  helper returns only a sorted enumeration of closed `.jsonl` files and never exposes active
  `.open` files.
- Added a Firehose sink using an injected minimal boto3-client protocol. Application retries are
  limited to explicit transient service and transport failures; hidden botocore retries are disabled
  by client configuration. Uninjected client construction is lazy inside the first fail-open write,
  so application construction/readiness does no credential or producer work. A non-empty `RecordId`
  means producer acceptance only.
- Added a one-operation worker gate. A request whose event deadline expires now returns promptly;
  the underlying thread may finish its ambiguous operation, but later writes fail fast instead of
  growing an unbounded executor queue. Bounded shutdown waits for that sole operation.
- Froze the later Firehose physical contract as newline JSON, `GZIP`, and physical UTC arrival-time
  `predictions/year=.../month=.../day=.../hour=.../` prefixes. Full model identity remains in the
  payload and dynamic model partitioning is deferred.
- Integrated event creation/writing into the API after successful scoring. Response and event share
  one frozen scoring latency; event creation and sink latency are outside that value. Serialization,
  local persistence, Firehose production, timeout, disabled-drop, and unexpected sink failures all
  fail open and are separately logged/counted.
- Extended Phase 03 Prometheus/EMF telemetry with fixed low-cardinality outcomes:
  `local_persisted`, `firehose_accepted`, `disabled_dropped`, `timeout`, `local_failed`,
  `firehose_producer_failed`, and `serialization_failed`. AWS failures also emit the existing
  `ErrorKind.EVENT_SINK` boundary. No success path uses delivered/S3 wording.
- Documented separate API producer acknowledgement, native Firehose delivery, and S3-prefix
  freshness boundaries. Phase 05 must enumerate physical arrival-hour overlap through grace,
  freeze its snapshot, and filter the authoritative payload timestamp to `[start,end)`.
- Added fake-client, schema compatibility, local concurrency/rotation, privacy, timeout, retry-byte
  stability, AWS EMF, fail-open API, and multi-request local integration coverage. No live AWS call,
  Terraform resource, monitor implementation, S3-per-event write, Parquet, or future phase feature
  was added.

## Files changed

- Event implementation: `src/modelguard/inference/events.py` and the verified bundle identity
  accessor in `src/modelguard/inference/predictor.py`.
- API integration: `src/modelguard/api/{main,dependencies,routes}.py`.
- Runtime configuration/telemetry: `src/modelguard/core/{config,telemetry}.py` and `.env.example`.
- Contract artifacts: `contracts/prediction-event-v1.schema.json` and
  `tests/fixtures/contracts/prediction-event-v1.json`.
- New Phase 04 tests: `tests/unit/test_prediction_events_phase04.py`,
  `tests/contract/test_prediction_event_contract_phase04.py`, and
  `tests/integration/test_prediction_logging_phase04.py`; Phase 03 settings/telemetry/API fixtures
  were updated for the now-explicit disabled/local modes.
- Documentation: `ARCHITECTURE.md`, `docs/PREDICTION_EVENT_CONTRACT.md`, ADR-003,
  README/getting-started/command files, acceptance/checklist/status/manifest records, and this
  report.

## Commands and evidence

```text
UV_CACHE_DIR=.cache/uv uv run pytest \
  tests/unit/test_prediction_events_phase04.py \
  tests/contract/test_prediction_event_contract_phase04.py -q --no-cov
PASS — 13 final focused schema, privacy, size, local writer/snapshot, timeout/backpressure,
retry-stability, fake Firehose, lazy bounded-client, and physical-contract tests.

UV_CACHE_DIR=.cache/uv uv run pytest \
  tests/integration/test_prediction_logging_phase04.py -q --no-cov
PASS — 2 local and AWS API integrations; local records were closed/parsed and producer acceptance
and failure produced separate Prometheus, EMF, and log semantics while both responses stayed 200.

UV_CACHE_DIR=.cache/uv uv run pytest <focused Phase 04 plus affected Phase 03 API files> -q --no-cov
PASS — 21 tests after the independent schema-version, canonical-UTC, hard-timeout, bounded-queue,
and standard inference-future repairs.

UV_CACHE_DIR=.cache/uv uv run pytest tests/unit tests/contract tests/integration -q
PASS — final source: 108 tests in 9.96 seconds with 85.78% total branch coverage.

make verify
PASS — Ruff format/lint checked 120 files; strict Mypy passed 36 source files; all 110 repository
tests passed with 85.78% branch coverage; Bandit reported no findings; strict hashed `pip-audit`
reported no known vulnerabilities; the defense-in-depth secret/file check passed; and the trusted
bundle verified with exact identity and smoke score.

APP_ENV=local EVENT_SINK=local LOCAL_EVENT_DIR=/tmp/modelguard-phase04-live.<random>/events \
  make api API_PORT=18085
PASS — literal loopback Uvicorn loaded the exact version 1.0.0 bundle and served live/ready/version,
five real TCP predictions, and metrics. Every prediction returned 200 with a distinct request ID;
the local-persisted metric reached five. While running there was one active `.open` file and no
closed input. SIGINT completed graceful shutdown and published one mode-0600 closed file containing
exactly five newline-terminated, schema-valid `Z`-timestamp events with five distinct event IDs and
the exact manifest digest. The temporary directory was removed after validation.

UV_CACHE_DIR=.cache/uv uv run bandit -q -r src
PASS — no Bandit findings.

./scripts/check_no_secrets.sh
PASS — defense-in-depth repository secret/file scan.

UV_CACHE_DIR=.cache/uv uv lock --check --offline
PASS — all 159 locked packages resolved offline with no lock change.

make verify-model
PASS — trusted bundle version 1.0.0, exact manifest SHA-256
49cbe04bc4285fc71463d0071e3babc3a5f5c20011541a072b4844bb5c78afd9, and smoke score
0.9981110662188358.

git diff --check
PASS — no whitespace errors.

make inspect-model; uv lock --check --offline; bash -n; JSON/manifest/Arabic scans
PASS — metadata inspection did not deserialize the model; 159 packages resolved offline; shell and
JSON syntax, exact sorted manifest parity, English-only content/filenames, unchanged Phase 03 HEAD,
and Phase 04 boundary checks passed.
```

The first direct `uv run pytest` baseline attempt used the read-only host uv cache; all recorded
commands above use the repository's writable `.cache/uv`, matching the Makefile convention.

## Tests

- Unit: required schema identity, canonical `Z` UTC serialization, privacy/size rules; local unique active file, single-writer
  concurrency, one-newline appends, `0600` permissions, rotation, closed snapshot, and parsing;
  Firehose retry byte identity, retry classification, bounded attempts/delays, fake client, client
  timeout configuration, sink modes, and ownership-aware close.
- Contract: frozen v1 example round trip; committed JSON Schema/runtime field parity; exact API,
  Phase 02, and event feature parity; unknown/sensitive-field rejection; newline/GZIP/UTC physical
  prefix; model identity in payload only.
- Integration: five independent local predictions produce five request-correlated unique events;
  response/event score, decision, identity, features, and latency match; active files are invisible
  until shutdown; Firehose acceptance/failure remain separate, fail open, and emit bounded AWS EMF.
- Regression/load: all prior unit, contract, integration, load, and smoke tests pass. The existing
  100-request concurrency-4 load gate remains within its required throughput/error/p95 assertions
  with local `fsync` event persistence enabled.

## Generated artifacts

- Versioned portable schema: `contracts/prediction-event-v1.schema.json`.
- Frozen compatibility event: `tests/fixtures/contracts/prediction-event-v1.json`.
- Detailed contract: `docs/PREDICTION_EVENT_CONTRACT.md`.
- Local smoke JSONL was generated under isolated ignored/temporary directories, fully parsed, and
  removed after evidence capture; no prediction-event output is a commit candidate.
- Existing immutable bundle: `artifacts/model-bundles/1.0.0/` with identity above.

## Decisions/assumptions

- `latency_ms` means scoring-path latency through model result creation. It is frozen before event
  serialization/sink work and copied unchanged to the response and event, so sink slowness cannot
  distort the inference measurement.
- `event_timestamp` is captured after successful scoring and before producer work. Firehose physical
  prefixes are based on UTC arrival time, not this event time.
- Local `fsync` is required before `local_persisted` is recorded. The sink does not retry an
  ambiguous append. A process crash can leave a synced `.jsonl.open` recovery candidate, but Phase
  05 must not read it as a finalized monitoring input.
- Firehose producer semantics are at least once. Stable event IDs enable later deduplication; the
  service does not claim exactly-once producer or S3 delivery.
- The API owns one model and one sink per process. The current local command uses one Uvicorn worker;
  any later multi-process deployment gets one unique event file per process rather than sharing a
  writer/file.
- Input values are synthetic by project contract. Only the nine approved fields are persisted, with
  strict bounds/domains identical to the API and Phase 02 schema.

## Residual risks

- No Firehose stream, GZIP S3 object, physical prefix, native delivery metric, or S3 freshness alarm
  exists yet; those are documented/tested contracts for Phases 05 and 08, not deployment claims.
- A local crash can leave an active `.open` file. It is safely excluded from monitoring, but a future
  operator recovery/rotation procedure may be useful if local crash recovery becomes a requirement.
- Firehose response loss after service acceptance can still produce a duplicate on retry. Phase 05
  must deduplicate by stable event ID exactly as the architecture requires.
- Python cannot force-terminate a permanently stuck OS/SDK worker thread. The request deadline and
  one-operation gate keep request latency and queue growth bounded; graceful shutdown and the later
  process/container supervisor remain the hard-stop boundary.

## Acceptance checklist status

All Phase 04 functional checklist and event-logging acceptance items are implemented and tested.
The required Python gate, complete `make verify`, live dependency audit, static/security checks,
trusted bundle verification, exact manifest/language checks, and literal TCP multi-request local
event evidence pass with no unexplained failure.

## Phase decision

**GO for Phase 05 after the authorized Phase 04 commit.** The dedicated human-review gate below is
complete, no unexplained Phase 04 failure remains, and no Phase 05 monitor, Docker, Terraform
resource, workflow, live AWS call, or infrastructure implementation was started.

## Dedicated pre-commit human-review gate

- Completely reviewed all 22 modified and 7 new files against `PROJECT_SPEC.md`,
  `ARCHITECTURE.md`, `ACCEPTANCE_CRITERIA.md`, the Phase 04 prompt, this report, and the Phase 04
  checklist.
- Confirmed all 29 paths are Phase 04 event-contract, producer, API integration, configuration,
  telemetry, test, documentation, or evidence files. No Phase 05 monitoring, Docker, Terraform,
  GitHub workflow, AWS infrastructure, live AWS resource, or unrelated dependency-lock change is
  present.
- Confirmed the strict runtime and portable schemas require the exact v1 identity and canonical UTC
  `Z` timestamp; only the nine approved synthetic features are accepted; exact verified model
  identity is recorded; and the frozen event computes its bounded canonical serialization once.
- Confirmed the local sink owns one mode-0600 append-only writer, submits one complete newline
  record per `O_APPEND` write, calls `fsync`, publishes closed files without replacement, excludes
  active files from frozen snapshots, and drains its sole bounded worker during graceful shutdown.
- Confirmed the Firehose client is dependency-injected or created lazily on first use, has explicit
  connect/read and application-retry bounds, reuses identical bytes across retries, and labels a
  non-empty `RecordId` only as producer acceptance. Newline JSON, later GZIP delivery, and physical
  UTC arrival-hour prefix semantics remain separate frozen contracts.
- Confirmed local, AWS, and disabled modes are explicit; request deadlines and one-operation gates
  bound latency and queue growth; and serialization, timeout, local-write, disabled-drop, Firehose,
  and unexpected sink failures remain observable without changing a successful prediction.
- Repeated the affected Phase 03/04 test set: 37 passed in 1.77 seconds. Repeated the required
  unit/contract/integration suite: 108 passed in 10.24 seconds with 85.78% branch coverage.
- Repeated `make verify`: Ruff checked 120 files, strict Mypy passed 36 source files, all 110 tests
  passed in 10.11 seconds with 85.78% branch coverage, Bandit reported no findings, strict hashed
  `pip-audit` reported no known vulnerabilities, the secret/file gate passed, and the exact trusted
  bundle verified.
- Repeated metadata-only model inspection, trusted-model verification, and the offline 159-package
  lock check. The model identity remained version 1.0.0 with manifest
  `49cbe04bc4285fc71463d0071e3babc3a5f5c20011541a072b4844bb5c78afd9`.
- Repeated literal loopback Uvicorn/TCP health, readiness, version, metrics, and five-prediction
  checks. Every response was 200; five unique request/event IDs were persisted; the metric reached
  five; and graceful shutdown produced one mode-0600, five-line, schema-valid closed file with exact
  identity, canonical `Z` timestamps, and no active file. Live log-redaction checks passed.
- Repeated exact manifest parity, JSON and shell syntax, diff-whitespace, secret, scope, staged-file,
  and Arabic content/filename scans. All passed with zero Arabic findings and no prohibited path.
- Confirmed only ignored local `.venv`, canonical Phase 02 generated artifacts, and the local MLflow
  store are retained outside the commit candidates. Disposable caches, coverage, bytecode, smoke
  files, temporary evidence, and runner logs are removed before staging.

## Suggested commit message

`feat: add versioned Phase 04 prediction event logging`

## Next manual action

After committing the reviewed Phase 04 files, wait for an explicit Phase 05 instruction. Do not
push or start Phase 05 as part of this gate.

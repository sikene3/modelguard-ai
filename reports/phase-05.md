# Phase 05 Report

## Objective

Implement deterministic monitoring that keeps run health, input data quality, distribution drift,
and delayed label-backed performance independent, while producing reproducible reports and
transition evidence without retraining, promotion, live cloud calls, or accuracy claims from drift.

## Scope completed

- Added explicit UTC event-time half-open windows with a one-hour default, ten-minute finalization
  grace, two-hour stale threshold, canonical test/CLI times, and no row-level delivery-lateness
  claim. Local JSONL/GZIP inputs are enumerated and copied before analysis; injected AWS helpers pin
  enumerated S3 inputs by VersionId or ETag.
- Added exact run-level target identity for event schema, model version, manifest digest, and input
  schema. The selected bundle is checksum/contract verified even for historical windows, baseline
  lineage comes from that manifest, known non-target identities come from verified bundles, and the
  effective monitoring configuration is canonically hashed once.
- Implemented exclusive parse/schema, outside-window, known-non-target, duplicate, and accepted
  classifications. Target duplicates are input-order independent; identical groups accept one,
  conflicting event-ID groups reject every member, and the strict report contract reconciles every
  raw row exactly.
- Implemented transparent frozen-bin numeric/prediction PSI with natural logs and base-2
  Jensen-Shannon distance for categorical/decision signals. Both use the exact `1e-6` smoothing
  formula. Constant, empty, non-finite, threshold-boundary, special-bucket, and missingness behavior
  is explicit; KS is omitted.
- Implemented the four independent state machines and exact precedence. Invalid or insufficient
  quality forces drift unknown; outside-window rows alone do not warn; required unevaluable signals
  prevent a healthy drift claim. Persistent run status represents never-run, current failure,
  successful, and stale independently of immutable successful reports.
- Added strict `modelguard.label.v1` delayed labels, canonical identical/conflicting deduplication,
  orphan/missing/coverage counts, exact adequacy boundaries, and metrics only for adequate labels.
  Only locked-threshold synthetic cost per event minus the Phase 02 held-out reference votes on
  performance. All presentation says “synthetic-policy cost on the labeled subset versus held-out
  synthetic reference” and discloses partial-label selection bias.
- Added canonical report IDs over all semantic inputs, including the sorted known-model registry
  and label-source presence so empty inputs cannot collide. IDs ignore enumeration order, names,
  partitions, enclosing-file hashes, and post-grace invocation time. JSON history is strict and
  create-only; local HTML is escaped/offline; exact reruns are byte-stable.
- Added process-safe local monotonic latest writes, atomic complete-file publication, persistent
  conditional transition markers, bounded alert outcomes, and concurrent/restart deduplication.
  AWS storage equivalents use create-only and conditional S3 operations. Alerts are limited to
  successful-run entry into data-quality invalid, drift degraded, or performance degraded; no
  exactly-once SNS claim is made.
- Added one low-cardinality AWS EMF completion/count/freshness record with only `Service` and
  `Environment` dimensions. It carries no identities, features, secrets, or delivery-lateness
  metric.
- Added a deterministic fixture generator, CLI/status commands, committed monitoring policy,
  portable JSON Schema exporter, detailed contract documentation, Make targets, and unit,
  integration, contract, fake-AWS, persistence, and restart tests.
- Tightened three contracts during independent reviews: rows that fail strict event-schema
  validation and schema-valid rows outside the half-open window no longer advance to identity
  classification, and configuration-validation failures now persist a failed run attempt instead
  of escaping before run-state recording. All three repairs have dedicated regression tests.
- Repaired the existing Phase 03/04 thread-future boundary exposed by the expanded native-model test
  lifecycle. Inference and serial event workers now inspect the thread-safe future from the event
  loop with bounded asynchronous polling, preserving cancellation/backpressure while avoiding a
  cross-thread event-loop wakeup hang. All earlier API/event tests remain green.

## Files changed

- Monitoring core: `src/modelguard/monitoring/{config,state,events,drift,performance,report,
  persistence,telemetry,service,cli,aws}.py` and package exports.
- Reproducible inputs/contracts: `configs/phase-05-monitoring.json`,
  `contracts/monitoring-report-v1.schema.json`,
  `scripts/generate_monitoring_fixture.py`, and `scripts/export_monitoring_report_schema.py`.
- Tests: five Phase 05 unit modules, two integration modules, one contract module, and shared
  verified-bundle/event fixtures in `tests/conftest.py`.
- Bounded regression repair: `src/modelguard/api/dependencies.py` and
  `src/modelguard/inference/events.py`.
- Documentation/build/evidence: Makefile, README/getting-started/command/event-contract docs,
  `docs/MONITORING_CONTRACT.md`, acceptance/checklist/status/manifest records, the committed evidence
  index, and this report.

## Commands and evidence

```text
UV_CACHE_DIR=.cache/uv uv run python scripts/generate_monitoring_fixture.py \
  --scenario baseline --window-end 2026-01-01T01:00:00Z \
  --event-dir artifacts/phase-05-validation/predictions
UV_CACHE_DIR=.cache/uv uv run python -m modelguard.monitoring.cli run \
  --window-end 2026-01-01T01:00:00Z --as-of 2026-01-01T01:10:00Z \
  --event-dir artifacts/phase-05-validation/predictions \
  --report-dir artifacts/phase-05-validation/reports
PASS — 1,000 accepted target events; data quality valid, drift healthy, performance unknown, run
succeeded. Report ID ba471dc62fc66f644a0f38ca2631168b5d4ce8c8c0753094927c69c9d83396b4.

UV_CACHE_DIR=.cache/uv uv run python scripts/generate_monitoring_fixture.py \
  --scenario drifted --window-end 2026-01-01T02:00:00Z \
  --event-dir artifacts/phase-05-validation/predictions
UV_CACHE_DIR=.cache/uv uv run python -m modelguard.monitoring.cli run \
  --window-end 2026-01-01T02:00:00Z --as-of 2026-01-01T02:10:00Z \
  --event-dir artifacts/phase-05-validation/predictions \
  --report-dir artifacts/phase-05-validation/reports
PASS — 1,000 accepted target events plus 1,000 exclusively outside-window rows; data quality valid,
drift degraded, performance unknown, run succeeded. Report ID
682cf4afea30b8aad75d37e3ab7123f3a2ede29099e1e60720a1269163dfdb6d.

Repeat the exact shifted-window monitor command above
PASS — same report ID, JSON SHA-256
60fdb7f589b2d708226b4157aeba744ad06357a3dabfd9634125f643448e753f, HTML SHA-256
6552398fea7f5619c6c1d3e1e920b7059e32a3032fd63c4d1ab2fd3a68fbe62f, and
latest_updated=false.

UV_CACHE_DIR=.cache/uv uv run python -m modelguard.monitoring.cli status \
  --as-of 2026-01-01T04:10:00Z \
  --report-dir artifacts/phase-05-validation/reports
PASS — run_state=stale at the exact two-hour threshold from the latest success.

UV_CACHE_DIR=.cache/uv uv run pytest tests/unit tests/integration -q
PASS — 162 tests, no warnings, 85.87% total branch-aware coverage.

UV_CACHE_DIR=.cache/uv uv run pytest \
  tests/unit/test_monitoring_aws_phase05.py \
  tests/unit/test_monitoring_drift_phase05.py \
  tests/unit/test_monitoring_events_state_phase05.py \
  tests/unit/test_monitoring_performance_phase05.py \
  tests/unit/test_monitoring_reports_phase05.py \
  tests/integration/test_monitoring_cli_phase05.py \
  tests/integration/test_monitoring_phase05.py \
  tests/contract/test_monitoring_report_contract_phase05.py \
  -q --cov-fail-under=0 --cov-report=
PASS — all 61 focused Phase 05 unit, integration, contract, fake-AWS, report, and persistence tests
passed in 7.73 seconds. The repository coverage floor remains enforced by the full gate below.

make verify
PASS — Ruff format/lint passed across 144 files; strict Mypy passed 47 source files; all 171
repository tests passed in 15.94 seconds with 86.08% branch-aware coverage; Bandit passed; strict
hashed pip-audit reported no known vulnerabilities; the secret/file scan passed; and trusted-model
verification passed. No check was disabled or weakened.

UV_CACHE_DIR=.cache/uv uv run pytest \
  tests/contract/test_api_contract_phase03.py \
  tests/contract/test_prediction_event_contract_phase04.py \
  tests/integration/test_api_load_phase03.py \
  tests/integration/test_api_phase03.py \
  tests/integration/test_prediction_logging_phase04.py \
  tests/unit/test_api_schemas_phase03.py \
  tests/unit/test_inference_phase03.py \
  tests/unit/test_prediction_events_phase04.py \
  tests/unit/test_telemetry_logging_phase03.py \
  -q --cov-fail-under=0 --cov-report=
PASS — all 47 affected Phase 03/04 regression tests passed in 6.41 seconds. The per-command coverage
floor was disabled only because this was a narrow diagnostic subset; the full `make verify` run
above retained and passed the repository's configured 70% branch-coverage gate. An exploratory
`--no-cov` invocation had first stopped inside pytest-cov's `no_cover` marker hook before the test
body ran; keeping coverage active resolved that command-option incompatibility without changing
project configuration or code.

./scripts/check_no_secrets.sh
PASS — basic defense-in-depth secret/file scan.

UV_CACHE_DIR=.cache/uv uv lock --check --offline
PASS — all 159 packages resolved offline without changing uv.lock.

make verify-model
PASS — trusted model 1.0.0, manifest
49cbe04bc4285fc71463d0071e3babc3a5f5c20011541a072b4844bb5c78afd9, smoke score
0.9981110662188358.

make export-monitor-schema; git diff --check; LC_ALL=C sort -c FILE_MANIFEST.txt
PASS — schema reproducible, no whitespace errors, manifest sorted.
```

`make train` was not repeated because the already verified canonical Phase 02 data and bundle are
immutable and the training command intentionally refuses those existing version paths. Deleting or
overwriting them merely to rerun validation would violate the bundle contract; `make verify-model`
provides the required current bundle evidence.

## Tests

- Math: known PSI/JS vectors, identity/symmetry/bounds/zero bins, exact smoothing, constants,
  empty/non-finite inputs, special buckets, and every warning/degraded/missingness boundary.
- Windows/records/identity: explicit UTC and grace edges, half-open timestamps, closed/frozen
  snapshot behavior, order/repartition invariance, all exclusive record classes, exact
  reconciliation, benign/conflicting event IDs, and known/unknown/conflicting model identities.
- States/labels: all state precedence and boundaries; never-run/stale/failure persistence; strict
  label schema, duplicates/conflicts/unknown versions, coverage/orphans/missing labels, every
  adequacy condition, label-backed metrics, and synthetic-cost boundaries.
- Reports/operations: canonical identity sensitivity/invariance, strict schema validation, escaped
  offline HTML, immutable exact reruns, atomic monotonic latest, all three transition dimensions,
  repeated/concurrent/restart alert deduplication, marker outcome persistence, and EMF
  dimension/redaction/freshness semantics.
- Integration: repeated stationary windows remain healthy; clear shifts degrade; tiny input is
  insufficient/unknown; unlabeled drift leaves performance unknown; stationary labeled events can
  independently degrade performance; repartitioning preserves report/checksum identity; CLI grace
  and configuration-validation failures persist separately from prior success. Schema-invalid rows
  and outside-window rows stop before identity classification.
- AWS boundaries use only injected fakes: SSM is read once, exact bundle VersionIds are fetched and
  verified, S3 inputs are pinned/decompressed, history/latest use conditional writes, and SNS
  failures are reduced to bounded non-secret outcomes. No unit or integration test makes a network
  call.

## Generated artifacts

- Committed monitoring policy: `configs/phase-05-monitoring.json`; file SHA-256
  `599adfc823d6a6e2e9153d23e3a2cecbdfbbe9a59afaeeba75930b06b77bbc1e`; canonical effective digest
  in reports `edd3177bc4a692262858b6ec2e60a991cdce1bc844ef7eb0becac6846df56c73`.
- Committed report schema: `contracts/monitoring-report-v1.schema.json`; SHA-256
  `fd1fc6a1d0e2143c8fd53bef317c89cd3a1ee7ee934db390513c84381e0d1967`.
- Ignored validation roots: `artifacts/phase-05-validation/predictions/` and
  `artifacts/phase-05-validation/reports/`.
- Baseline JSON/HTML SHA-256: `d95ccc406894dbcd96402672c0cedd0ed56267112c7bd68e9e1eade118a46d3c`
  / `2a4f81b440fac5870a17e73617994c8a340007e3a418620393ae5e37ed6cb830`.
- Shifted JSON/HTML SHA-256: `60fdb7f589b2d708226b4157aeba744ad06357a3dabfd9634125f643448e753f`
  / `6552398fea7f5619c6c1d3e1e920b7059e32a3032fd63c4d1ab2fd3a68fbe62f`.
- Drift marker SHA-256: `ccd2b5fd1638bead639d00ec80075aa06a1f4eee3b4edfac640f51ac1d85d9ed`;
  it records `healthy -> degraded`, `not_configured`, and no exactly-once guarantee.
- Committed index: `reports/evidence/phase-05/README.md`.

## Decisions/assumptions

- The immutable successful report excludes a later invocation's `as_of`; window eligibility is
  determined by end plus grace, while mutable failure/freshness health lives in `run-status.json`.
  Changing the actual frozen record/label multiset still changes report identity.
- The known-non-target registry and label-source configured bit are additional semantic identity
  inputs. Without them, an empty registry/source change could produce different bytes under one
  create-only report ID.
- The local quickstart may derive the four-field target from an exactly inspected bundle because the
  mandated demo command omits `--target-*`; tests exercise explicit target arguments, and the
  service verifies either frozen tuple against the bundle again. AWS uses the single-read strict SSM
  pointer boundary.
- Missingness is separate from drift metrics. Grace is a closing delay, and accepted-event
  freshness is event-time freshness—not row delivery lateness.
- Monitoring never retrains, promotes, rolls back, infers performance from drift, or emits one
  overall health state.

## Residual risks

- AWS boundaries are contract- and mock-tested only. No SSM/S3/SNS resource, ECS scheduled task, IAM
  policy, CloudWatch alarm, or live delivery claim exists until the later infrastructure phases.
- Conditional alert markers suppress normal retry spam but cannot provide exactly-once SNS delivery;
  a process failure between claim and recorded outcome can leave a claimed marker pending review.
- Performance applies only to the adequate labeled subset. Partial-label selection bias, delayed
  availability, and the synthetic cost policy prevent generalizing it to full-window real-world
  economics.
- Local snapshots copy logical inputs into memory, which is appropriate for this finishable MVP but
  is not an unbounded-scale ingestion design.

## Acceptance checklist status

All Phase 05 functional checklist and drift-monitoring acceptance items are implemented and pass
the deterministic, fake-cloud, integration, schema, dependency-audit, and full regression test
gates. No unexplained test, lint, type, static-security, dependency, secret, schema, bundle, or
artifact failure remains.

## Phase decision

**GO for Phase 06 after the authorized Phase 05 commit.** The dedicated independent review below is
complete, no unexplained Phase 05 failure remains, and no dashboard, container, Terraform, workflow,
live AWS resource, or infrastructure implementation was started. Phase 06 remains not started.

## Dedicated pre-commit independent-review gate

- Completely reviewed all 13 modified and 26 new files against `PROJECT_SPEC.md`,
  `ARCHITECTURE.md`, `ACCEPTANCE_CRITERIA.md`, all eight ADRs, the Phase 05 prompt, monitoring
  contract, checklist, report, evidence index, and manifest.
- Confirmed all 39 paths are Phase 05 monitoring policy, ingestion/classification, transparent drift
  math, delayed labels, reporting/persistence, injected AWS boundaries, telemetry, tests,
  documentation, or bounded Phase 03/04 regression repairs. No Phase 06 dashboard, Docker,
  Terraform, GitHub workflow, live AWS resource, or infrastructure implementation is present.
- Confirmed strict event-schema validation and half-open window classification both precede exact
  four-field identity classification, followed by stable event-ID deduplication. The independent
  review repaired the out-of-window identity-observation leak and added a regression test. Closed
  local snapshots include only `.jsonl`/`.jsonl.gz`, never active `.jsonl.open` files, and every raw
  row reconciles to exactly one exclusive count.
- Confirmed numeric and prediction PSI use only frozen baseline bins, natural logs, and exact
  `1e-6` smoothing/renormalization; categorical and decision signals use base-2 Jensen-Shannon
  distance. Feature order and threshold boundaries are deterministic, and monitoring never fits,
  selects a deployment threshold, retrains, promotes, rolls back, or mutates the model.
- Confirmed run, data-quality, drift, and performance states are separate and the schema has no
  overall state. With no label source performance is `unknown`; a configured but inadequate valid
  source is explicitly `pending_labels`; malformed, conflicting, or unknown-version labels are
  `unknown`. Metrics require all support boundaries and describe only the labeled synthetic subset;
  drift is never presented as accuracy.
- Confirmed report IDs cover canonical semantic inputs, history is create-only, latest advances only
  for a strictly newer window, exact reruns are byte-identical, transition markers suppress duplicate
  alerts, and invalid monitoring configuration persists bounded failed-run evidence.
- Confirmed AWS boundaries use injected protocols/fakes only. EMF has only `Service` and
  `Environment` dimensions, fixed count/freshness signals, and no identities, feature values,
  request/event IDs, secrets, arbitrary error text, or delivery-lateness claim.
- Repeated all 61 focused Phase 05 tests, the 162-test unit/integration gate at 85.87% branch
  coverage, all 47 affected Phase 03/04 regressions, and `make verify`: 171 tests passed at 86.08%
  branch coverage; Ruff, strict Mypy, Bandit, strict hashed `pip-audit`, secret scanning, and trusted
  model verification all passed.
- Replayed baseline, shifted, identical shifted rerun, and exact stale-boundary scenarios in an
  isolated directory. Baseline remained `valid/healthy/unknown`; shifted remained
  `valid/degraded/unknown`; the rerun kept the exact report ID and JSON/HTML checksums with
  `latest_updated=false`; and exactly two hours after the latest success was `stale`.
- Repeated schema export, metadata-only bundle inspection, offline resolution of all 159 locked
  packages, exact 178-path manifest parity, JSON/shell syntax, whitespace, Arabic content/filename,
  secret, disposable-output, and staged-file checks. The immutable Phase 02 bundle was never
  retrained or overwritten.

## Suggested commit message

`feat: add deterministic Phase 05 monitoring and reports`

## Next manual action

After committing the reviewed Phase 05 files, wait for an explicit Phase 06 instruction. Do not
push or start Phase 06 as part of this gate.

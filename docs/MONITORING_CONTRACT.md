# Deterministic Monitoring Contract

Phase 05 finalizes one immutable distribution/performance report for one explicit model identity and
one UTC event-time window. It never collapses run health, input quality, drift, and labeled model
performance into a misleading overall status.

## Window and snapshot

- The event-time window is half-open `[start,end)` in UTC and defaults to one hour.
- Finalization requires `as_of >= end + 10 minutes`. The exact boundary is accepted.
- The grace period is only a closing delay. ModelGuard does not claim a row-level delivery-lateness
  metric. Firehose/S3 freshness remains separate infrastructure telemetry.
- Local monitoring copies the logical records from a frozen enumeration of closed `.jsonl` or
  `.jsonl.gz` files before analysis. Active `.jsonl.open` writers are excluded.
- Firehose explicitly writes GZIP objects with the `.jsonl.gz` extension. AWS monitoring accepts
  exactly that suffix; local `.jsonl` compatibility does not widen the AWS object-name contract.
- AWS helpers verify all three bucket Regions, derive only the finite physical UTC arrival-hour
  prefixes from the event window start through `end + finalization grace`, and enumerate them with
  one shared `MaxKeys`, page, total-entry, deduplicated-object, compressed-byte, and decoded-byte
  budget. They reject every key outside its requested hour prefix and pin every object by VersionId,
  or by ETag with `If-Match` when a VersionId is unavailable, before reading it. A changed identity,
  partial length, invalid or cycling pagination token, missing truncation marker, excessive
  irrelevant entries, corrupt GZIP body, or aggregate overflow fails the cycle.
- Tests and evidence always pass explicit `--window-end` and `--as-of`; no test depends on wall
  clock time.

## Exact target and baseline identity

Every run freezes this event-carried tuple:

```text
event_schema_version
model_version
bundle_manifest_sha256
input_schema_version
```

Local/tests can pass all four `--target-*` arguments. The quickstart may derive them from the exact
verified `--bundle`, after which the service verifies the tuple again. Known non-target identities
come only from separately verified bundles. AWS mode uses the strict
`modelguard.active-monitor-target.v1` SSM pointer and caches its single read for the run; versioned
S3 bundle objects are downloaded and checked before use.

The scheduled image exposes `aws-run`, which executes exactly one cycle and exits. It requires the
canonical `us-east-1` Region, exact active-pointer parameter, distinct buckets in that Region, exact
regional SNS topic, absolute runtime volume, the locked in-image monitoring configuration, and a
sample threshold consistent with runtime settings. It uses only the ECS task-role/default SDK
credential chain; there is no profile or static credential input. Unlike local `run`, `aws-run`
does not expose `--config`, so drift bins, thresholds, sample limits, or policy semantics cannot be
replaced at invocation time.
The canonical semantic policy SHA-256 is
`edd3177bc4a692262858b6ec2e60a991cdce1bc844ef7eb0becac6846df56c73`; changing bins,
thresholds, sample limits, feature ordering, or performance semantics changes that identity and
fails before any AWS operation.

The report separately records:

- the target identity carried by events;
- every observed event-carried identity and its classification;
- the baseline profile hash, input-schema hash, training-membership hash, and support derived from
  the exact verified target manifest; and
- the canonical hash of the effective versioned monitoring configuration, computed once per run.

An exact target candidate must match all four identity fields. Exact verified known identities are
excluded as `known_non_target`. Unknown identities, or combinations that collide with a known model
version/manifest but disagree elsewhere, are rejected and make data quality invalid.

## Exclusive record classification

The order is fixed:

1. JSON parsing and the strict event schema;
2. timestamp membership in `[start,end)`;
3. exact identity classification; and
4. target-event deduplication by `event_id`.

An identical group of size `k` accepts one canonical event and counts `k-1` duplicates. If the same
event ID has more than one canonical event body, every row in that group is rejected. Every report
validates:

```text
raw = rejected + outside_window + known_non_target + duplicate + accepted_target
```

`outside_window` alone does not warn. The default minimum is 500 accepted target events; smaller or
empty windows are `insufficient_data`, and their drift state is `unknown`.

## Drift and missingness math

For a `k`-bin probability vector:

```text
smooth(p)_i = (p_i + 1e-6) / (1 + k*1e-6)
```

Numeric features and prediction scores use frozen reference bins and natural-log PSI:

```text
sum((current_i - baseline_i) * ln(current_i / baseline_i))
```

PSI is warning at `>= 0.10` and degraded at `>= 0.25`.

The strict boolean `is_new_device` feature uses an explicit ordered `false`/`true` baseline and
Jensen-Shannon distance. It is never collapsed into one inclusive numeric interval.

Categorical features and locked decisions use Jensen-Shannon distance: the square root of base-2
Jensen-Shannon divergence over the full baseline universe plus `__OTHER__` and `__MISSING__`. It is
bounded in `[0,1]`, warning at `>= 0.10`, and degraded at `>= 0.20`.

A constant baseline that is unchanged has a null metric with a healthy reason. A changed constant
has a null metric with a degraded reason. Empty, non-finite, or otherwise unevaluable input is
unknown. KS is intentionally omitted.

Missingness among accepted events is evaluated separately as the absolute
current-minus-baseline rate difference. Under the strict v1 event schema every required feature is
present and non-null before acceptance, so a missing required field is counted as a schema-rejected
record rather than attributed to a per-feature missingness signal. Rejected-fraction thresholds
still warn or invalidate data quality. The per-feature voter is retained for a future explicitly
nullable event contract; this MVP does not claim raw-field attribution for rejected records.

All external JSON artifacts reject duplicate keys, non-finite constants, excessive nesting, extra
fields, and type coercion before their Pydantic contracts are accepted.

## Independent states and precedence

```text
run:          never_run | succeeded | failed | stale
data_quality: valid | warning | invalid | insufficient_data
drift:        healthy | warning | degraded | unknown
performance:  healthy | warning | degraded | pending_labels | unknown
```

- Run precedence is current failure, never-run, stale latest success, succeeded. A success becomes
  stale at exactly two hours without a newer success.
- Data-quality precedence is invalid, insufficient, warning, valid. Reconciliation, bundle,
  identity, conflicting-event-ID, missingness-invalid, and rejected-fraction `>= 0.05` faults are
  invalid. Otherwise rejected rows, duplicates, known non-target rows, or warning missingness warn.
- Invalid or insufficient data forces drift unknown. Otherwise degraded outranks warning; any
  remaining required unknown signal prevents a healthy claim.
- Performance never derives from drift.

## Delayed labels

The optional local label source accepts only:

```json
{
  "label_schema_version": "modelguard.label.v1",
  "event_id": "UUID",
  "label": 0,
  "labeled_at": "UTC timestamp ending in Z"
}
```

Extra fields, coercion, non-UTC text, and labels outside `{0,1}` are rejected. Canonically identical
labels deduplicate; differing rows for one event ID conflict. Orphans are reported and excluded.
Coverage is unique valid joined labels divided by accepted target events.

The local-only label adapter enforces the inclusive logical ordering
`event_timestamp <= labeled_at <= evaluation_cutoff`. The explicit cutoff is the run's UTC `as_of`
timestamp. Labels before their matching event or after that cutoff are classified separately,
excluded from the joined subset, counted as `temporally_ineligible`, and force performance to
`unknown` rather than allowing misleading metrics. Both the cutoff and the temporal classification
are bound into the report identity. Online/AWS label collection remains out of scope; results
describe only the supplied synthetic subset and are never presented as real-world or causal
performance evidence.

New reports use `modelguard.monitoring-report-identity.v2` for this cutoff-aware identity. Existing
v1 report artifacts remain parseable and are explicitly marked with the legacy temporal-policy
default rather than being reinterpreted as cutoff-validated evidence.

Adequacy requires all of:

- coverage `>= 0.80`;
- at least 500 joined labels;
- at least 20 positive labels; and
- at least 100 negative labels.

No configured source is `unknown`. A valid configured source below adequacy is `pending_labels`.
Unknown schema versions, malformed rows, temporal ineligibility, or conflicts are `unknown`. Only
adequate labels produce average precision/prevalence/AP lift, ROC-AUC, Brier, log loss, and
locked-threshold precision/recall/F1/confusion metrics.

Only the locked policy votes on performance state:

```text
current synthetic cost/event = (10 * FN + FP) / labeled_rows
delta = current - held-out test synthetic cost/event
healthy:  delta < 0.10
warning:  0.10 <= delta < 0.25
degraded: delta >= 0.25
```

Every presentation uses the phrase “synthetic-policy cost on the labeled subset versus held-out
synthetic reference.” Partial-label selection bias remains an explicit limitation.

## Report identity, publication, and alerts

`report_id` is a semantic-input identity, not a content-authentication digest. It is a SHA-256 over
the report schema version, window/grace, target/baseline/config
identities, the sorted known-non-target registry, whether a label source was configured, sorted
canonical record/classification digests, and sorted label/classification digests. Including the
registry and source-presence bit prevents two different report bodies from colliding when either
input is empty. The identity excludes enumeration order, object names, file boundaries, mutable
enclosing-file hashes, post-grace invocation time, and HTML presentation.

Local history uses create-if-absent files under:

```text
artifacts/reports/history/<window-end>/<report-id>.json
artifacts/reports/history/<window-end>/<report-id>.html
artifacts/reports/latest.json
artifacts/reports/run-status.json
artifacts/reports/alerts/*.json
```

An exact rerun returns the same report/checksums. `latest.json` is replaced atomically only for a
strictly newer window. AWS history/markers use `If-None-Match: *`, and latest uses `If-Match` or
`If-None-Match` conditional writes. Five unresolved conditional conflicts fail persistence rather
than silently reporting success. The conditional run-status object keeps the newest attempt and
preserves the last successful timestamp/report identity when a later attempt fails.

Local report publication locks `latest`, but the local run-status adapter is a single-writer
developer/demo boundary and does not support concurrent monitor processes. The AWS adapter uses
conditional object writes and is the process-safe deployment boundary. Generated evidence records
the JSON file SHA-256 (and AWS object identity where applicable); `report_id` alone must not be used
to authenticate persisted report bytes.

After a successful newer report, a conditional marker is claimed before SNS on entry into exactly
three states: data-quality invalid, drift degraded, and performance degraded. The marker then stores
`sent`, bounded `failed`, or `not_configured`. A claim suppresses routine retries but explicitly does
not promise exactly-once delivery. Run failures and staleness belong to CloudWatch alarms.

AWS completion emits one EMF record with only `Service` and `Environment` dimensions, completion
and reconciled counts, and accepted-event freshness. It contains no request/event IDs, features,
secrets, or arbitrary model-version dimensions, and its freshness field is not delivery lateness.

`aws-run` writes one canonical `modelguard.monitor-aws-run-output.v1` JSON object to stdout and EMF
only to stderr. Exit `0` means a complete persisted cycle; `2` is invalid or contradictory
configuration, `3` is AWS credential, authorization, or provider access failure, `4` is corrupt or
incomplete evidence, and `5` is report, alert, telemetry, or run-status persistence failure. A
nonzero cycle is never converted into scheduler success.

## Local deterministic demo

Create the immutable bundle once, then generate and finalize two windows:

```bash
make train
uv run python scripts/generate_monitoring_fixture.py \
  --scenario baseline --window-end 2026-01-01T01:00:00Z
uv run python -m modelguard.monitoring.cli run \
  --window-end 2026-01-01T01:00:00Z --as-of 2026-01-01T01:10:00Z
uv run python scripts/generate_monitoring_fixture.py \
  --scenario drifted --window-end 2026-01-01T02:00:00Z
uv run python -m modelguard.monitoring.cli run \
  --window-end 2026-01-01T02:00:00Z --as-of 2026-01-01T02:10:00Z
```

The first window must be drift healthy; the second must be drift degraded. With no label directory,
both performance states remain unknown. `make export-monitor-schema` reproduces the checked-in
`contracts/monitoring-report-v1.schema.json` exactly.

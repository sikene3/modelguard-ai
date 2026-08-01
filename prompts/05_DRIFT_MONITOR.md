# Phase 05 — Drift, Data Quality, Delayed Performance, and Reports

## Recommended mode
GPT-5.6 Sol, Max.

## Objective
Implement deterministic monitoring that never confuses drift, data quality, run health, or labeled
model performance.

## Exact monitoring contract
- UTC event-time half-open window `[start,end)`, default one hour; ten-minute finalization grace;
  explicit `--window-end` and `--as-of` in tests; two-hour stale threshold. Require
  `as_of >= end + grace`, freeze/enumerate the raw input snapshot at run start, and do not claim a
  row-level delivery-lateness metric.
- Snapshot one target event-schema/model/manifest/input-schema identity per run (explicit CLI in
  local/tests; SSM once at AWS run start). Resolve and verify that exact bundle even for historical
  windows, derive baseline identity from its manifest, and compute a canonical monitoring-config
  hash once. Known non-target model identities are excluded/counted; unknown or conflicting
  identities make data quality invalid. Reports contain event-carried and derived identities.
- Classify record counts exclusively: parse/schema failures are rejected; valid timestamps outside
  the window are `outside_window`; known non-target identities are `known_non_target`; then dedupe
  valid target candidates. An identical group of size `k` accepts one and counts `k-1` duplicates;
  a conflicting ID group rejects all `k`. Reconcile exactly:
  `raw = rejected + outside_window + known_non_target + duplicate + accepted_target`.
- Minimum 500 accepted events by default. Tiny/empty input is `insufficient_data`, never healthy.

## Exact math
- Numeric/prediction PSI uses frozen training bins and natural log. Smooth each proportion vector
  with epsilon `1e-6`, then renormalize. Warning `>=0.10`, degraded `>=0.25`.
- Categorical/decision metric is Jensen-Shannon **distance**: square root of base-2 divergence in
  `[0,1]`, over baseline universe plus `__OTHER__`/`__MISSING__`, with the same smoothing rule.
  Warning `>=0.10`, degraded `>=0.20`.
- Constant baseline unchanged: metric null/healthy reason; changed: null/degraded reason. Empty or
  unevaluable input: unknown. Missingness is assessed separately. Omit KS in this MVP.
- For each `k`-bin vector use `smooth(p)_i = (p_i + 1e-6) / (1 + k*1e-6)`. PSI is
  `sum((current_i-baseline_i) * ln(current_i/baseline_i))` over smoothed vectors; JS uses their
  midpoint and base-2 KL before the square root. Missingness uses absolute current-minus-baseline
  rate difference with versioned defaults: warning `>=0.02`, invalid `>=0.05`.

## Independent states
- Run: `never_run | succeeded | failed | stale`.
- Data quality: `valid | warning | invalid | insufficient_data`.
- Drift: `healthy | warning | degraded | unknown`.
- Performance: `healthy | warning | degraded | pending_labels | unknown`.
Do not emit one misleading overall state. Invalid/insufficient data forces drift unknown.
Data-quality precedence is invalid, insufficient, warning, valid. Reconciliation/bundle/identity,
conflicting-ID faults, missingness at its invalid boundary, or `rejected/raw >=0.05` (for nonzero
raw) are invalid; otherwise any rejected,
benign duplicate, known-non-target, or missingness warning makes warning. `outside_window` alone is
not a quality warning. When quality permits evaluation, drift is the maximum required-signal
severity and is healthy only if every required signal is evaluable below warning. Run precedence is
current failure, never-run, stale latest success, succeeded.

## Delayed labels
Optional local versioned labels join accepted events by `event_id`. Deduplicate identical labels;
conflicts/unknown versions make performance unknown. Report coverage, missing/orphan/conflicting
labels. Adequacy defaults: coverage `>=0.80`, at least 500 labeled rows, 20 positives, 100 negatives.
Only adequate labels may produce AP/prevalence/AP lift, ROC-AUC, Brier, log loss, locked-threshold
precision/recall/F1/confusion metrics. Without labels, performance is unknown—not inferred from drift.

Minimal label rows are strict `{label_schema_version, event_id, label: 0|1, labeled_at: UTC}`.
Coverage is unique valid joined labels divided by `accepted_target`; orphans are reported but
excluded. No configured label source is `unknown`; a configured source below adequacy is
`pending_labels`; unknown schema/conflicts are `unknown`. With adequate labels compute locked-policy
`synthetic_cost_per_event`, subtract the held-out test reference stored after Phase 02, and assign:
healthy delta `<0.10`, warning `>=0.10 and <0.25`, degraded `>=0.25`. Other metrics do not vote on
state. Always say “synthetic-policy cost on the labeled subset versus held-out synthetic reference”;
partial-label selection bias remains a disclosed limitation.

## Idempotency and reports
Canonical `report_id` hashes report schema, window/grace, target/baseline/config identities, sorted
canonical selected record/classification digests, and sorted label digests. It is independent of
enumeration order, storage object name, file boundary, and mutable enclosing-file hash. Immutable
history uses create-if-absent; exact snapshot reruns return the same checksum. Atomically update
`latest` only for a newer window (local temp-file rename; conditional S3 write in AWS). Conditionally
claim dimension/transition markers before SNS and record send outcome; suppress routine retry spam
without claiming exactly-once delivery. The monitor alerts only after successful runs on entry into
data-quality invalid, drift degraded, or performance degraded. CloudWatch owns run failure/staleness.
Produce strict JSON and escaped offline HTML plus a low-cardinality EMF completion/count/freshness
record in AWS mode.

## Mandatory tests
Known PSI/JS vectors, identity/symmetry/bounds/zero bins, constants/empty/non-finite values, exact
threshold boundaries, window/grace edges, frozen snapshots and reconciled counts,
input-order-independent deduplication, conflicts, known/unknown model identities, state precedence,
label schema/coverage/adequacy/cost boundaries/conflicts, stale/never-run, canonical report ID across
repartitioning/file append, HTML escaping, monotonic latest, concurrent/repeated-run alert dedupe,
EMF redaction/dimensions, multiple stationary windows, clear shifted windows, tiny data, unlabeled
drift, labeled performance change, and restart persistence.

## Constraints
No retraining/promotion, Evidently core dependency, accuracy claim without labels, hidden wall-clock
tests, or live network calls.

## Validation
```bash
make train
uv run python scripts/generate_monitoring_fixture.py --scenario baseline --window-end 2026-01-01T01:00:00Z
uv run python -m modelguard.monitoring.cli run --window-end 2026-01-01T01:00:00Z --as-of 2026-01-01T01:10:00Z
uv run python scripts/generate_monitoring_fixture.py --scenario drifted --window-end 2026-01-01T02:00:00Z
uv run python -m modelguard.monitoring.cli run --window-end 2026-01-01T02:00:00Z --as-of 2026-01-01T02:10:00Z
uv run pytest tests/unit tests/integration -q
make verify
```

## Definition of done
Stationary windows keep drift healthy; shifted data degrades drift; tiny data is
insufficient/unknown; performance remains label-backed under the versioned synthetic-cost rule;
reports/counts/latest/alerts are deterministic. Update evidence/report.

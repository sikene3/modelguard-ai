# Operations Dashboard Contract

Phase 06 presents evidence computed and versioned by earlier phases. It is a read-only Streamlit
surface, not a monitor, model registry, promotion service, or real-time control plane.

## Evidence ownership

- `MonitoringReport` owns window selection, identity classification, count reconciliation, PSI/JS
  values, missingness, drift severity, and delayed-label performance.
- `RunStatusArtifact` owns the latest attempt, latest successful completion, report ID, and bounded
  failure category.
- The exact `MonitoringConfig` owns stale and score thresholds. The dashboard shows those thresholds
  only when its canonical hash equals the report's recorded configuration hash.
- The configured active model manifest supplies the active semantic version, manifest digest, and
  input-schema digest. It is displayed separately from the event-carried report target.
- The dashboard owns formatting, safe artifact access, and freshness presentation only. It never
  recomputes a score/state, promotes a model, mutates a report, or infers performance from drift.

## Repository interface

`DashboardRepository` exposes the same five read operations for local files and S3:

1. latest strict JSON report;
2. independent run-status JSON;
3. configured active model manifest;
4. bounded recent immutable report history; and
5. HTML access for a validated report ID/window.

Local reads reject symlinks/non-regular artifacts, bound JSON/HTML sizes, and return HTML bytes as an
offline browser download. S3 reads use an injected client, bounded payload/history sizes, and the
private `monitoring/` and `model-bundles/` prefixes. HTML access first checks the exact object and
then returns an HTTPS-only, five-minute presigned attachment URL. The URL is not written to state or
logs. Unit tests use fakes and make no network calls.

Phase 06 does not create AWS infrastructure or an AWS monitor orchestrator. Its S3 reader expects
`monitoring/run-status.json` using the existing `modelguard.monitor-run-status.v1` contract. Phase 08
must grant the dashboard read-only access and make the scheduled monitor persist that object before
deployed AWS run-state/freshness is claimed.

## Freshness and failure behavior

Each Streamlit rerun takes one actual UTC `captured_at` value. Freshness uses
`latest_success_at` from run status and the matching policy's `stale_after_seconds`; file mtimes and
browser time are not substituted. Window and maximum accepted-event ages are shown separately and
are not described as delivery lateness.

- No report and no run status: run is `never_run`; report-backed cards are unavailable.
- A current failed attempt: run is `failed`; any matching last successful report remains explicitly
  historical evidence.
- A success at or beyond the exact stale boundary: run is `stale`.
- Missing/malformed/mismatched run status: current run state is unavailable, not succeeded.
- Missing/malformed report: data-quality, drift, and performance states are unavailable.
- Invalid or insufficient data keeps the report's drift `unknown`.
- No label source keeps performance `unknown`; an inadequate configured source remains
  `pending_labels`. Neither is restyled or renamed as healthy.

`unknown`, `stale`, `insufficient_data`, `pending_labels`, and unavailable artifacts use visibly
different card borders, colors, and labels. A valid stale/failed run never rewrites the independent
states stored in the last successful report. The checked-in Streamlit theme fixes a light,
high-contrast palette so browser color-scheme preferences cannot make native widgets unreadable.

## Displayed evidence

- four independent state cards and exact UTC snapshot/report/window/event timestamps;
- accepted target volume plus every exclusive reconciliation bucket and classification fault;
- active and report-target model/manifest identities, event/input schemas, baseline and config
  hashes, report ID, known non-target count, and half-open window/grace;
- top input features with monitor-recorded metric, score, severity/reason, and identity-matched
  warning/degraded thresholds;
- numeric and categorical baseline/current proportions where both vectors are in the report;
- exact prediction-score-bin and locked-decision proportions across recent reports with matching
  target, baseline, and monitoring-policy identities; and
- labeled-subset metrics/coverage only when present, always with the synthetic-policy and selection-
  bias limitations.

There are no authentication-platform features, model controls, promotion buttons, auto-refresh
claims, or raw event/feature displays in Phase 06.

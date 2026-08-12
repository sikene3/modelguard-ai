# Phase 11 Evidence Index

Phase 11 completed two local-only runs against the same explicit anchor and verified their stable
projections. Generated events, model candidates, reports, command output, and complete summaries
remain under the ignored `artifacts/phase-11-evidence/` tree; this tracked index records only public,
synthetic identities and two report-backed dashboard images.

## Fixed contract and repeatability

- Anchor: `2026-08-11T19:46:00Z`.
- Target bundle: model `1.0.0`, manifest
  `f126f986aa210f3213d9c6cdc88f65b4bb9c2d2d20e49f1eae91fb48ec01f439`.
- Accepted-event minimum: 500.
- Baseline and drifted accepted events: 1,000 each; deterministic headroom: `+500` each.
- Canonical post-fix run 1: `phase11-final-local-03`, 64.235558 seconds.
- Canonical post-fix run 2: `phase11-final-local-04`, 63.005936 seconds.
- Stable projection SHA-256:
  `5cfc687d7c8a8c9650ee2b3939f49cf10c97699d6be173dcc44e0ab3a03001cc`.
- Comparison: matching fixed-anchor report IDs/hashes, dashboard images, counts, states, headroom,
  alert marker, and expected breached metrics.

The expected nondeterministic fields were wall-clock execution timestamps/durations, candidate
MLflow run ID, candidate creation timestamp, and candidate manifest identity. Candidate manifests
differed as expected; neither was selected using a performance comparison. Earlier successful
development cycles remain ignored local artifacts but are superseded by this final post-security-fix
pair for acceptance evidence.

## Monitoring scenarios

| Scenario | UTC half-open window / as-of | States `(run, quality, drift, performance)` | Accepted | Report ID |
| --- | --- | --- | ---: | --- |
| Insufficient | `[16:46,17:46)` / `17:46Z` | `succeeded, insufficient_data, unknown, unknown` | 50 | `7e6678f4e5683d8d4856252dde50ba90f409872571d7e94db33bae2bd84411e1` |
| Baseline | `[17:46,18:46)` / `18:46Z` | `succeeded, valid, healthy, unknown` | 1,000 | `e6942cc42047d74a6417487df5c8e960c6dcd9d51ff9e63123be67cfa6dcf733` |
| Drifted | `[18:46,19:46)` / `19:46Z` | `succeeded, valid, degraded, unknown` | 1,000 | `0f60429d668929d353842ba54c3196b6865eceedb251ccdeb0b1c10db1ca1801` |

All timestamps are on `2026-08-11` UTC. Baseline and shifted inputs use separate directories and
adjacent, non-overlapping windows. Performance has no configured label source, coverage is null,
and no accuracy or causal claim is made.

Run 1 immutable report identities:

| Scenario | JSON SHA-256 | HTML SHA-256 |
| --- | --- | --- |
| Insufficient | `5a13760812be7247edc78a0f0503eb88f95b6eed76c0a56a852add5d310149b0` | `4c93b1e9cefb6bad2015dcd46654fd28d6961af858acbe6d450adefae8db965c` |
| Baseline | `071d83c91a434782d36e1a7ba03027afb29cec1a6dfd9bd1d685c54a72910a7b` | `6b1e4cfa1152723538802fd98e7964cc8e0dc3ee033fd92572bc3fb9f5fab628` |
| Drifted | `407f60f53201f28714c0e4c9c0e2d7093370cb97060c55a51351d8d10b64c57b` | `9302d98e1aac1d4b40c0e42e45890523b559b9f1761d00275cd2e06f92c08107` |

The drifted report recorded degraded PSI for `amount`, `velocity_1h`,
`distance_from_home_km`, `device_risk_score`, `merchant_risk_score`, and `prediction_score`;
degraded Jensen-Shannon distance for `country_code` and `device_type`; and warning
Jensen-Shannon distance for the locked-decision distribution. Exact values and thresholds are in
the generated drifted summary.

Phase 12 found that these immutable Phase 11 reports predated the baseline-v2 boolean correction:
their aggregate degraded transition remains valid evidence, but their historical
`is_new_device` numeric signal is superseded and is not cited as feature-level evidence. Current
source requires an explicit false/true Jensen-Shannon signal and regression-proves that a
baseline-like mixture stays healthy while all-false and all-true populations degrade. Future Phase
11 reproductions include that signal in `expected_breached_metrics`; the immutable historical files
were not rewritten.

## Dashboard evidence

| State | Tracked image | Kind | PNG SHA-256 |
| --- | --- | --- | --- |
| Healthy | `healthy-dashboard-evidence.png` | Offline, report-backed snapshot | `3260e1e3146471676cadb85165701ee0de321b3137922af69f558941461e3327` |
| Degraded | `degraded-dashboard-evidence.png` | Offline, report-backed snapshot | `350e1f75672fb3fc5a34444b8a2ac6d523460a479c6f45c7ec928db051f9a1f2` |

Both images are 1440×1120 RGB PNGs and visibly identify themselves as offline report-backed
snapshots, not live-browser captures. They were rendered from the validated dashboard
repository/parser. In each local run, Streamlit's real in-process app runner rendered the four
expected state cards, configured-active and report-target identity sections, seven dataframes, and
zero exceptions. The sandbox prohibited local socket creation; prior real headless-browser
reference images remain separately indexed under `reports/evidence/phase-06/`.

## Alert, outage, recovery, and teardown

- The local drift transition marker records `healthy -> degraded`, SHA-256
  `82b950dd8d80091f1c8d036ccd16790c737e7f93eb933eae55569a5049c97751`, and
  `send_status=not_configured`. It is not SNS/CloudWatch delivery evidence.
- The dependency-injected local event-sink outage kept readiness and prediction at HTTP 200 while
  emitting exactly one `local_failed` operation and one `event_sink` error. It was classified as an
  operational sink outage; drift/performance were not evaluated and model degradation was not
  claimed.
- The independent local recovery story verified and promoted model `1.0.1`, retained the exact
  `1.0.0` identity as previous, validated atomic pointer readback, and served `ready=200` plus the
  promoted version/manifest through the real ASGI app. No metric comparison or accuracy-improvement
  claim was used, and the promotion was not presented as a drift response.
- Both teardown rechecks passed with no network listener or long-running process started, closed
  ASGI lifespans/sink, no broken deployment active, and no AWS environment started.
- AWS Phase 11 was correctly not run: `tasks/phase_status.json` records that Phase 10 destroyed the
  demo and left zero disposable residuals. Historical Phase 10 SNS/CloudWatch evidence was not
  relabeled as Phase 11 evidence.

## Generated evidence roots

```text
artifacts/phase-11-evidence/phase11-final-local-03/
artifacts/phase-11-evidence/phase11-final-local-04/
artifacts/phase-11-evidence/local-repeatability.json
```

Summary SHA-256 values:

- Run 1: `1e0ec875a161aa75b1312aba09e242028acde206236356da05015ba2934dbdee`.
- Run 2: `39d8389871140321065a342849680ad2e60e69d5ffa2302608cdeb3fbb511a24`.
- Repeatability record:
  `b6385da1abf756439cb44b702406124e38ad9fb3a9e75943ccd349554359b063`.

See `docs/DEMO_RUNBOOK.md` for exact reproduction and `reports/phase-11.md` for command timings,
validation results, environmental limitations, and residual risks.

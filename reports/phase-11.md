# Phase 11 report — healthy-to-degraded demo and recovery evidence

## Outcome

Phase 11 is complete for the deployed-state boundary that existed when the phase began. Two
create-only local runs used the same explicit UTC anchor and passed the healthy-to-degraded,
insufficient-data, event-sink-outage, controlled-promotion, repeatability, and teardown contracts.
The Phase 10 demo environment was already recorded destroyed with zero disposable residuals, so an
AWS Phase 11 run was not authorized or required by the conditional validation instruction. This
phase made zero AWS mutations and did not relabel historical Phase 10 CloudWatch/SNS evidence.

No labels were configured. Both adequate monitoring windows therefore report
`performance=unknown`, with null coverage and no performance metrics. Input/prediction-distribution
drift is not described as an accuracy decrease. All events are deterministic synthetic fixtures;
no customer data or malicious traffic was used.

## Material assumptions and evidence boundaries

- `tasks/phase_status.json` was treated as the repository's deployment-state record: Phase 10 says
  `live_deployment_destroyed=true` and `disposable_demo_resource_residuals=0`. Live AWS inventory was
  not re-queried and the environment was not recreated.
- The checked-in Phase 07 monitoring policy is the Phase 11 policy. Its minimum is 500 accepted
  target records, its window is one hour, and its finalization grace is zero.
- Model `1.0.0` and manifest
  `f126f986aa210f3213d9c6cdc88f65b4bb9c2d2d20e49f1eae91fb48ec01f439` are the fixed monitoring
  target for both local runs.
- The required recovery story uses a validated, local-only model promotion. Selection uses bundle
  integrity, trusted-origin confirmation, identity, and runtime readiness only. It is independent
  of the observed drift and makes no metric or accuracy-improvement claim.
- The restricted runner denied local socket creation and Chromium crash reporting. Fresh dashboard
  evidence therefore combines the real Streamlit in-process test runner with clearly labeled,
  report-backed PNG snapshots. The PNGs are not represented as live-browser screenshots.

## Implementation

`scripts/phase11_demo.py` adds three fail-closed CLI operations:

```text
run-local             generate, execute, validate, and seal one local evidence cycle
compare-local-runs    compare the deterministic projection of two fixed-anchor cycles
verify-local-teardown revalidate that a completed cycle left no runtime active
```

The harness invokes the existing fixture generator and real monitor CLI as bounded subprocesses.
It also exercises the production dashboard repository/parser, Streamlit script with
`streamlit.testing.v1.AppTest`, real FastAPI ASGI lifespan, event-sink exception boundary, immutable
bundle verifier, and local model runtime. Evidence namespaces are create-only and owner-only. The
Makefile exposes the three commands, and `docs/DEMO_RUNBOOK.md` documents exact reproduction and
expected output.

Six focused unit tests cover explicit UTC windows, non-UTC refusal, strict local pointer state,
fail-open event-sink behavior, deterministic projection, and malformed-summary refusal.

## Fixed local execution contract

Both final runs used anchor `2026-08-11T19:46:00Z` and these UTC half-open windows:

| Scenario | Event-time window | Explicit as-of | Accepted/minimum/headroom | States `(run, quality, drift, performance)` |
| --- | --- | --- | --- | --- |
| Insufficient | `[2026-08-11T16:46:00Z, 17:46:00Z)` | `17:46:00Z` | `50/500/-450` | `succeeded, insufficient_data, unknown, unknown` |
| Baseline | `[2026-08-11T17:46:00Z, 18:46:00Z)` | `18:46:00Z` | `1000/500/+500` | `succeeded, valid, healthy, unknown` |
| Drifted | `[2026-08-11T18:46:00Z, 19:46:00Z)` | `19:46:00Z` | `1000/500/+500` | `succeeded, valid, degraded, unknown` |

Baseline and shifted events are in separate input directories. The adjacent baseline and drifted
windows do not overlap, and the insufficient-data scenario uses its own report repository. The
transition repository's `latest` pointer first selected the baseline report and then advanced to
the drifted report; it never evaluated a mixed baseline/shifted window.

The shifted fixture applies these explicit feature changes:

| Feature | Change |
| --- | --- |
| `amount` | `min(25000, amount * 20 + 5000)` |
| `velocity_1h` | `min(30, velocity_1h + 15)` |
| `distance_from_home_km` | `min(1000, distance_from_home_km + 400)` |
| `device_risk_score` | `min(1.0, 0.8 + 0.2 * value)` |
| `merchant_risk_score` | `min(1.0, 0.8 + 0.2 * value)` |
| `is_new_device` | `true` |
| `country_code` | `"BR"` |
| `device_type` | `"tablet"` |

The resulting drifted report recorded all expected boundary breaches:

| Metric | Kind | Value | Warning/degraded threshold | State |
| --- | --- | ---: | --- | --- |
| `country_code` | Jensen-Shannon | 0.8701956243 | 0.10/0.20 | degraded |
| `device_type` | Jensen-Shannon | 0.8654241533 | 0.10/0.20 | degraded |
| `locked_decision` | Jensen-Shannon | 0.1984375311 | 0.10/0.20 | warning |
| `amount` | PSI | 25.3281430852 | 0.10/0.25 | degraded |
| `device_risk_score` | PSI | 15.9474587920 | 0.10/0.25 | degraded |
| `distance_from_home_km` | PSI | 16.0140483723 | 0.10/0.25 | degraded |
| `merchant_risk_score` | PSI | 13.2988790138 | 0.10/0.25 | degraded |
| `velocity_1h` | PSI | 14.9511396541 | 0.10/0.25 | degraded |
| `prediction_score` | PSI | 20.5327366966 | 0.10/0.25 | degraded |

## Immutable incident reports

The two fixed-anchor runs produced matching report IDs and matching JSON/HTML bytes:

| Scenario | Report ID | JSON SHA-256 | HTML SHA-256 |
| --- | --- | --- | --- |
| Insufficient | `7e6678f4e5683d8d4856252dde50ba90f409872571d7e94db33bae2bd84411e1` | `5a13760812be7247edc78a0f0503eb88f95b6eed76c0a56a852add5d310149b0` | `4c93b1e9cefb6bad2015dcd46654fd28d6961af858acbe6d450adefae8db965c` |
| Baseline | `e6942cc42047d74a6417487df5c8e960c6dcd9d51ff9e63123be67cfa6dcf733` | `071d83c91a434782d36e1a7ba03027afb29cec1a6dfd9bd1d685c54a72910a7b` | `6b1e4cfa1152723538802fd98e7964cc8e0dc3ee033fd92572bc3fb9f5fab628` |
| Drifted | `0f60429d668929d353842ba54c3196b6865eceedb251ccdeb0b1c10db1ca1801` | `407f60f53201f28714c0e4c9c0e2d7093370cb97060c55a51351d8d10b64c57b` | `9302d98e1aac1d4b40c0e42e45890523b559b9f1761d00275cd2e06f92c08107` |

The reports show run, data quality, drift, and performance independently. Active and report-target
identities are also separate fields and matched exactly for these monitoring runs.

## Dashboard and alert evidence

In each local run, the real Streamlit in-process runner rendered both frozen repositories with zero
exceptions, seven dataframes, both identity sections, and these four state-card classes:

```text
healthy:  succeeded, valid, healthy, unknown
degraded: succeeded, valid, degraded, unknown
```

Tracked, public-safe images:

- `reports/evidence/phase-11/healthy-dashboard-evidence.png` — 1440x1120 RGB,
  SHA-256 `3260e1e3146471676cadb85165701ee0de321b3137922af69f558941461e3327`.
- `reports/evidence/phase-11/degraded-dashboard-evidence.png` — 1440x1120 RGB,
  SHA-256 `350e1f75672fb3fc5a34444b8a2ac6d523460a479c6f45c7ec928db051f9a1f2`.

Each image visibly says it is an offline report-backed snapshot, not a live-browser capture. The
generated `dashboard/healthy.json` and `dashboard/degraded.json` records preserve the AppTest
results and exact report/active identities.

The conditional local transition marker proves `drift=healthy -> drift=degraded`; its SHA-256 is
`82b950dd8d80091f1c8d036ccd16790c737e7f93eb933eae55569a5049c97751`. Its delivery status is
`not_configured`, and both `sns_configured` and `cloudwatch_configured` are false. This is local
transition evidence, not SNS/CloudWatch delivery evidence.

## Non-degradation failure evidence

The isolated insufficient-data run accepted 50 valid target records. Its monitor run succeeded,
quality is `insufficient_data`, and drift/performance are `unknown`. It is classified as
`insufficient_monitoring_data`; neither degradation nor accuracy decrease is claimed.

The controlled sink-outage path dependency-injected `LocalEventWriteError` on the real ASGI event
boundary. In both runs:

- readiness returned HTTP 200;
- prediction returned HTTP 200 for model `1.0.0`;
- exactly one sink emit call failed;
- metrics included `modelguard_event_sink_operations_total{outcome="local_failed"} 1.0` and
  `modelguard_errors_total{kind="event_sink"} 1.0`; and
- the lifespan and sink closed.

Drift and performance were not evaluated for this operational outage, and model degradation was not
claimed. The canonical post-fix outage exercises took 0.400840 seconds and 0.383785 seconds under
the throttled runner.

## Controlled recovery, kept separate from drift

Each run created a new local `1.0.1` candidate in its own ignored evidence namespace, verified the
seven-file bundle and trusted origin, atomically promoted a strict local pointer, retained the exact
`1.0.0` identity as previous, verified pointer readback, and started the real ASGI lifespan against
the promoted bundle. Readiness and version both returned HTTP 200 and served the exact promoted
identity. No network socket was opened.

Candidate manifests differed, as expected, because bundle creation time is an identity-bearing
field: run 1 produced
`653543fd8f4c25a74e10501b5b382af67f61186eb0dfe26731cac1666a8cad00`; run 2 produced
`04ff4a8b36d5517973b4add49bc145d82a442cbfb150bcf569dc49cf8061f7a3`. Candidate training took
11.487062 and 11.452758 seconds under the throttled runner. The promotion was manual, local-only,
not automatic retraining, not a metric comparison, and not described as fixing drift.

## Execution timings and repeatability

| Run | Started UTC | Completed UTC | Total |
| --- | --- | --- | ---: |
| `phase11-final-local-03` | `2026-08-11T20:13:31Z` | `2026-08-11T20:14:35Z` | 64.235558 s |
| `phase11-final-local-04` | `2026-08-11T20:14:59Z` | `2026-08-11T20:16:02Z` | 63.005936 s |

First-run measured subprocess timings were 6.921667 seconds (baseline fixture), 7.064359 seconds
(baseline monitor), 7.518711 seconds (drift fixture), 8.976152 seconds (drift monitor), 8.791414
seconds (tiny fixture), and 8.160062 seconds (insufficient monitor).

`compare-local-runs` passed with stable-projection SHA-256
`5cfc687d7c8a8c9650ee2b3939f49cf10c97699d6be173dcc44e0ab3a03001cc`. It proved the same anchor,
matching fixed-anchor report IDs/bytes, and matching states, counts, headroom, expected breaches,
dashboard images/AppTest results, alert marker, claim boundaries, and teardown state.

Expected nondeterminism was limited to wall-clock execution timestamps, measured durations, MLflow
candidate run ID, candidate creation time, and the derived candidate manifest/pointer identity. No
unexpected monitoring nondeterminism was found.

One pre-final exploratory run exposed a deterministic MLflow constraint: training cannot place its
tracking store beneath a path literally named `artifacts`. The harness now trains in an owner-only
temporary directory, copies only completed candidate evidence into the run namespace, and always
removes the temporary training tree. The 2.7 MiB failed scratch namespace was removed from `/tmp`
after diagnosis; it is not recoverable, while both final evidence namespaces remain intact. Earlier
successful development cycles were retained under ignored evidence paths but are superseded by
`phase11-final-local-03` and `phase11-final-local-04`, which ran after the temp-path security fix and
the explicit Pillow lock declaration.

## Commands and validation results

The final evidence cycles used the public Make targets with uv kept frozen/offline:

```bash
make UV_RUN='uv run --frozen --no-sync' phase11-demo-local \
  PHASE11_RUN_ID=phase11-final-local-03 \
  PHASE11_ANCHOR=2026-08-11T19:46:00Z

make UV_RUN='uv run --frozen --no-sync' phase11-demo-local \
  PHASE11_RUN_ID=phase11-final-local-04 \
  PHASE11_ANCHOR=2026-08-11T19:46:00Z

make UV_RUN='uv run --frozen --no-sync' phase11-compare-local \
  PHASE11_FIRST_SUMMARY=artifacts/phase-11-evidence/phase11-final-local-03/summary.json \
  PHASE11_SECOND_SUMMARY=artifacts/phase-11-evidence/phase11-final-local-04/summary.json

make UV_RUN='uv run --frozen --no-sync' phase11-verify-teardown \
  PHASE11_TEARDOWN_SUMMARY=artifacts/phase-11-evidence/phase11-final-local-03/summary.json

make UV_RUN='uv run --frozen --no-sync' phase11-verify-teardown \
  PHASE11_TEARDOWN_SUMMARY=artifacts/phase-11-evidence/phase11-final-local-04/summary.json
```

Results:

- Both local demo commands: passed with the exact state triplets shown above.
- Repeatability comparison: passed.
- Both teardown rechecks: passed; zero listeners/long-running processes were started, ASGI
  lifespans/sink were closed, no broken deployment remained active, and AWS was not started.
- `uv run --frozen --no-sync pytest -q --no-cov tests/unit/test_phase11_demo.py`: 6 passed in
  9.51 seconds on the final post-fix tree.
- `make UV_RUN='uv run --frozen --no-sync' lint`: 212 files formatted; Ruff passed.
- `make UV_RUN='uv run --frozen --no-sync' typecheck`: strict Mypy passed for 75 source files.
- `make UV_RUN='uv run --frozen --no-sync' verify-model`: model `1.0.0` and its trusted-origin
  manifest passed; smoke score was finite.
- `uv lock --check`: passed with 128 packages; the directly used Pillow dependency resolves to the
  already locked version `12.3.0` and remains outside runtime-image-only groups.
- `./scripts/check_shell.sh`: Bash syntax and ShellCheck passed for 21 shell files.
- `git diff --check`: passed.
- Final unrestricted `make test`: 590 passed in 70.69 seconds with 83.56% branch coverage. The
  unchanged Phase 03 measured-load threshold of 25 requests/second passed. The first unrestricted
  attempt correctly caught two stale container lock-digest defaults after Pillow became a direct
  development dependency. The three Dockerfiles and Compose default were rebound to the current
  `uv.lock` SHA-256; both focused reproducibility tests then passed, followed by the green full run.
- Final unrestricted `make security`: Bandit passed, pip-audit completed in strict hashed mode with
  no known vulnerabilities, and the basic secret/file check passed.
- Final unrestricted `make security-scan`: pinned Actionlint, ShellCheck, Checkov, Gitleaks, and
  Trivy all passed. Fresh Checkov results were 475 Terraform, 317 Dockerfile, and 956 GitHub Actions
  checks passed with zero failures. Gitleaks enforced the one owned historical exception and found
  no current-worktree leak; Trivy filesystem and configuration scans passed. Sanitized SARIF is
  under ignored `artifacts/security/sarif/`.

Earlier restricted-sandbox attempts could not complete network- or Docker-backed gates and observed
CPU-throttled load measurements; those attempts remain historical diagnostics and are superseded by
the unrestricted green closure gates above. The final source review made the already-transitive
Pillow package an explicit development dependency because the Phase 11 renderer imports it directly;
`uv lock --check` validated the resolved Pillow artifact and the container reproducibility defaults
bind the resulting lock SHA-256.

## AWS and teardown verification

AWS Phase 11 status is `not_run`: the demo was not deployed when this phase began. This phase made
zero AWS mutations and did not run `terraform apply`, `terraform destroy`, an ECS task, model
pointer promotion, or notification enrollment. The repository records Phase 10 teardown as already
complete with zero disposable residuals; it was not live-reverified in this restricted run.

Both local summaries and subsequent teardown commands prove:

```text
network_listeners_started=0
long_running_local_processes_started=0
asgi_lifespans_closed=true
controlled_outage_sink_closed=true
deliberately_broken_deployment_active=false
aws_environment_started=false
aws_environment_left_running=false
```

## Evidence paths

Tracked public evidence:

```text
docs/DEMO_RUNBOOK.md
reports/evidence/phase-11/README.md
reports/evidence/phase-11/healthy-dashboard-evidence.png
reports/evidence/phase-11/degraded-dashboard-evidence.png
reports/phase-11.md
```

Complete ignored evidence:

```text
artifacts/phase-11-evidence/phase11-final-local-03/
artifacts/phase-11-evidence/phase11-final-local-04/
artifacts/phase-11-evidence/local-repeatability.json
```

Summary SHA-256 values are
`1e0ec875a161aa75b1312aba09e242028acde206236356da05015ba2934dbdee` (run 1),
`39d8389871140321065a342849680ad2e60e69d5ffa2302608cdeb3fbb511a24` (run 2), and
`b6385da1abf756439cb44b702406124e38ad9fb3a9e75943ccd349554359b063` (repeatability record).

## Residual risks

- There is no fresh live-browser Phase 11 screenshot because the sandbox denies socket creation;
  evidence is AppTest plus visibly labeled offline snapshots. The runbook gives exact unrestricted
  host commands for a real browser capture.
- There is no Phase 11 SNS/CloudWatch delivery evidence because local mode does not configure those
  sinks and the AWS environment was already destroyed.
- Performance is intentionally unknown without labels. This phase cannot support an accuracy,
  precision, recall, calibration, or business-outcome change claim.
- AWS teardown is based on the completed Phase 10 authoritative record, not a fresh live inventory.
- No local release gate remains unresolved. The 25 requests/second performance threshold passed on
  the unrestricted closure host and was not weakened.

## Exact next manual action

None for Phase 11. The commit containing this report closes the phase with message
`feat: add repeatable Phase 11 monitoring recovery demo`. Phase 12 remains `not_started` and requires
separate user authorization.

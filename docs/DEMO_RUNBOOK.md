# Phase 11 Healthy-to-Degraded Demo Runbook

## What this proves

This runbook executes one synthetic, local-only monitoring story with three explicit UTC half-open
windows and one separate deployment-control story:

1. 1,000 stationary events produce `run=succeeded`, `data_quality=valid`, `drift=healthy`, and
   `performance=unknown`. The 500 accepted-event minimum therefore has deterministic headroom of
   `+500`.
2. 1,000 shifted events in the next, non-overlapping window produce `run=succeeded`,
   `data_quality=valid`, `drift=degraded`, and `performance=unknown`.
3. Fifty valid events in an earlier isolated report repository produce
   `data_quality=insufficient_data` and `drift=unknown`. This is not model degradation.
4. A controlled event-sink exception leaves readiness and prediction at HTTP 200 while emitting
   the `local_failed` and `event_sink` counters. This is an operational sink outage, not model
   degradation.
5. A separate local-only control-plane exercise trains version `1.0.1`, verifies the seven-file
   bundle from a trusted local origin, atomically promotes a strict pointer from `1.0.0` to `1.0.1`,
   preserves the previous identity, and proves readiness/version through the real ASGI app. It uses
   integrity and readiness only; it makes no accuracy-improvement claim and is not presented as a
   response to drift.

No labels are configured in the required path. Consequently, performance remains `unknown`, label
coverage remains `null`, and neither input drift nor prediction-distribution drift is described as
an accuracy decrease. All traffic is deterministic synthetic data.

## Prerequisites

Run from the repository root with Python 3.12, uv 0.12.x, and the verified local bundle present:

```bash
./scripts/verify_environment.sh
make setup
make verify-model
```

If `artifacts/model-bundles/1.0.0/` is absent, run `make train` once. Training refuses to overwrite
an existing semantic version.

The Phase 11 harness does not require Docker, AWS credentials, a browser, or a network listener. It
uses the real monitor CLI, dashboard repository/parser, Streamlit's in-process app runner, API ASGI
lifespan, event-sink boundary, and bundle verifier. Generated evidence is owner-only under the
ignored `artifacts/phase-11-evidence/` root.

## Execute the demo twice locally

Resolve one explicit UTC anchor just behind wall clock and reuse that exact value for both runs. The
baseline report is one hour older than the anchor, so complete both runs before the configured
two-hour staleness boundary:

```bash
PHASE11_ANCHOR="$(date -u -d '1 minute ago' +%Y-%m-%dT%H:%M:00Z)"
printf 'Phase 11 anchor: %s\n' "$PHASE11_ANCHOR"

make phase11-demo-local \
  PHASE11_RUN_ID=phase11-local-01 \
  PHASE11_ANCHOR="$PHASE11_ANCHOR"

make phase11-demo-local \
  PHASE11_RUN_ID=phase11-local-02 \
  PHASE11_ANCHOR="$PHASE11_ANCHOR"
```

Each command emits one final JSON object. The variable timestamps, durations, and identities are
shown as placeholders below; the state values are exact:

```json
{
  "duration_seconds": 0.0,
  "run_id": "phase11-local-01",
  "states": {
    "baseline": {
      "data_quality": "valid",
      "drift": "healthy",
      "performance": "unknown",
      "run": "succeeded"
    },
    "drifted": {
      "data_quality": "valid",
      "drift": "degraded",
      "performance": "unknown",
      "run": "succeeded"
    },
    "insufficient": {
      "data_quality": "insufficient_data",
      "drift": "unknown",
      "performance": "unknown",
      "run": "succeeded"
    }
  },
  "status": "passed",
  "summary": ".../artifacts/phase-11-evidence/phase11-local-01/summary.json"
}
```

Run IDs are create-only evidence namespaces. Choose new lowercase IDs for a later execution; do not
delete or merge prior inputs to make a rerun pass.

## Compare deterministic evidence

```bash
make phase11-compare-local \
  PHASE11_FIRST_SUMMARY=artifacts/phase-11-evidence/phase11-local-01/summary.json \
  PHASE11_SECOND_SUMMARY=artifacts/phase-11-evidence/phase11-local-02/summary.json
```

Expected output contains:

```json
{
  "monitoring_report_ids_and_hashes_match": true,
  "same_anchor": true,
  "states_counts_headroom_and_breaches_match": true,
  "status": "passed"
}
```

The comparison deliberately excludes wall-clock timings, MLflow run IDs, candidate creation
timestamps, and the resulting candidate manifest digest. It requires the fixed-anchor monitoring
report IDs, JSON/HTML hashes, states, record counts, sample headroom, and expected metric breaches
to match exactly.

## Exact window and shift contract

For an anchor `A` and a one-hour monitoring policy, the harness resolves:

| Scenario | UTC event-time window | Explicit as-of | Report repository |
| --- | --- | --- | --- |
| Insufficient | `[A-3h, A-2h)` | `A-2h + grace` | isolated |
| Baseline | `[A-2h, A-1h)` | `A-1h + grace` | transition history |
| Drifted | `[A-1h, A)` | `A + grace` | transition history |

The checked-in local demo policy has zero finalization grace, so as-of equals window end. Baseline
and drifted traffic are written to separate event directories; they never share a `latest` input
window. The shifted fixture applies these explicit transformations:

| Feature | Transformation |
| --- | --- |
| `amount` | `min(25000, amount * 20 + 5000)` |
| `velocity_1h` | `min(30, velocity_1h + 15)` |
| `distance_from_home_km` | `min(1000, distance_from_home_km + 400)` |
| `device_risk_score` | `min(1.0, 0.8 + 0.2 * value)` |
| `merchant_risk_score` | `min(1.0, 0.8 + 0.2 * value)` |
| `is_new_device` | `true` |
| `country_code` | `"BR"` |
| `device_type` | `"tablet"` |

The harness requires degraded-boundary breaches for PSI on `amount`, `velocity_1h`,
`distance_from_home_km`, `device_risk_score`, `merchant_risk_score`, and `prediction_score`; it also
requires degraded Jensen-Shannon distance for `country_code` and `device_type`. The locked-decision
Jensen-Shannon signal must cross the warning boundary while remaining below degraded. Exact values
are recorded under `expected_breached_metrics` in each drifted summary.

## Evidence paths

For run ID `<run-id>`, inspect:

```text
artifacts/phase-11-evidence/<run-id>/summary.json
artifacts/phase-11-evidence/<run-id>/commands.json
artifacts/phase-11-evidence/<run-id>/scenarios/baseline/summary.json
artifacts/phase-11-evidence/<run-id>/scenarios/drifted/summary.json
artifacts/phase-11-evidence/<run-id>/scenarios/insufficient/summary.json
artifacts/phase-11-evidence/<run-id>/monitoring/transition-reports/history/<window>/<id>.json
artifacts/phase-11-evidence/<run-id>/monitoring/transition-reports/history/<window>/<id>.html
artifacts/phase-11-evidence/<run-id>/monitoring/insufficient-reports/history/<window>/<id>.json
artifacts/phase-11-evidence/<run-id>/monitoring/insufficient-reports/history/<window>/<id>.html
artifacts/phase-11-evidence/<run-id>/alerts/summary.json
artifacts/phase-11-evidence/<run-id>/sink-outage/summary.json
artifacts/phase-11-evidence/<run-id>/recovery/summary.json
artifacts/phase-11-evidence/<run-id>/dashboard/healthy.json
artifacts/phase-11-evidence/<run-id>/dashboard/degraded.json
artifacts/phase-11-evidence/<run-id>/dashboard/healthy-dashboard-evidence.png
artifacts/phase-11-evidence/<run-id>/dashboard/degraded-dashboard-evidence.png
```

The two PNGs are intentionally labeled offline, report-backed dashboard snapshots. They are
generated from the validated dashboard repository/parser because restricted execution environments
may prohibit local sockets and headless-browser crash reporting. They are not represented as live
browser screenshots. The fresh `dashboard/*.json` artifacts also prove the real Streamlit script
rendered all four state-card classes in process with zero exceptions. The prior real-browser
reference captures remain at:

```text
reports/evidence/phase-06/healthy-dashboard.png
reports/evidence/phase-06/degraded-dashboard.png
```

On an unrestricted host, immediately after the Phase 11 run and before staleness, the frozen
repositories can be rendered by the real server with:

```bash
LOCAL_REPORT_DIR=artifacts/phase-11-evidence/phase11-local-01/dashboard/healthy-repository \
  MONITORING_CONFIG_PATH=configs/phase-07-monitoring.json \
  DASHBOARD_PORT=18511 make dashboard

LOCAL_REPORT_DIR=artifacts/phase-11-evidence/phase11-local-01/dashboard/degraded-repository \
  MONITORING_CONFIG_PATH=configs/phase-07-monitoring.json \
  DASHBOARD_PORT=18512 make dashboard
```

Open `http://127.0.0.1:18511` and `http://127.0.0.1:18512`. Stop both processes after capture.

## Alert and AWS boundary

The local transition produces a conditional alert marker proving
`drift=healthy -> drift=degraded`. Its send result is exactly `not_configured`; it does not claim
SNS delivery or exactly-once notification. CloudWatch is likewise not configured in local mode.

Check whether an AWS Phase 11 run is allowed:

```bash
jq '{deployed:.phase_10.live_deployment_executed,
     destroyed:.phase_10.live_deployment_destroyed,
     residuals:.phase_10.disposable_demo_resource_residuals}' \
  tasks/phase_status.json
```

If `destroyed` is `true` and `residuals` is `0`, do not recreate infrastructure merely to satisfy
this runbook. Record AWS Phase 11 as not run because the environment is not deployed. Historical
Phase 10 Firehose, CloudWatch EMF, alarm inventory, SNS enrollment, and teardown evidence remains
historical Phase 10 evidence; it must not be relabeled as a Phase 11 healthy-to-degraded AWS run.

If a later operator explicitly redeploys the demo through the guarded Phase 10 workflow, use the
scheduled one-shot monitor contract and capture the immutable S3 JSON/HTML pair, `MonitorCompletions`
EMF event, alarm state, SNS transition result, task exit category, dashboard transition, and a fresh
post-destroy inventory. Do not run `terraform apply`, `terraform destroy`, pointer promotion, or an
ad hoc ECS task from this local runbook.

## Verify local closure

```bash
make phase11-verify-teardown \
  PHASE11_TEARDOWN_SUMMARY=artifacts/phase-11-evidence/phase11-local-01/summary.json

make phase11-verify-teardown \
  PHASE11_TEARDOWN_SUMMARY=artifacts/phase-11-evidence/phase11-local-02/summary.json
```

Expected output has `status=passed`, zero long-running processes, zero network listeners, no broken
deployment active, and `aws_environment_started=false`. The harness opens no listener or background
process; both ASGI lifespans and the controlled outage sink close before the summary is published.
Generated evidence and candidate bundles remain local ignored files, not running services.

## Validation gate

Run the focused test first, then the phase and repository gates:

```bash
uv run --frozen --no-sync pytest -q --no-cov tests/unit/test_phase11_demo.py
make lint
make typecheck
make test
make security
git diff --check
```

Do not weaken a gate, erase an evidence namespace, claim label-backed performance without labels,
or describe insufficient data/sink failure as model degradation.

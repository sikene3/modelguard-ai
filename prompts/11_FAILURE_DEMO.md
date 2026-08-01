# Phase 11 — Healthy-to-Degraded Demo and Recovery Evidence

## Recommended mode
GPT-5.6 Sol, Max.

## Objective
Create and execute a repeatable demonstration that proves monitoring and recovery behavior without fabricating model-accuracy claims.

## Required implementation/evidence
- Baseline traffic scenario with deterministic accepted-sample headroom above the minimum, explicit
  UTC window end/as-of, and a monitor run that proves `run=succeeded`, `data_quality=valid`, and
  `drift=healthy` (`performance=unknown` unless the optional complete label fixture is used).
- Drifted scenario in a separate non-overlapping UTC window with explicit feature changes and
  expected breached drift metrics; never mix baseline and shifted traffic in one `latest` window.
- CLI/script to trigger or wait for monitor execution.
- Dashboard transition evidence.
- JSON and HTML incident reports.
- Show run/data-quality/drift/performance as separate dimensions. If labels are absent, performance
  remains unknown; if delayed labels are demonstrated, record adequacy/coverage.
- SNS/CloudWatch evidence where configured.
- Controlled recovery: either validated model promotion or ECS bad-deployment rollback demonstration. Keep the two stories separate from drift unless causally appropriate.
- Include insufficient-data and event-sink-outage evidence without calling either model degradation.
- `docs/DEMO_RUNBOOK.md` with exact commands and expected outputs.
- `reports/phase-11.md` containing timings, screenshots paths, and any nondeterminism found.

## Constraints
- Do not claim accuracy decreased without labels.
- Do not cause real malicious traffic or use real customer data.
- Do not leave a deliberately broken deployment active.
- Do not leave the AWS environment running after evidence capture unless explicitly intended.

## Validation
Run the demo twice locally. Run once on AWS if the demo environment is deployed. Verify teardown afterward.

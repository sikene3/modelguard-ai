# ModelGuard AI demo script

## Recording target

**Length:** 4 minutes 15 seconds (acceptable range: 3–5 minutes)<br>
**Mode:** local, using synthetic data and the committed/reproducible Phase 11 evidence<br>
**Outcome:** show a healthy finalized window becoming degraded while performance remains honestly
unknown, then connect that evidence to the guarded AWS design and teardown record

Do not imply that the historical AWS environment is currently live. Do not show a private endpoint,
IP address, account identifier, ARN, email address, bearer value, `.env`, Terraform plan/state, raw
cloud receipt, shell history, or notification details.

## Pre-recording setup

From a clean clone, complete the [README quickstart](../README.md#clean-local-quickstart). For the
fixed evidence flow, the shorter recording path may reuse the tracked Phase 11 screenshots and
evidence index. Confirm the following before recording:

```bash
make verify-model
uv run python -m modelguard.monitoring.cli status \
  --as-of 2026-01-01T02:10:00Z
```

Start the API and dashboard only on loopback in separate terminals:

```bash
make api
```

```bash
make dashboard
```

Use a clean terminal profile with no account/environment prompt metadata. Close password managers,
notifications, email, cloud consoles, and unrelated tabs. Use only synthetic request data.

## Shot-by-shot script

### 0:00–0:25 — Outcome and failure prevented

**Show:** repository title, then the architecture PNG.<br>
**Say:**

> I built ModelGuard AI to prevent two quiet failures: serving an incomplete or mismatched model
> bundle, and presenting distribution drift as an accuracy problem before labels exist. Everything
> in this demo uses synthetic data, and the AWS environment was temporary.

### 0:25–0:55 — Architecture and identity path

**Show:** [`assets/modelguard-architecture.png`](assets/modelguard-architecture.png). Trace client →
API → event sink → monitor → report → dashboard; then point to SSM/S3 identity and GitHub OIDC.<br>
**Say:**

> A prediction is tied to a model version, manifest, input schema, and event schema. In AWS, the API
> loads exact versioned bundle objects, Firehose batches events to S3, and a scheduled one-shot task
> writes immutable reports. The dashboard reads evidence; it does not recalculate a healthier state.

### 0:55–1:30 — Verified model and prediction

**Show:** a clean `make verify-model` result, `/health/ready`, `/version`, and one response to the
committed request. Crop to bounded JSON fields.<br>
**Say:**

> Readiness succeeds only after the seven-file bundle passes structure, checksum, schema, lineage,
> and trusted-origin checks. A valid response carries a server request ID, score, locked-threshold
> decision, model version, and latency. This is synthetic risk scoring, not a real fraud claim.

### 1:30–2:00 — Healthy window

**Show:**
[`../reports/evidence/phase-11/healthy-dashboard-evidence.png`](../reports/evidence/phase-11/healthy-dashboard-evidence.png).<br>
**Say:**

> The stationary window accepted 1,000 events against a minimum of 500. The monitor succeeded, data
> quality was valid, and drift was healthy. Performance is still unknown because no labels were
> configured.

### 2:00–2:45 — Injected drift and incident evidence

**Show:** run the shifted fixture/monitor commands from the README, then show
[`../reports/evidence/phase-11/degraded-dashboard-evidence.png`](../reports/evidence/phase-11/degraded-dashboard-evidence.png).<br>
**Say:**

> The adjacent shifted window also accepted 1,000 target events. Numeric and categorical inputs plus
> the prediction-score distribution crossed the versioned thresholds, so drift became degraded. The
> JSON and HTML reports are immutable and reproducible. I still do not call this an accuracy loss:
> label-backed performance remains unknown.

### 2:45–3:20 — Failure semantics

**Show:** the Phase 11 evidence index sections for insufficient data, sink outage, and recovery.<br>
**Say:**

> A 50-event window becomes insufficient data, never healthy. A controlled event-sink outage leaves
> a valid prediction at HTTP 200 but emits a failure metric and log. Corrupt bundle bytes block
> readiness. Model promotion is a separate validated control, not an automatic reaction to drift.

### 3:20–3:55 — AWS, security, and observability

**Show:** architecture again, then safe repository views of workflow/IAM/alarm source files. Do not
show live cloud receipts.<br>
**Say:**

> The temporary AWS demo used private Fargate tasks, restricted load-balancer ingress, digest-pinned
> images, GitHub OIDC, reviewed Terraform plans, CloudWatch and bounded EMF signals. The release gate
> combines tests, type and lint checks, dependency audit, IaC checks, secret scanning, and image
> scanning.

### 3:55–4:15 — Cost, teardown, and close

**Show:** README cost/teardown and limitations sections.<br>
**Say:**

> This is deliberately not an HA or permanent service: one task per service, one NAT Gateway, no
> automatic retraining, and no real customer data. I captured the AWS evidence, applied a guarded
> destroy plan, and recorded zero disposable demo resources. The repository maps every public claim
> to evidence.

## Capture outputs

- Full recording: [`assets/demo/modelguard-demo.mp4`](assets/demo/modelguard-demo.mp4), 1280×720,
  4 minutes 15 seconds.
- Short GIF: [`assets/demo/modelguard-drift.gif`](assets/demo/modelguard-drift.gif), 15 seconds,
  derived directly from the healthy → monitoring → degraded interval of the same MP4.
- Four publishable stills: architecture, prediction/readiness, healthy dashboard, degraded
  dashboard.
- Optional captions/transcript based on this file.

The real capture passed [`screenshot-checklist.md`](screenshot-checklist.md). The README and claim
CL-29 use the exact reviewed paths and hashes; neither asset is presented as a live AWS session.

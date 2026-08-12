# ModelGuard AI Case Study

## Outcome

I turned a notebook-shaped synthetic fraud classifier into an evidence-driven MLOps demo that
refuses unverified model bytes and surfaces distribution drift without calling it an accuracy loss.
The local demo moves from a healthy finalized window to a degraded shifted window, preserves
immutable incident reports, and keeps label-backed performance `unknown` when labels are absent.
The same contracts were deployed once in a restricted, temporary AWS environment and the disposable
resources were then destroyed.

All data in this project is synthetic. The cloud deployment was a short-lived portfolio demo, not a
permanent service or a claim of production readiness.

## Problem

A model endpoint can look healthy while two important failures remain invisible:

1. the service may load stale, partial, mixed-version, or otherwise unverified model artifacts; and
2. the incoming population can change while infrastructure health checks continue to pass.

The tempting response to the second problem is to call drift “accuracy degradation.” That is not
supported without labels. I wanted the project to demonstrate the more useful engineering outcome:
trace exactly which model and schema produced each event, detect distribution changes in a
reconciled window, preserve incident evidence, and keep performance conclusions separate.

## Constraints

- The dataset had to be deterministic and synthetic; no real payment, identity, or customer data
  could enter source, logs, screenshots, or cloud evidence.
- The MVP had to be finishable and understandable. Kubernetes, a feature store, automatic
  retraining, an authentication platform, and multi-Region design were out of scope.
- Core behavior had to run locally without AWS credentials or hidden network calls in tests.
- The AWS environment had to be restricted, cost-aware, staged, reviewable, and destroyable.
- Model evaluation needed explicit leakage boundaries: persisted split before fitting, calibration
  on training only, threshold selection on validation only, and one held-out test evaluation per
  training invocation after threshold lock.
- Monitoring needed deterministic event-time windows, identity filtering, deduplication, exact
  record reconciliation, and honest small-sample/label states.
- Public claims had to be backed by tracked reports, tests, commands, or real captures.

## Decisions

### ECS Fargate instead of Kubernetes

Three small container roles—API, dashboard, and one-shot monitor—did not justify EKS operational
overhead. ECS Fargate made task identities, private networking, deployment circuit breakers, and
scheduled execution visible while keeping the demo bounded. One task per service and one NAT Gateway
reduce cost, but deliberately do not provide high availability.

### Immutable model identity instead of a mutable model path

I bound a semantic model version to a manifest digest and, in AWS, exact S3 object VersionIds. The
seven-file bundle includes the serialized pipeline, manifest, input schema, metrics, threshold,
baseline, and checksum index. Startup stages downloads into an empty bounded directory, verifies
every artifact and cross-artifact identity, then installs atomically before readiness can succeed.

### Firehose-to-S3 event capture instead of a streaming platform

The monitor consumes finalized batches, so Kinesis Data Firehose and GZIP JSONL in date/hour S3
prefixes were proportionate. Producer acceptance, downstream delivery, and S3 freshness remain
separate signals. An event-sink failure is observable but does not make a valid prediction fail
closed.

### Deterministic batch drift instead of automatic retraining

The monitor evaluates UTC half-open windows after a finalization grace, freezes the input snapshot,
filters to one target identity, handles duplicate/conflicting IDs, and reconciles every record as:

```text
raw = rejected + outside_window + known_non_target + duplicate + accepted_target
```

Numeric PSI, categorical Jensen–Shannon distance, prediction-score/decision distributions,
missingness, and schema violations vote only within their documented policy. Automatic retraining is
excluded because drift alone does not prove that a replacement is better.

### Four independent status dimensions

Monitor execution, data quality, drift, and label-backed performance can fail or remain unknown
independently. Small samples become `insufficient_data`; missing labels leave performance `unknown`;
stale or missing reports never silently render as healthy.

## Implementation

### Data and MLOps

The training workflow generates 5,000 synthetic rows from committed configuration, validates them,
persists a hashed stratified split, fits a scikit-learn preprocessing/classification pipeline,
cross-fits calibration on training rows, locks a synthetic 10:1 false-negative cost threshold on
validation, evaluates the held-out test once per training invocation after that lock, logs to local
MLflow, and publishes the immutable bundle and training-reference baseline.

The canonical synthetic test result is deliberately not polished: average precision was about
0.408 against 0.188 prevalence (about 2.17× lift), while the locked cost rule selected a low
threshold and a high false-positive rate. Those values characterize only the generator and demo
policy; they are not real fraud probabilities or economics.

### Inference and event lineage

FastAPI exposes liveness, readiness, version, metrics, and a strict prediction contract. Successful
responses carry a request ID, score, locked-threshold decision, model version, and latency. Each
event carries its own ID plus the exact model, manifest, input-schema, and event-schema identities.
Local writes rotate atomically from an open file to closed JSONL; AWS writes use Firehose.

### Monitoring and dashboard

The same pure monitoring contract runs locally and in the one-shot AWS task. Reports are strict JSON
plus readable HTML; canonical report identity does not depend on input file names, file boundaries,
or enumeration order. History is immutable and `latest` advances only to a newer window. The
read-only Streamlit dashboard presents source health separately from the four persisted monitor
states and shows identity, counts, top drift signals, and distributions.

### AWS, DevOps, and security

Terraform separates retained bootstrap/audit controls from the disposable demo. GitHub Actions uses
OIDC rather than stored AWS keys. Deployment first creates prerequisites with runtimes disabled,
then binds scanned images and the model to immutable identities, and finally applies a reviewed
activation plan. Private ECS tasks sit behind restricted ALB ingress. CloudWatch native metrics,
bounded-dimension EMF events, logs, and alarms cover application and monitor failure modes.

Local and CI gates include Ruff, strict Mypy, Pytest with branch coverage, Bandit, hashed
`pip-audit`, actionlint, ShellCheck, Checkov, Gitleaks, and Trivy. Runtime containers are non-root;
deployment images and base images are referenced by digest.

## Failure demo

The fixed Phase 11 run used adjacent, non-overlapping windows and the same target identity:

| Scenario | Accepted target events | Run | Data quality | Drift | Performance |
| --- | ---: | --- | --- | --- | --- |
| Insufficient | 50 | succeeded | insufficient_data | unknown | unknown |
| Stationary baseline | 1,000 | succeeded | valid | healthy | unknown |
| Shifted inputs | 1,000 | succeeded | valid | degraded | unknown |

The shifted window degraded numeric PSI for multiple input features and prediction score, plus
categorical Jensen–Shannon distance for country and device type. Because no labels were configured,
the demo makes no accuracy, precision, recall, calibration-change, causal, or business-impact claim.

Two other failures demonstrate different semantics:

- A controlled local event-sink outage kept a valid prediction at HTTP 200 while logging/counting
  the sink failure. That is an operational data-capture outage, not model degradation.
- A corrupt or incomplete bundle prevents readiness. A separate validated local model promotion
  proves the recovery mechanism, but is not presented as a drift response or a better model.

## Evidence

- [Phase 02](../reports/phase-02.md): deterministic training, split/leakage boundaries, held-out
  metrics, MLflow, and bundle verification.
- [Phase 03](../reports/phase-03.md) and [Phase 04](../reports/phase-04.md): API, load, redaction,
  event schema, and sink behavior.
- [Phase 05](../reports/phase-05.md): monitoring math, states, persistence, reconciliation, and
  report contracts.
- [Phase 07](../reports/phase-07.md): non-root images, Compose scenarios, image scanning, and local
  cleanup.
- [Phase 09.1](../reports/phase-09-1.md): reproducible release scanner identities and results.
- [Phase 10](../reports/phase-10.md): historical restricted AWS deployment, Firehose/report/EMF
  readback, alarm/source inventory, and zero disposable resources after guarded teardown.
- [Phase 11](../reports/phase-11.md) and its
  [tracked evidence index](../reports/evidence/phase-11/README.md): fixed-window states, report
  hashes, repeatability, screenshots, outage semantics, and local teardown.
- [Claims ledger](../portfolio/claims-ledger.md): claim-by-claim public evidence and exclusions.

## Outcome

The project now demonstrates a coherent path from synthetic data generation to a versioned model,
bounded API, lineage-preserving event stream, deterministic drift incidents, read-only operations
view, guarded AWS delivery, and teardown. More importantly, its failure behavior is explicit:
unverified model bytes block readiness; small or invalid windows do not become healthy; missing
labels do not become performance claims; and sink failures remain visible without silently changing
prediction semantics.

The demonstrated outcome is engineering evidence and failure containment—not a claim that the model
improves real fraud losses.

## Limitations

- Synthetic, independently generated tabular data cannot establish real-world validity, fairness,
  stability, or economic benefit.
- AWS delayed-label collection is not implemented. Label-backed performance in the tracked demo is
  `unknown`.
- The service is single-Region, desired count one, and dependent on one NAT Gateway. It is not HA
  and does not claim zero downtime.
- Monitoring is scheduled and windowed, not real-time.
- There is no automatic retraining, automatic promotion, feature store, Kubernetes, multi-tenant
  authentication platform, or multi-Region failover.
- The temporary AWS application environment was destroyed. The retained budget and audit/bootstrap
  controls are intentional and can still carry limited cost/maintenance responsibility.
- The Phase 11 images are visibly labeled offline, report-backed snapshots. The reviewed 4:15
  current-run video and its 15-second healthy-to-degraded GIF are genuine local captures governed
  by the screenshot checklist; neither is presented as live AWS evidence.

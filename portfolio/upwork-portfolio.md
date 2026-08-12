# Upwork portfolio item

## Title

AWS MLOps Reliability Demo: Verified Models, Drift Evidence, and Guarded Delivery

## Short description

I designed and implemented a compact AWS MLOps portfolio system that prevents unverified model
artifacts from becoming ready and detects input/prediction-distribution drift without overstating
unlabeled performance. It covers deterministic synthetic training, a versioned FastAPI service,
prediction-event lineage, batch drift reports, a read-only operations dashboard, Terraform, CI/CD,
security scanning, and teardown evidence.

## The problem I solved

Infrastructure health alone cannot answer which model produced a prediction, whether recent traffic
matches the training reference, or whether monitoring evidence is complete. I built explicit
contracts for model identity, event identity, finalized windows, record reconciliation, and
independent run/data-quality/drift/performance states.

## What I delivered

- Deterministic synthetic data generation, persisted train/validation/test membership, train-only
  calibration, validation-only threshold selection, held-out evaluation, and MLflow tracking.
- A checksummed seven-file model bundle with schema, threshold, baseline, metrics, and manifest
  lineage; readiness blocks corrupt, partial, or mismatched artifacts.
- FastAPI prediction, health, version, and local metrics endpoints with strict Pydantic contracts,
  bounded request handling, structured logging, and redaction rules.
- Local atomic JSONL and AWS Firehose-to-S3 prediction events that retain exact model, manifest,
  input-schema, and event-schema identity.
- Deterministic PSI/Jensen–Shannon monitoring, immutable JSON/HTML reports, explicit small-sample and
  missing-label states, transition alerting, and a Streamlit evidence dashboard.
- Three non-root container roles, digest-pinned images, Terraform-managed ECS Fargate, private tasks,
  restricted ALB ingress, CloudWatch/EMF alarms, GitHub Actions OIDC, and guarded staged activation.
- A repeatable healthy-to-degraded demo, sink-outage/corrupt-bundle scenarios, claims ledger, cost
  boundary, and post-demo teardown record.

## Evidence-backed result

The fixed local evidence run accepted 1,000 target events in a stationary window and 1,000 in an
adjacent shifted window. Drift changed from `healthy` to `degraded`; performance stayed `unknown`
because labels were not configured. A separate 50-event window was correctly classified as
`insufficient_data`. The temporary AWS deployment passed restricted API/dashboard checks and
monitoring evidence readback before the disposable resources were destroyed.

## Skills demonstrated

AWS architecture and IAM · MLOps lifecycle design · Python/FastAPI · scikit-learn/MLflow ·
Terraform · Docker · GitHub Actions OIDC · CI/CD and security scanning · event/data contracts ·
drift monitoring · CloudWatch observability · incident evidence and teardown

## Honest scope boundary

All data is synthetic. This is a production-style demonstration, not a permanent production service.
It does not claim high availability, zero downtime, real-world fraud performance, automatic
retraining, real-time drift decisions, or an authentication platform. The AWS environment may be
temporary or absent when this portfolio item is viewed.

## Suggested attachments

- [`assets/modelguard-architecture.png`](assets/modelguard-architecture.png)
- [`../reports/evidence/phase-11/healthy-dashboard-evidence.png`](../reports/evidence/phase-11/healthy-dashboard-evidence.png)
- [`../reports/evidence/phase-11/degraded-dashboard-evidence.png`](../reports/evidence/phase-11/degraded-dashboard-evidence.png)
- [`../docs/CASE_STUDY.md`](../docs/CASE_STUDY.md)

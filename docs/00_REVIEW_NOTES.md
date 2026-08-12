# Launch Kit Review Results

This document records the pre-implementation review of the original launch kit.

## Verdict

The original kit was organized and strong as a starting point, but it was not ready for
high-quality implementation without repair. The reviewed version was ready for Phase 00 followed by
incremental implementation; that verdict did not mean that the application itself had already been
built.

## Most important gaps closed

1. Prevented data leakage by requiring a fixed split before training, calibration within training
   data, threshold selection on validation data, and one held-out test evaluation per training
   invocation after threshold lock.
2. Defined score and metric semantics, including average precision versus prevalence, calibration,
   the synthetic cost rule, lineage, and bundle verification before joblib loading.
3. Separated run, data-quality, drift, and label-backed performance states instead of using a
   misleading aggregate state.
4. Defined a precise monitoring contract covering UTC windows and grace periods, deduplication,
   model-version purity, count reconciliation, PSI, Jensen-Shannon distance, delayed labels, and
   idempotent reports and alerts.
5. Defined privacy-safe event contracts with stable IDs, UTC timestamps, JSONL, bounded retries,
   Firehose GZIP/date-hour delivery, and no secrets.
6. Defined API boundaries for request bodies, concurrency, load targets, log redaction, and the
   restricted-CIDR/shared-token demo gate.
7. Added AWS safety boundaries for private tasks, restricted CIDRs, two AZs with one NAT and an S3
   endpoint, separated IAM roles, exact OIDC claims, independent state bootstrap, budgets,
   retention, guarded destroy, and an alarm matrix.
8. Defined CI/CD as build-once and digest-promotion with pinned actions/images, protected serialized
   deployments, explicit rollback targets, and no automatic rollback caused by drift.
9. Required portfolio packaging before the final Ultra audit and added a claims ledger to prevent
   unsupported claims.
10. Removed High and Medium from the execution plan: XHigh is the minimum, Max is for highly coupled
    work, and Ultra is reserved for the two independent audits.

## Scope decisions

The following remain outside the MVP: EKS, Kafka, Airflow, a feature store, hosted MLflow,
automatic retraining, real customer or payment data, a public anonymous demo, multi-region
architecture, and a full authentication platform.

## Original pre-implementation instruction

The original launch kit required a Phase 00 Ultra review before any application code, followed by a
human review of its report and a clear GO decision before Phase 01. That review is preserved in
`reports/phase-00-architecture-review.md`.

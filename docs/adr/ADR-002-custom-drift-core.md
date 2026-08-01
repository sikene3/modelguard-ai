# ADR-002: Implement a small transparent drift core

## Status
Accepted.

## Decision
Implement PSI and Jensen-Shannon **distance** (square root of base-2 divergence) directly with
reference-vector tests. Numeric bins come from the training baseline; epsilon smoothing,
renormalization, UTC event-time windows/finalization grace, special buckets, target-version purity,
and edge states are explicit. Grace is not represented as a row-level delivery-lateness metric.

## Rationale
Transparent math, deterministic tests, and small dependencies make the project easier to explain and maintain.

## Consequences
The dashboard/report layer owns presentation only. Thresholds, bins, smoothing, windows,
deduplication, identities, exact count reconciliation, and limitations must be versioned; drift never
stands in for performance. A run targets one exact model identity and excludes/counts verified known
non-target identities rather than invalidating a normal rolling-deployment window.

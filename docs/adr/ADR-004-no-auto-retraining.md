# ADR-004: No automatic retraining in MVP

## Status
Accepted.

## Decision
The system detects drift, produces evidence, alerts, and supports controlled model promotion. It does not automatically retrain or promote models.

## Rationale
Drift does not prove that retraining is correct, and labels may be unavailable. Automatic promotion would expand scope and weaken safety.

## Consequences
The demo shows controlled response and rollback/promotion rather than a fully autonomous loop.

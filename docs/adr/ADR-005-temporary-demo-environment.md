# ADR-005: Treat AWS as a temporary demo environment

## Status
Accepted.

## Decision
Deploy only long enough to validate and record evidence, then destroy the demo environment.

## Rationale
The portfolio value comes from reproducibility and evidence, not from paying continuously for idle infrastructure.

## Consequences
Documentation must include repeatable deployment and teardown steps. Public endpoints are not guaranteed to remain available.

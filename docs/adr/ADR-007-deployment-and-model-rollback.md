# ADR-007: Separate deployment rollback from model rollback

## Status
Accepted.

## Decision
ECS deployment/health failures may target a recorded last-known-good task definition. Model
promotion changes a separate active-version pointer and records its previous value. Drift creates
evidence and an incident; it never triggers automatic model rollback or promotion.

The pointer records semantic version plus manifest digest. API tasks load it once at startup, so a
promotion/rollback forces a controlled ECS deployment. Initial activation is staged: prerequisites
with runtimes disabled, verified image/model/pointer publication, then a second reviewed activation
plan. There is no hot reload or automatic drift response in the MVP.

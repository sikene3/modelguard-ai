# Phase 00 — Ultra Architecture Review

## Mode
Use GPT-5.6 Sol Ultra. This is a review-only phase.

## Objective
Perform a parallel, independent review of the planned ModelGuard AI MVP before implementation. Do not write application code and do not expand the product scope.

## Read first
- `PROJECT_SPEC.md`
- `ARCHITECTURE.md`
- `ACCEPTANCE_CRITERIA.md`
- `AGENTS.md`
- `docs/adr/`

## Review workstreams
Evaluate independently and then synthesize:

1. Architecture and data flow: correctness, failure modes, unnecessary complexity.
2. MLOps/statistics: leakage, reproducibility, thresholding, drift semantics, false claims.
3. AWS/security: IAM boundaries, networking, secrets, OIDC, logging, teardown risk.
4. Testing/delivery/portfolio: testability, phase boundaries, evidence, demo clarity.

## Required output
Create `reports/phase-00-architecture-review.md` containing:

- Executive verdict: ready / ready with required changes / not ready.
- Critical findings that must be fixed before coding.
- Recommended scope reductions.
- Findings that are intentionally deferred beyond MVP.
- A risk register with severity, likelihood, mitigation, and owner phase.
- Proposed documentation edits as a small, explicit list.

## Constraints
- Do not propose EKS, Airflow, Kafka/MSK, a feature store, automatic retraining, an LLM, or a database unless identifying why they are out of scope.
- Do not modify source code or create future implementation files.
- Do not run cloud commands.
- Prefer deleting complexity over adding services.

## Completion
End with the exact files you changed and a recommendation for whether Phase 01 may begin.

# ADR-001: Use ECS Fargate instead of EKS

## Status
Accepted.

## Decision
Run the API, dashboard, and scheduled monitoring task on ECS Fargate.

## Rationale
The MVP needs container orchestration, health checks, rolling deployments, IAM roles, logging, and scheduled tasks but does not need Kubernetes platform operations. ECS demonstrates AWS architecture while preserving finishability and lower operational overhead.

## Consequences
The project will not demonstrate Kubernetes. That is intentional and should be described as proportional architecture, not a missing feature.

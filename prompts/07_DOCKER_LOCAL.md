# Phase 07 — Docker Images and Local End-to-End Demo

## Recommended mode
GPT-5.6 Sol, XHigh.

## Objective
Containerize the API, dashboard, and monitor and prove the complete local workflow through Docker Compose and repeatable smoke scripts.

## Required implementation
- Separate Dockerfiles for API, dashboard, and monitor, sharing a sensible base strategy.
- Non-root runtime users.
- Minimal runtime layers; no development dependencies in final images where practical.
- Health checks.
- Pin release base images by digest and label images with source revision/lock identity.
- `docker-compose.yml` with local volumes/config and no AWS dependency.
- Traffic generator for baseline and drifted scenarios.
- `scripts/smoke_local.sh` proving health, prediction, event creation, monitor report, and dashboard availability.
- E2E scenarios for healthy traffic, drift, insufficient data, corrupt bundle, and sink outage.
- `scripts/demo_local.sh` orchestrating Healthy → Drifted flow.
- Trivy scan commands and documented remediation/exception process.
- Machine-readable smoke/load evidence; any scan exception needs rationale, owner, and expiry.
- Tests for scripts where practical and shellcheck compatibility if installed.

## Constraints
- Do not add Kubernetes manifests.
- Do not run containers as root.
- Do not bake model bundles, credentials, `.env`, or generated reports into images.
- Do not require Docker socket mounting.

## Validation

```bash
docker compose build
docker compose up -d
./scripts/smoke_local.sh
./scripts/demo_local.sh
trivy image modelguard-api:local
trivy image modelguard-dashboard:local
trivy image modelguard-monitor:local
docker compose down -v
make verify
```

## Definition of done
A documented clean-clone sequence runs the full local demonstration without AWS credentials.

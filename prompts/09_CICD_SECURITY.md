# Phase 09 — GitHub Actions CI/CD and DevSecOps

## Recommended mode
GPT-5.6 Sol, Max.

## Objective
Create reviewable, least-privilege GitHub Actions workflows for code quality, security, infrastructure planning, image publishing, and protected demo deployment.

## Required workflows
1. `ci.yml`: uv sync, format/lint, mypy, pytest/coverage, Bandit, pip-audit.
2. `container-security.yml`: build images and Trivy scan; publish reports/artifacts.
3. `terraform-plan.yml`: fmt, validate, Checkov, plan for trusted contexts without applying.
4. `publish-images.yml`: protected/manual or main-only image build and ECR push using Git SHA tags.
5. `deploy-demo.yml`: workflow_dispatch/protected environment, OIDC, reviewed plan/apply, ECS deployment, smoke test, clear failure handling.
6. Optional `destroy-demo.yml`: workflow_dispatch with protected environment and explicit confirmation input.

## Security requirements
- GitHub OIDC only; no AWS access keys.
- Restrict role trust to exact intended repository subjects: protected main-ref plan and protected
  GitHub Environment deploy/destroy are separate exact `sub` values.
- PRs from forks/untrusted contexts cannot assume AWS role.
- Pin third-party actions to commit SHAs for final release, with update notes.
- Pin release base images by digest and generate SBOM/scan evidence.
- Minimum permissions per job, especially `id-token: write` only where required.
- No secrets echoed.
- Terraform state/plan handling must not expose secrets.
- Run a pinned repository/history secret scanner. Allowlist entries require exact scope, rationale,
  owner, and expiry. Scanner output and artifacts must redact matched values.
- Do not auto-apply from PRs.

## Delivery requirements
- Immutable provenance tags by Git SHA for each deployable image.
- Build and scan each image once, then promote/deploy `repository@sha256:...` without rebuilding.
- Serialize deployments with workflow concurrency and use protected environments.
- Record deployed image/task definition/model version.
- Post-deploy live and ready checks plus one prediction smoke test.
- Failed smoke test makes workflow fail and triggers/documented rollback behavior.
- Record durable last-known-good task-definition and model-pointer values; ECS rollback and model
  rollback are separate. Drift alone never triggers rollback.
- Upload useful test, coverage, scan, and plan artifacts.
- Raw saved plans are short-lived, access-restricted workflow-transfer artifacts only. Publish a
  redacted human-readable summary for evidence, record the raw plan hash/source commit/account/backend
  identity, and refuse apply if any identity differs.
- Initial deploy runs a protected prerequisite plan with runtimes disabled, verifies image/model/
  pointer/token inputs, then a second protected activation plan. Never use `terraform -target` to
  bypass the barrier.

## Validation
Use actionlint/yamllint if available, run local tests, inspect permissions, and document any validation that requires GitHub execution.

## Definition of done
Workflows are syntactically valid, permission-scoped, OIDC-based, and cannot apply infrastructure from an untrusted pull request.

# AGENTS.md — Operating Contract for Coding Agents

## Mission

Build ModelGuard AI as a compact, production-style AWS MLOps portfolio project. Optimize for correctness, testability, security, clear evidence, and a finishable MVP. Do not optimize for feature count.

## Required reading order

Before making changes, read:

1. `PROJECT_SPEC.md`
2. `ARCHITECTURE.md`
3. `ACCEPTANCE_CRITERIA.md`
4. The current phase prompt under `prompts/`
5. The current phase checklist under `checklists/`

## Phase boundary

Implement only the current phase. Do not pre-build future phases unless a tiny interface stub is required for compilation or testing. Document any stub explicitly.

## Working method

1. Inspect the repository before editing.
2. State any material assumption in the phase report.
3. Prefer small, cohesive modules and explicit interfaces.
4. Add tests with implementation, not later.
5. Run the narrowest tests first, then the full phase gate.
6. Fix failures instead of weakening tests or quality configuration.
7. Update documentation when behavior or commands change.
8. End with a concise summary of files changed, commands run, results, residual risks, and the exact next manual action.

## Engineering standards

- Python 3.12.
- `uv` for dependency and virtual-environment management.
- `src/` package layout.
- Type hints on public functions and boundaries.
- Pydantic v2 for external contracts and configuration.
- Ruff for formatting/linting, Mypy for type checking, Pytest for tests.
- Structured logging; never print secrets or full environment variables.
- UTC timestamps in ISO 8601.
- Deterministic random seeds where applicable.
- Dependency injection for storage/event sinks and cloud clients.
- No hidden network calls in unit tests.
- No broad exception swallowing.
- No mutable global application state except carefully controlled cached model loading.
- No TODO placeholder that blocks acceptance criteria.

## Security rules

- Never create or request long-lived AWS access keys.
- Never write secrets into files, logs, tests, Terraform variables, or screenshots.
- Use GitHub OIDC for AWS deployment.
- Containers must run as non-root.
- Avoid `latest` image tags for deployments.
- Use least-privilege IAM and explicit resource ARNs where practical.
- Do not use `danger-full-access` or disable the sandbox.
- Do not run `terraform apply` or `terraform destroy` unless the phase prompt explicitly permits it and the user has initiated the deployment phase.
- Never destroy resources outside the configured demo workspace.

## Scope-control rules

Do not add the following to the MVP:

- EKS/Kubernetes.
- Kafka/MSK.
- Airflow.
- Feature store.
- Automatic retraining.
- LLM/Bedrock features.
- Authentication platform.
- Multi-region architecture.
- A separate database unless a phase prompt explicitly changes the architecture.

## Evidence requirements

A claim is not complete without evidence. Capture in the final phase response:

- Commands executed.
- Test counts/results.
- Lint/type/security status.
- Relevant generated artifact paths.
- Any skipped check and the reason.

## Git discipline

- Do not commit automatically.
- Do not rewrite Git history.
- Do not modify unrelated files.
- Keep generated large artifacts out of Git.
- Recommend a commit message at the end of each phase.

## Definition of done

A phase is done only when its checklist is satisfied, expected tests pass, docs reflect actual commands, and no unexplained failure remains.

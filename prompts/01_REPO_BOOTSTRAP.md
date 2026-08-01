# Phase 01 — Repository Bootstrap and Quality Gates

## Recommended mode
GPT-5.6 Sol, XHigh.

## Objective
Create a clean, installable Python 3.12 repository foundation for ModelGuard AI with deterministic developer commands and quality gates. Implement no product logic beyond minimal importable stubs.

## Read first
`AGENTS.md`, `PROJECT_SPEC.md`, `ARCHITECTURE.md`, `ACCEPTANCE_CRITERIA.md`, and `checklists/PHASE_01.md`.

## Required implementation
- Validate and improve `pyproject.toml` for uv, src layout, Ruff, Mypy, Pytest, coverage, Bandit, and pip-audit.
- Pin project execution to Python 3.12 (`requires-python >=3.12,<3.13` plus `.python-version`) and
  create a committed `uv.lock`; do not rely on the host's unversioned `python3` default.
- Create the final package skeleton under `src/modelguard/` without implementing later-phase behavior.
- Create test folder structure and at least one import/version smoke test.
- Create or improve `Makefile` with setup, format, lint, typecheck, test, security, verify, clean.
- Create `.env.example`, safe `.gitignore`, and README skeleton.
- Align the documented monitoring minimum with the locked Phase 05 default of 500. Ignore all
  non-example `*.tfvars`/`*.tfvars.json` forms, state, plans, and environment files.
- Add a simple typed settings module that loads local defaults without requiring AWS.
- Add a version module and expose package version.
- Add `scripts/check_no_secrets.sh` for basic accidental-secret/file checks without pretending it
  replaces a real scanner. It may print only redacted path/line locations, never a matching secret
  value. Audit the convenience installer: pin/verify remote artifacts or clearly make unverified
  remote-install steps manual rather than silently treating them as reproducible setup.
- Update `reports/phase-01.md` from the template.

## Constraints
- Do not implement dataset generation, model training, API, monitoring, dashboard, Docker, Terraform, or workflows.
- Do not add a web framework yet unless only a dependency declaration already exists.
- Do not create hidden network calls during setup/tests.

## Required validation
Run and fix:

```bash
uv sync --all-groups
uv run ruff format --check .
uv run ruff check .
uv run mypy src
uv run pytest -q
uv run bandit -q -r src
./scripts/check_no_secrets.sh
```

## Definition of done
The repository installs from a clean environment, imports `modelguard`, and all quality commands pass.

## Final response
Report files changed, exact commands/results, residual risks, suggested commit message, and stop. Do not begin Phase 02.

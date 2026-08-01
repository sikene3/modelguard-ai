# Phase 01 Report

## Objective

Create an installable Python 3.12 repository foundation with deterministic uv commands, an
importable package skeleton, typed local settings, and enforceable quality/security gates. No
product behavior was implemented.

## Scope completed

- Pinned project execution to `>=3.12,<3.13`, retained `.python-version` as `3.12`, constrained uv
  to 0.12.x, pinned the build backend, and refreshed/validated `uv.lock`.
- Made all final `modelguard` subpackages importable without adding later-phase modules or behavior.
- Added a standalone version module, distribution/version smoke coverage, and a `py.typed` marker.
- Added immutable Pydantic v2 settings that load safe local defaults without AWS credentials,
  clients, or network calls.
- Added deterministic Make targets for setup, format, lint, type checking, tests, security, verify,
  and clean. Premature application commands and broken console entry points were removed.
- Hardened environment, Terraform variable/state/plan, artifact, cache, and secret-file ignores.
- Replaced the tracked-only secret check with a redacted scan of tracked and untracked candidate
  files plus explicit ignore-contract checks.
- Converted the unverified remote Ubuntu convenience installer into a manual-only guide with no
  network or system mutation.
- Documented `MIN_MONITORING_SAMPLES=500`, matching the locked Phase 05 default.
- Repaired the live audit finding `PYSEC-2026-1845` by raising the Pytest floor to 9.0.3 and locking
  Pytest 9.1.1; the final full dependency audit is clean.

## Files changed

- Repository/tooling: `pyproject.toml`, `uv.lock`, `Makefile`, `.env.example`, `.gitignore`,
  `README.md`, `START_HERE.sh`, `FILE_MANIFEST.txt`.
- Safety/bootstrap: `scripts/bootstrap_repo.sh`, `scripts/check_no_secrets.sh`,
  `scripts/setup_ubuntu.sh`, `scripts/verify_environment.sh`.
- Documentation alignment: `docs/07_TROUBLESHOOTING.md`,
  `docs/10_COMMANDS_CHEATSHEET.md`.
- Package: `src/modelguard/__init__.py`, `src/modelguard/version.py`,
  `src/modelguard/core/config.py`, `src/modelguard/core/__init__.py`, `src/modelguard/py.typed`, and
  package-only `__init__.py` files under `api`, `dashboard`, `data`, `inference`, `monitoring`,
  `storage`, and `training`.
- Tests: `tests/smoke/test_package_import.py`, `tests/unit/test_settings.py`; empty placeholders remain
  for contract and integration suites.
- Phase records: `checklists/PHASE_01.md`, `tasks/phase_status.json`, `reports/phase-01.md`.

## Commands and evidence

`./scripts/run_phase.sh 01 max` initially stopped because the unpacked kit was not a Git work tree.
Phase 01 initialized Git on branch `main` without staging or committing, then reran the command. The
nested execution completed its implementation and required gates but was interrupted during a
redundant final-review loop that repeatedly emitted the complete untracked diff. The final state was
therefore inspected and validated directly with the commands below.

```text
uv sync --all-groups
PASS — resolved 159 packages; checked 156 packages.

uv run ruff format --check .
PASS — 75 files already formatted.

uv run ruff check .
PASS — all checks passed.

uv run mypy src
PASS — no issues in 11 source files.

uv run pytest -q
PASS — Pytest 9.1.1; 4 passed; 41 statements; 100% branch coverage (70% gate).

uv run bandit -q -r src
PASS — exit 0; no findings emitted.

./scripts/check_no_secrets.sh
PASS — ignore contract and tracked/untracked content scan passed.

uv lock --check
PASS — resolved 159 packages without changing the lock.

uv run python -c 'import sys, modelguard; assert sys.version_info[:2] == (3, 12); ...'
PASS — modelguard=0.1.0, Python 3.12.13.

UV_PROJECT_ENVIRONMENT=<new temporary venv> uv sync --all-groups --frozen
PASS — installed 156 packages from the validated lock; a fresh process imported modelguard 0.1.0
on Python 3.12.13 and Pytest 9.1.1.

make verify
PASS — Ruff format/lint, Mypy, Pytest/coverage, Bandit, pip-audit, and the secret/file check all
passed in one end-to-end gate.

bash -n START_HERE.sh scripts/*.sh
PASS.

./scripts/check_no_secrets.sh  # with a temporary fake access-key-shaped fixture
EXPECTED REJECTION — reported only tests/secret-check-fixture.txt:2 plus [REDACTED]; the matching
value was absent from output. The fixture was then removed.
```

The first live `make security` run correctly failed closed on `pytest 8.4.2` with
`PYSEC-2026-1845` and a fixed-version floor of 9.0.3. `pyproject.toml` was repaired to
`pytest>=9.0.3,<10`, the lock resolved Pytest 9.1.1, and the final hashed, locked `pip-audit` run
reported `No known vulnerabilities found`.

## Tests

- 2 smoke tests: installed distribution/version consistency and all phase package imports.
- 2 unit tests: AWS-free local defaults and typed `.env` overrides.
- Final result: 4 passed in 0.23 seconds, 100% branch coverage.

## Generated artifacts

- `uv.lock` — SHA-256
  `e2239d71d962cd30324a948f0757f66c01150d2c03b131798903a3e28812c10e`.
- `reports/phase-01.md` — this evidence record.
- `FILE_MANIFEST.txt` — 103 sorted, commit-candidate paths; the manifest intentionally excludes
  itself and ignored local outputs.
- `.coverage` and `.cache/` are local ignored validation outputs and are not commit artifacts.
- `logs/phase-01-max-20260801T211518Z.log` and
  `logs/phase-01-max-20260801T211538Z.log` are ignored local runner logs, not commit artifacts.
- Temporary clean-install environments/caches were created under `/tmp`, validated, and removed
  after the final checks; they are not commit artifacts.

## Decisions/assumptions

- Existing future product dependencies were retained as declarations because the phase prompt
  explicitly permits an already-declared web framework. No framework or later-phase behavior is
  imported or implemented.
- Settings declarations for future non-secret AWS resource identifiers are interface stubs only;
  no AWS SDK client is constructed and no credentials are required.
- Package and distribution versions are intentionally duplicated in `version.py` and
  `pyproject.toml`; a smoke test fails if they diverge. Static metadata avoids fetching a build
  backend merely to read the version during lock checks.
- The repository currently has no commit history and all supplied files are untracked. No staging
  or commit was performed, per `AGENTS.md`; `uv.lock` is present, validated, and not ignored so it
  can be committed with the phase.

## Residual risks

- The basic repository scanner covers common high-confidence patterns and sensitive file forms but
  does not replace a dedicated secret scanner or human review.
- Predeclared later-phase dependencies increase the audit surface before those components exist;
  they are currently audit-clean and locked but unused in Phase 01.
- The unpacked launch kit began without Git history. All 103 manifest-listed files remain untracked
  until the user performs the first review, staging, and commit.
- Shellcheck was not run because it is not installed and is not a Phase 01 required gate; `bash -n`
  passed for all shell entry points. Docker, Terraform, and AWS checks were intentionally not run
  because their implementation belongs to later phases.

## Acceptance checklist status

- [x] uv sync succeeds.
- [x] Python 3.12 range, `.python-version`, and commit-ready `uv.lock` are present.
- [x] Package and final subpackage skeleton import.
- [x] Ruff format/lint pass.
- [x] Mypy strict mode passes.
- [x] Pytest and coverage pass.
- [x] Bandit passes.
- [x] Redacted secret/file and ignore-contract checks pass.
- [x] Unverified remote installation is manual-only.
- [x] Phase report is updated.

## Suggested commit message

`chore: bootstrap Phase 01 repository quality gates`

## Next manual action

Review all 103 paths in `FILE_MANIFEST.txt`, stage the complete launch kit intentionally, and create
the first manual commit with the suggested message. Do not begin Phase 02 before that review and
commit.

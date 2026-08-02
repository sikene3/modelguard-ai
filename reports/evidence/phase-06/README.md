# Phase 06 Evidence Index

Phase 06 evidence is complete. The two screenshots were rendered by a real headless Chrome session
from loopback-bound Streamlit servers and visually reviewed. They contain only deterministic
synthetic evidence and public artifact identities.

## Fresh local scenarios

Both ignored validation roots were generated from the verified `1.0.0` bundle for the finalized
`[2026-08-02T11:00:00Z, 2026-08-02T12:00:00Z)` window and completed at
`2026-08-02T13:03:29Z`:

| Scenario | States `(run, quality, drift, performance)` | Accepted | Report ID | JSON SHA-256 | HTML SHA-256 |
| --- | --- | ---: | --- | --- | --- |
| Baseline | `succeeded, valid, healthy, unknown` | 1,000 | `59fd5b7025e0caf17da35265205119ccdeb95430929e57c785cc5b816e52708e` | `c120027eaaa0c64e0c76c332c53e3e949868bef709d028b73d975a36310b98f1` | `b9735ffaa906e4decb92f69c981f15dd0cb1990dd244ee4de7bbc05e037937c6` |
| Shifted | `succeeded, valid, degraded, unknown` | 1,000 | `8736d3123370ffc8bea23787a6ca2a5e3d623a5fd7c68eaa125b093e20dd241a` | `cc5c632cae0a9929a6f88615ae8687a92f32e483812641448d07a88fe5b30f72` | `073575820666131365a53f863b8124664001cb97f42f0128df8b448c1d72ae2f` |

Ignored report roots:

```text
artifacts/phase-06-validation/healthy/
artifacts/phase-06-validation/degraded/
```

## Browser evidence

| Scenario | Screenshot | Viewport | Verified card sequence | PNG SHA-256 |
| --- | --- | --- | --- | --- |
| Baseline | `healthy-dashboard.png` | 1440x1200 | `succeeded, valid, healthy, unknown` | `f3cc03a785726ffa391583c549f015de5af3ed52a045e5a550693f737f0b24fe` |
| Shifted | `degraded-dashboard.png` | 1440x1200 | `succeeded, valid, degraded, unknown` | `7ade968f6f8215dacd6445b18286bef873e964e7f79a2293ab31f77241e66284` |

For both scenarios:

- Streamlit bound to loopback and `/_stcore/health` returned `ok`.
- Chrome rendered all four state cards with no `[data-testid=stException]` element.
- The fixed light theme produced the expected `rgb(19, 34, 56)` heading color.
- The 500px responsive check used one state-card column, had no horizontal overflow, and rendered no
  Streamlit exception.
- Visual review confirmed readable labels, non-stacked baseline/current comparisons, exact UTC
  freshness, and no credential or secret content.

## Automated gate

- Focused Phase 06 repository/render tests: 13 passed.
- Required `tests/unit tests/smoke`: 158 passed in 8.84 seconds; 76.05% coverage.
- Full suite: 184 passed in 19.60 seconds; 84.71% coverage.
- Ruff format/lint: passed across 154 files.
- Strict Mypy: passed across 52 source files.
- Bandit: passed with no findings.
- Hash-locked `pip-audit`: no known vulnerabilities.
- Basic secret/file scan: passed.
- Offline lock check: resolved all 159 locked packages without changes.
- Trusted bundle verification: passed; smoke score `0.9981110662188358`.
- Manifest parity/sort, English-only filename/content, shell syntax, project JSON, disposable-file,
  and future-phase scope checks: passed.

## Reproduction

```bash
LOCAL_REPORT_DIR=artifacts/phase-06-validation/healthy/reports \
  DASHBOARD_PORT=18501 make dashboard

LOCAL_REPORT_DIR=artifacts/phase-06-validation/degraded/reports \
  DASHBOARD_PORT=18502 make dashboard

uv run pytest tests/unit tests/smoke -q
make verify
```

The screenshots are evidence of local synthetic scenarios only. S3/IAM/deployed dashboard evidence
remains explicitly owned by Phase 08.

# Phase 05 Evidence Index

This committed index points to the ignored, reproducible local artifacts produced by the Phase 05
validation run. Generated prediction/model/report data remains outside Git.

## Verified identities

- Model version: `1.0.0`
- Bundle manifest SHA-256:
  `49cbe04bc4285fc71463d0071e3babc3a5f5c20011541a072b4844bb5c78afd9`
- Effective monitoring configuration digest recorded in both reports:
  `edd3177bc4a692262858b6ec2e60a991cdce1bc844ef7eb0becac6846df56c73`
- Monitoring configuration file SHA-256:
  `599adfc823d6a6e2e9153d23e3a2cecbdfbbe9a59afaeeba75930b06b77bbc1e`
- Portable report JSON Schema SHA-256:
  `fd1fc6a1d0e2143c8fd53bef317c89cd3a1ee7ee934db390513c84381e0d1967`

## Deterministic reports

| Window end | States `(run, quality, drift, performance)` | Report ID | JSON SHA-256 | HTML SHA-256 |
| --- | --- | --- | --- | --- |
| `2026-01-01T01:00:00Z` | `succeeded, valid, healthy, unknown` | `ba471dc62fc66f644a0f38ca2631168b5d4ce8c8c0753094927c69c9d83396b4` | `d95ccc406894dbcd96402672c0cedd0ed56267112c7bd68e9e1eade118a46d3c` | `2a4f81b440fac5870a17e73617994c8a340007e3a418620393ae5e37ed6cb830` |
| `2026-01-01T02:00:00Z` | `succeeded, valid, degraded, unknown` | `682cf4afea30b8aad75d37e3ab7123f3a2ede29099e1e60720a1269163dfdb6d` | `60fdb7f589b2d708226b4157aeba744ad06357a3dabfd9634125f643448e753f` | `6552398fea7f5619c6c1d3e1e920b7059e32a3032fd63c4d1ab2fd3a68fbe62f` |

The ignored artifact roots are:

```text
artifacts/phase-05-validation/predictions/
artifacts/phase-05-validation/reports/
```

The baseline report reconciles `raw=1000` and `accepted_target=1000`. The shifted report reconciles
`raw=2000`, `outside_window=1000`, and `accepted_target=1000`; outside-window rows alone do not
degrade data quality or advance to identity classification. An exact shifted-window rerun returned
the same report ID and both checksums, with `latest_updated=false`. Status at
`2026-01-01T04:10:00Z` was `stale`.

The drift transition marker has SHA-256
`ccd2b5fd1638bead639d00ec80075aa06a1f4eee3b4edfac640f51ac1d85d9ed`. It records
`healthy -> degraded`, a `not_configured` send outcome, and the explicit no-exactly-once delivery
semantics.

## Gate results

- Focused Phase 05 gate: `61 passed`.
- Required `tests/unit tests/integration`: `162 passed`, no warnings, `85.87%` total coverage.
- Final full repository test gate: `171 passed`, `86.08%` total coverage.
- Affected Phase 03/04 API and event regression set: `47 passed`.
- Ruff format/lint: passed across 144 files.
- Strict Mypy: passed across 47 source files.
- Bandit: passed with no findings.
- Basic secret/file scan: passed.
- Offline lock check: all 159 packages resolved without a lock change.
- Trusted bundle verification: passed; smoke score `0.9981110662188358`.
- Strict hashed `pip-audit`: passed with no known vulnerabilities.

Full command output and scope details are recorded in `reports/phase-05.md`.

# Phase 06 Report

## Objective

Create a compact, polished, read-only Streamlit dashboard that presents system health, model/report
identity, drift and distribution evidence, volume reconciliation, label-backed performance, and
actual freshness timestamps without overstating what the evidence proves.

## Completion status

**Complete.** Every Phase 06 functional requirement, automated gate, live TCP check, real-browser
check, screenshot requirement, security check, and repository-integrity check passed. No validation
was skipped, no Phase 07 implementation was introduced, and no commit was created automatically.

## Scope completed

- Added one typed `DashboardRepository` protocol used by both local files and S3. Local reads are
  read-only, size-bounded, regular-file/symlink guarded, and history-bounded. S3 reads use an
  injected client, bounded timeouts/pagination/payloads, deterministic private prefixes, and closed
  response bodies. Unit tests make no network calls.
- Added safe HTML behavior: local mode downloads immutable offline HTML bytes; S3 mode verifies the
  exact object and generates only a short-lived HTTPS attachment URL. Public bucket/object URLs,
  URL persistence, and URL logging are absent.
- Added dashboard-only strict settings with local defaults and an explicit AWS/S3 configuration
  boundary. AWS mode requires model/report buckets; no API authentication setting is reused.
- Added generic duplicate-key/non-finite/UTF-8 strict JSON byte parsing and reused the strict Phase
  05 Pydantic contracts for monitoring reports and independent run status.
- Added an honest snapshot/view model. It validates report/status chronology and report IDs, derives
  `succeeded | failed | stale | never_run` using the exact matching policy, preserves current
  failure even if prior evidence is missing, and never turns missing/malformed/mismatched evidence
  into health. Window/event ages stay separate from report age and are not called delivery lateness.
- Derived the configured active `{model_version, manifest_sha256, input_schema_sha256}` from strict
  manifest bytes without deserializing joblib. Configured active identity is visibly separate from
  the report's event-carried target and may legitimately differ after promotion.
- Added identity-gated threshold presentation. Monitor-recorded values/states are never recomputed;
  PSI/JS thresholds and stale timing appear only when the canonical policy hash exactly matches the
  report configuration identity.
- Added responsive state cards with distinct visual treatments for `unknown`, `stale`,
  `insufficient_data`, `pending_labels`, and unavailable evidence. Performance sections explicitly
  state that drift is not label-backed performance.
- Added exact UTC snapshot/report/window/event freshness, configured/target/event/input/baseline/
  configuration identities, accepted volume and six-bucket reconciliation, classification faults,
  top input drift signals, prediction signals, missingness, numeric/categorical comparisons, and
  score/decision history from immutable reports.
- Restricted prediction trends to reports with the exact same target, baseline, monitoring-policy
  version, and monitoring-policy hash. A single comparable report is labeled as a distribution
  snapshot, not presented as a time trend.
- Added grouped baseline/current distribution bars, a fixed high-contrast light Streamlit theme,
  responsive layout, readable native widgets, and exact report timestamps.
- Added `make dashboard`, local/S3 configuration examples, operator and claim-boundary
  documentation, repository/parsing tests, and Streamlit startup/render smoke coverage. There are no
  mutation, promotion, authentication-platform, or auto-refresh controls.
- Documented the sole future-phase interface stub: S3 mode reads strict
  `monitoring/run-status.json`; Phase 08 must wire its writer and least-privilege reader IAM before
  deployed AWS run-health claims.

## Review repairs

The final review found and repaired six genuine issues before evidence capture:

1. Historical charts could combine incompatible target/baseline/policy identities. Exact identity
   filtering and a regression assertion now prevent cross-model or cross-policy trends.
2. S3 object bodies were not explicitly closed. The repository now closes every response body and
   the fake-client test proves it.
3. A final-component local symlink loop was reported only as unavailable. It now maps to the bounded
   `unsafe_local_artifact` category.
4. Lazy S3 client-construction failure was not reduced to a safe dashboard error. It now maps to
   `s3_client_unavailable` and the app withholds evidence cleanly.
5. Browser dark-mode preference could make custom light panels and native widgets unreadable. The
   checked-in Streamlit theme and stronger scoped styles provide deterministic contrast.
6. Stacked baseline/current bars and one-point line charts overstated their visual comparison. The
   distributions are grouped, and one-report prediction evidence is explicitly a snapshot.

## Files changed

- Dashboard: `src/modelguard/dashboard/{app,config,parsing,presentation,repository}.py` and package
  description.
- Strict parsing: `src/modelguard/core/serialization.py`.
- Tests: `tests/unit/test_dashboard_repository_parsing_phase06.py` and
  `tests/smoke/test_dashboard_startup_phase06.py`.
- Commands/config/docs: `Makefile`, `.env.example`, `.streamlit/config.toml`, `README.md`,
  `GETTING_STARTED.md`, `START_HERE.sh`, `docs/10_COMMANDS_CHEATSHEET.md`, and
  `docs/DASHBOARD_CONTRACT.md`.
- Phase records/evidence: acceptance, checklist, status, manifest, this report, the evidence index,
  and two reviewed local screenshots.

## Commands and evidence

```text
./scripts/run_phase.sh 06 max
PASS — implemented Phase 06 only and left the reviewable worktree uncommitted.

uv run pytest tests/unit/test_dashboard_repository_parsing_phase06.py \
  tests/smoke/test_dashboard_startup_phase06.py --no-cov -q
PASS — 13 focused dashboard tests.

uv run pytest tests/unit tests/smoke -q
PASS — 158 passed in 8.84 seconds; 76.05% total branch coverage.

make verify
PASS — 154 files Ruff-formatted/linted; strict Mypy passed 52 source files; 184 tests passed
in 19.60 seconds with 84.71% total branch coverage; Bandit passed; pip-audit found no known
vulnerabilities; the basic secret/file scan passed; and the trusted bundle verified.

make verify-model
PASS within make verify — trusted bundle 1.0.0, manifest
49cbe04bc4285fc71463d0071e3babc3a5f5c20011541a072b4844bb5c78afd9, smoke score
0.9981110662188358. The immutable Phase 02 bundle was not retrained or overwritten.

uv lock --check --offline
PASS — all 159 locked packages resolved without a lock change.

LOCAL_REPORT_DIR=artifacts/phase-06-validation/healthy/reports DASHBOARD_PORT=18501 make dashboard
LOCAL_REPORT_DIR=artifacts/phase-06-validation/degraded/reports DASHBOARD_PORT=18502 make dashboard
PASS — both servers bound to loopback; Streamlit health returned `ok`; real headless-Chrome renders
had no Streamlit exception and showed the exact expected four-state sequences.

browser desktop and responsive checks
PASS — both evidence images are 1440x1200 PNGs; heading contrast was deterministic; a 500px viewport
used one state-card column, had no horizontal overflow, and had no Streamlit exception.

manifest parity, Arabic-character, shell/JSON syntax, disposable-file, and future-scope scans
PASS — FILE_MANIFEST.txt is sorted and exactly matches the approved candidate set; no Arabic text or
filenames, unapproved disposable paths, or Phase 07 implementation files were found. The only path
matching the generic log-directory scan was the intentional tracked `logs/.gitkeep` placeholder.
```

## Test coverage

- Local repository: latest/status/active manifest/history/HTML reads, size bounds, and symlink
  rejection.
- S3 repository: identical parse surface, fake-only object/history reads, closed response bodies,
  object existence, and short HTTPS attachment-link parameters/expiry.
- Parsing/freshness: strict UTF-8/duplicate-key rejection, healthy and exact stale boundaries,
  missing/malformed artifacts, current-failure precedence, report/status identity, policy mismatch,
  and configured-active/report-target separation.
- Presentation: top signal scores/exact thresholds, comparable distribution vectors,
  identity-compatible prediction/decision history, and distinct special-state card classes.
- Streamlit: honest missing-artifact startup and complete fresh local-report rendering without a
  script exception. Existing Phase 05 tests continue to own and verify all monitoring math/state
  policies.
- Real browser: healthy/degraded state preservation, no runtime exception, deterministic readable
  theme, desktop evidence capture, and narrow-viewport layout behavior.

## Generated artifacts

- Healthy ignored report root: `artifacts/phase-06-validation/healthy/reports/`; report
  `59fd5b7025e0caf17da35265205119ccdeb95430929e57c785cc5b816e52708e`.
- Degraded ignored report root: `artifacts/phase-06-validation/degraded/reports/`; report
  `8736d3123370ffc8bea23787a6ca2a5e3d623a5fd7c68eaa125b093e20dd241a`.
- Healthy screenshot: `reports/evidence/phase-06/healthy-dashboard.png`; SHA-256
  `f3cc03a785726ffa391583c549f015de5af3ed52a045e5a550693f737f0b24fe`.
- Degraded screenshot: `reports/evidence/phase-06/degraded-dashboard.png`; SHA-256
  `7ade968f6f8215dacd6445b18286bef873e964e7f79a2293ab31f77241e66284`.
- Evidence index: `reports/evidence/phase-06/README.md`.

The screenshots contain only deterministic synthetic evidence and public artifact identities; they
were visually reviewed and passed the repository secret/file scan.

## Decisions and assumptions

- The active local identity is the configured strict manifest identity, not a live API `/version`
  probe. The dashboard makes no hidden network call and labels it configured active identity.
- Historical report trends use only proportions already stored in validated, identity-compatible
  reports. No raw-event read, average-score approximation, or dashboard-side drift calculation is
  introduced.
- A missing policy never falls back to hard-coded thresholds. A mismatched policy withholds both
  thresholds and derived current freshness state.
- A valid current failure remains `failed` even when its prior success artifact is missing; the
  missing historical evidence is reported independently.
- S3 presigned downloads are short-lived bearer URLs. They reduce exposure but do not replace the
  later restricted ALB/private-task/IAM deployment boundary.

## Residual risks

- The S3 repository is fake-client tested but not deployed; Phase 08 owns buckets, IAM, networking,
  object versioning/lifecycle, and the run-status writer.
- Local configured-manifest identity does not prove which model an independently running API process
  has in memory; operators should compare the API version endpoint during the later integrated demo.
- Streamlit has no authentication platform by MVP design. Later AWS access remains restricted by the
  ALB CIDR/access-mode architecture.
- The screenshots prove the local synthetic scenarios only; they are not AWS deployment evidence.

No unexplained Phase 06 validation failure remains.

## Acceptance and phase decision

All Dashboard acceptance criteria and every Phase 06 checklist item are implemented and evidenced.

- **Phase 06 technical decision: GO — complete.**
- **Phase 07 decision: NO-GO until the required independent human review approves and manually
  commits this Phase 06-only worktree.**

## Suggested commit message

`feat: add honest Phase 06 operations dashboard`

## Next manual action

Review the complete Phase 06 diff and both screenshots, rerun any desired local checks, stage only
the approved files, and create the manual commit. Do not run Phase 07 before that review gate.

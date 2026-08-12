# Phase 13 report — portfolio packaging

## Outcome

Phase 13 packaging and its previously missing genuine media are implemented before the Phase 12
Ultra audit. The repository leads with the failure prevented, uses first-person claims where
appropriate, maps material claims to evidence, and discloses synthetic data, temporary cloud scope,
label limits, availability/cost trade-offs, and teardown.

No screenshot, cloud receipt, GIF, or video was fabricated. Four existing synthetic/local dashboard
PNGs remain unchanged and indexed with their original capture boundaries. The new 4-minute-15-second
MP4 records the real current loopback application at 1280×720; its 15-second GIF is derived from the
same healthy-to-monitoring-to-degraded interval. Both passed the privacy checklist and are linked by
exact hash in the claims ledger.

Phase 13 made no AWS, deployment, notification, or other cloud mutation. Publication is limited to
the final dedicated Git branch, protected pull request, required checks, and normal merge described
in this report; it does not change repository rules or other GitHub settings.

## Material assumptions and boundaries

- All transaction and label examples are synthetic.
- The AWS application environment is historical and temporary. Phase 10 records completed guarded
  teardown with zero disposable demo resources; Phase 13 does not claim a currently live endpoint.
- The retained USD 10 Budget and audit/bootstrap controls remain intentional and may still carry
  limited cost/maintenance responsibility.
- The Phase 11 dashboard pair is visibly labeled as offline report-backed evidence. The Phase 06
  pair is a prior local live-browser capture. None is relabeled as live AWS evidence.
- The 25 requests/second performance threshold, scanner integrity policy, and dependency-audit
  strictness were not changed to accommodate this sandbox.

## Deliverables

- Final outcome-led [`README.md`](../README.md) with genuine demo media, evidence, architecture,
  quickstart, AWS overview, evidence, security, cost, teardown, trade-offs, and limitations.
- [`docs/CASE_STUDY.md`](../docs/CASE_STUDY.md) using problem → constraints → decisions →
  implementation → failure demo → evidence → outcome → limitations.
- LinkedIn, Upwork, and bounded three-tier Fiverr copy under [`portfolio/`](../portfolio/).
- A timed 4:15 [`demo-script.md`](../portfolio/demo-script.md) and privacy-aware
  [`screenshot-checklist.md`](../portfolio/screenshot-checklist.md).
- [`architecture.mmd`](../portfolio/architecture.mmd), offline deterministic exporter, official
  pinned Mermaid CLI alternative, and checked SVG/PNG assets.
- [`skills-to-evidence.md`](../portfolio/skills-to-evidence.md) across AWS, MLOps, DevOps, Data
  Engineering, security, and observability.
- A 30-entry [`claims-ledger.md`](../portfolio/claims-ledger.md) covering material public claims,
  boundaries, excluded claims, the scoped service offer, and the exact recording/GIF identities.
- A non-network [`validate_portfolio.py`](../scripts/validate_portfolio.py) gate plus focused tests.
- Genuine [`modelguard-demo.mp4`](../portfolio/assets/demo/modelguard-demo.mp4) and same-recording
  [`modelguard-drift.gif`](../portfolio/assets/demo/modelguard-drift.gif) assets.

## Clean quickstart evidence

The current tracked/untracked approved source surface was copied to a fresh temporary directory;
the existing repository artifacts, MLflow state, and virtual environment were not reused as project
outputs.

The first literal `make setup` attempt created Python 3.12 and resolved all 128 locked packages, then
failed while downloading scikit-learn because the sandbox blocks DNS. A validated locked environment
was copied into the isolated tree and `make setup` was rerun with the repository's existing uv cache
and `UV_OFFLINE=1`. That exact Make target passed, rebuilt the project from the temporary source, and
made no network call. This is a dependency-seeded clean run, not evidence that the sandbox can fetch
packages from an empty cache.

The documented functional sequence then passed:

```text
make train
  PASS — 5,000 synthetic rows; model 1.0.0; held-out AP 0.40842191798974226;
         prevalence 0.188; threshold 0.075; one fresh MLflow run and seven-file bundle.

make verify-model
  PASS — trusted-origin bundle verification and finite smoke score 0.9981110662188358.

baseline fixture + monitor
  PASS — accepted_target=1000, run=succeeded, data_quality=valid, drift=healthy,
         performance=unknown, immutable JSON/HTML report pair.

drifted fixture + monitor
  PASS — accepted_target=1000, run=succeeded, data_quality=valid, drift=degraded,
         performance=unknown, newer immutable JSON/HTML report pair.
```

`make api` started Uvicorn on loopback, loaded the isolated verified model, and completed application
startup. The sandbox then denied the separate curl process's socket creation. `make dashboard`
reached Streamlit server startup and was denied at socket creation. Those are environment-level
socket restrictions, not successful browser/curl claims. API and Streamlit behavior were instead
covered by the focused in-process integration/smoke tests below; prior unrestricted local captures
remain indexed in Phase 06.

## Genuine media capture evidence

The unrestricted host started the current API and Streamlit dashboard on loopback, verified the
seven-file bundle, served one committed synthetic prediction request, and created fresh adjacent
1,000-event baseline/drift windows. The baseline report states were
`succeeded/valid/healthy/unknown`; the shifted report states were
`succeeded/valid/degraded/unknown`.

The first capture attempt was rejected during visual review because Streamlit disconnected. The
kernel located both observed crashes at the same `mi_thread_init` offset in PyArrow 25's bundled
`libarrow` mimalloc backend. Running only the dashboard with Arrow's supported `system` memory pool
passed a live-browser stability check, after which a fresh capture completed without a disconnect.
The rejected media and extracted validation frames were excluded, then removed during bounded
cleanup; they are not portfolio assets.

Final reviewed media:

- `portfolio/assets/demo/modelguard-demo.mp4`: ISO MP4/H.264, 255.036 seconds, 1280×720, 25 fps,
  35,941,469 bytes, SHA-256
  `a8910b4c8fd9d392dc7e161cc773caefcff38501815f25f3e43d8f3fe6f07237`.
- `portfolio/assets/demo/modelguard-drift.gif`: animated GIF89a, 15.000 seconds, 960×540, 26
  optimized frames, 3,574,995 bytes, SHA-256
  `e0a0f8112298ee633f8a9381859fa6d37554d110e67cbe9c53f189c40d1a1dc4`.

The GIF uses seconds 117.5–132.0 of the exact MP4. It shows the live drift card as `healthy`, the
real deterministic monitor activity and persisted `degraded` result, then the reloaded live
dashboard with drift `degraded` and performance `unknown`. The initial dashboard's event-time
freshness indicator is retained rather than hidden. No additional static screenshot was required;
the existing four reviewed images already satisfy that count.

## Commands and validation results

### Portfolio contract

```text
make portfolio-check
PASS — 15 required paths; 10 public Markdown files; 188 local links; 5 README Bash blocks;
       10 README commands; all 5 referenced Make targets; 30 claims; 4 reviewed screenshots;
       2 genuine media files; MP4 255.0356s at 1280×720; GIF 15.0s / 26 optimized frames;
       architecture source/SVG/PNG byte parity; no bounded public-text sensitive pattern.
```

Final architecture hashes:

- Mermaid: `a3b9142de6be07463bc301dd6c5e863b4d76b1f8d064cb0bf8c3c78c5b32b89a`.
- SVG: `e05a6d639ceb85b5d79e7cf0d9137a9ca8ffb05f606f69bb29ff291e5860e2b1`.
- PNG: `5e10f162b061782e0b8f0f29142d7f08b4498bc3467872c3821c88a5fb1f6afc`.

The official Mermaid CLI export attempt was also made with the pinned command, but package
resolution was blocked by DNS. The repository-local deterministic exporter generated both reviewed
assets without network access.

### Focused tests and static checks

```text
pytest -q --no-cov tests/unit/test_phase13_portfolio.py \
  tests/integration/test_api_phase03.py tests/smoke/test_dashboard_startup_phase06.py
PASS — 18 passed in 2.56 seconds.

make lint
PASS — 226 files formatted; Ruff found no issue.

make typecheck
PASS — strict Mypy found no issue in 77 source files.

bandit -q scripts/export_portfolio_architecture.py scripts/validate_portfolio.py
PASS — no finding.

README Bash extraction | bash -n
PASS — every README Bash block parsed.

./scripts/check_no_secrets.sh
PASS — basic defense-in-depth secret/file check.

LC_ALL=C sort -c FILE_MANIFEST.txt
git diff --check
PASS — approved manifest sorted and at exact tracked/untracked source parity; no whitespace error.
```

The focused command used `--no-cov` safely because none of those 18 tests carries the repository's
`no_cover` marker.

### Full-suite and release-gate boundary

The first nested sandbox run completed 598 tests and failed only
`test_measured_local_prediction_load_targets`. Coverage was 83.56%, above the 70% gate. That
CPU-throttled sandbox produced 8.78 requests/second, zero errors, and 628.43 ms p95 against the
unchanged 25 requests/second and 250 ms thresholds. Two isolated sandbox reruns produced 8.25 and
9.44 requests/second with zero errors. The latter used single-threaded BLAS settings and did not
change the threshold. These remain recorded as failed environment evidence, not passes.

An exploratory isolated `--no-cov` load invocation stopped inside pytest-cov's known `no_cover`
marker hook before the test body. The subsequent isolated commands kept the plugin active and set
only the narrow coverage floor/report to zero, preserving the measured test body and thresholds.

In the same nested sandbox, `make security` ran Bandit and exported strict hashed requirements, then
pip-audit stopped because DNS could not resolve PyPI. The repository-local security scan separately
refused because the then-cached Checkov OCI image failed its pinned integrity preflight. Those two
results remain explicit environment failures and are not relabeled as passes.

The first unrestricted-host rerun executed `make release-gates` without a policy or threshold
change. It passed with 599 tests and 83.56% coverage, including the measured-load test. A separate
captured run of that unchanged test measured 42.02 requests/second, zero errors, and 140.41 ms p95.
The final Phase 13 closure run added the one new adversarial media-symlink regression and passed 600
tests at the same 83.56% coverage; the canonical release target also ran the integrated portfolio
gate over the final assets and public claims. Strict hashed pip-audit reported no known
vulnerabilities. The verified scanner set was actionlint 1.7.9, ShellCheck 0.11.0, Checkov 3.3.9,
Gitleaks 8.30.1, and Trivy 0.70.0. Checkov reported 475 passing Terraform checks, 317 passing
Dockerfile checks, and 956 passing GitHub Actions checks, with zero failures; the policy-controlled
ShellCheck, Gitleaks, and Trivy gates also passed. These successes do not erase the earlier sandbox
failures; they prove the same gates on the unrestricted host.

## Generated and tracked artifacts

```text
README.md
docs/CASE_STUDY.md
portfolio/architecture-export.md
portfolio/architecture.mmd
portfolio/assets/demo/modelguard-demo.mp4
portfolio/assets/demo/modelguard-drift.gif
portfolio/assets/modelguard-architecture.png
portfolio/assets/modelguard-architecture.svg
portfolio/claims-ledger.md
portfolio/demo-script.md
portfolio/fiverr-packages.md
portfolio/linkedin-post.md
portfolio/screenshot-checklist.md
portfolio/skills-to-evidence.md
portfolio/upwork-portfolio.md
scripts/export_portfolio_architecture.py
scripts/validate_portfolio.py
tests/unit/test_phase13_portfolio.py
```

The isolated 861 MiB temporary copy—including its seeded virtual environment, failed empty-cache
environment, generated dataset, MLflow state, bundle, events, and reports—was removed after evidence
capture. No generated model/data artifact was added to Git, and that temporary deletion is not
recoverable.

## Residual risks

- The nested sandbox could not prove an unrestricted browser/curl session and produced the recorded
  performance, DNS, and Checkov-cache failures. The final unrestricted-host release gate and
  measured-load run passed separately as recorded above.
- PyArrow 25's bundled mimalloc backend crashed twice at the same allocator function on this VMware
  host; the reviewed capture used Arrow's `system` pool after a successful live-browser stability
  check. This is an environment-specific capture-runner constraint, not hidden application evidence.
- Phase 13 does not freshly inventory AWS. Teardown remains the authoritative Phase 10 record.
- Platform copy may need minor character-count trimming when pasted into LinkedIn, Upwork, or Fiverr;
  trimming must preserve the synthetic/temporary/label and availability boundaries.

## Closure

The complete Phase 13 scope is recorded by the commit containing this report with message:

```text
docs: package Phase 13 portfolio assets
```

That commit is published from a dedicated branch through the repository's protected pull-request
path and merged only after all four required checks pass. The immutable commit, PR, and merge
identities are reported in the closure handoff rather than embedded into their own source. No AWS
operation is part of this closure, and Phase 12 remains not started.

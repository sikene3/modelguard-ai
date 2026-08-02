# Phase 07 Report

## Objective

Package the API, read-only dashboard, and one-shot monitor as hardened role-specific images, then
prove the complete local synthetic workflow through Docker Compose, deterministic traffic,
repeatable smoke/demo/failure scripts, machine-readable evidence, and a strict critical-vulnerability
policy.

## Completion status

**Complete — technical GO for Phase 07.** All required images build, the exact Compose `up --build`
path starts the local services, all five required scenarios pass, the final images have zero critical
Trivy findings with zero exceptions, and the complete quality/security gate passes. Phase 07 is
recorded as `completed`.

This does not authorize Phase 08. The current uncommitted tree still requires an independent human
review and a manual commit. No Docker deployment, Terraform, GitHub workflow, AWS client/resource,
live AWS change, or Phase 08 implementation was introduced.

## Scope implemented

- Added separate two-stage API, dashboard, and monitor Dockerfiles. All stages use the same official
  Python 3.12.13 Alpine 3.23 index pinned by immutable digest. uv is pinned in build stages; final
  stages contain source plus role-specific lock-backed virtual environments.
- Restricted the build context to an explicit allowlist of project/lock metadata, application source,
  and Streamlit configuration. Generated artifacts, credentials, tests, infrastructure, `.env`, and
  the model bundle do not enter the builder.
- Added OCI source-revision and exact `uv.lock` SHA-256 labels. The build wrapper resolves the actual
  Git worktree identity; direct Compose builds retain an explicit `local-uncommitted` default.
- Declared numeric runtime user/group `10001:10001` in every image and repeated it in Compose. Root
  filesystems are read-only, all capabilities are dropped, setuid/setgid bits are removed, `/tmp` is
  bounded and no-execute, and the Docker socket is never mounted.
- Added API readiness, Streamlit process, and monitor import/non-root health checks.
- Added distinct runtime dependency groups for API, dashboard, and monitor. Compilers, GFortran,
  headers, uv, build caches, MLflow, and developer/security test packages are absent from final
  images. Only `libgomp` and `libstdc++` remain for the source-built scikit-learn runtime.
- Added a local-only Compose application. API and dashboard are long-running. The one-shot monitor is
  part of a plain build but has default scale zero and runs only through an explicit Compose job.
- Mounted the seven trusted-bundle files and the exact Phase 07 monitoring configuration read-only,
  with missing sources rejected. Prediction events and reports use one synthetic named volume under
  validated per-run directories. The workflow needs no AWS credentials or service.
- Added deterministic baseline, drifted, and tiny traffic generation over loopback only. Responses
  are contract-validated and bounded aggregate evidence is written atomically.
- Added `smoke_local.sh` for health, prediction, persisted event metrics/counts, graceful event-file
  closure, monitor publication, dashboard availability, image provenance, and absence of baked
  artifacts.
- Added `demo_local.sh` for isolated Healthy to Drifted evidence with distinct immutable report IDs.
- Added `e2e_local.sh` for honest insufficient-data handling, corrupt-bundle refusal without identity
  disclosure, and observable fail-open sink outage behavior.
- Added strict, versioned evidence validators and a critical-only Trivy evaluator. Any exception must
  exactly match image/CVE/package and carry a substantive rationale, owner, and expiry within 90
  days. Duplicate, expired, stale, unmatched, malformed, and non-finite JSON input fails. The
  committed exception list is empty.
- Added clean-clone, scenario, remediation/exception, troubleshooting, cleanup, and command
  documentation plus Make targets for every Phase 07 action.

## Review and validation repairs

The maximum-effort review repaired genuine defects instead of weakening gates:

1. The monitor originally used a profile, which omitted it from the required plain build. It is now
   always modeled with default scale zero.
2. Default UTC run stamps used uppercase characters that violated the path-safe namespace contract.
   Shared lowercase run stamps now satisfy the same validator used by all scripts.
3. Corrupt-bundle evidence did not verify the version/manifest identity boundary. It now proves
   liveness, not-ready/prediction 503 responses, and null model identities.
4. Bind mounts now use `create_host_path: false`, and only the exact Phase 07 monitoring file is
   mounted rather than the entire configuration directory.
5. Compose discovery originally rejected the installed standalone Compose 5.3.1. It now accepts any
   plugin or standalone numeric major version 2 or newer.
6. Relocated virtual-environment console-script shebangs still pointed at the discarded build path.
   API and dashboard commands now use `python -m`, which is relocation-safe.
7. Evidence and scan JSON readers now reject duplicate keys and non-finite values through the shared
   strict serializer.
8. The sink-outage E2E exposed an existing Phase 04 boundary defect: local directory-creation
   failures escaped the typed sink exception and were counted as generic failures. The sink now
   translates that `OSError` to `LocalEventWriteError`, preserving the documented `local_failed`
   telemetry and prediction fail-open behavior. A focused regression test was added.
9. ShellCheck found one repository-wide unchecked `cd` in `verify_environment.sh`; the minimal
   fail-fast correction was applied.
10. The first authoritative Trivy scan of the pinned Debian Bookworm images failed with six
    no-fixed-version critical findings per image (`zlib1g`, `libsqlite3-0`, and four `perl-base`
    findings). No exception was created. A current official Alpine Python 3.12 base was compatibility-
    tested against the full locked scientific imports, pinned by digest, built, and rescanned. The
    final images have zero critical findings.
11. Transient package-download failures in cold parallel builds were bounded with a 120-second uv
    HTTP timeout and a shared locked BuildKit cache. A normal cached rebuild remains deterministic
    against `uv.lock`.

The local Docker daemon rejects both injected `docker-init` and `no-new-privileges:true` execution,
including trivial stock-image probes, with `operation not permitted`. Those optional Compose flags
are therefore not asserted here. Application processes handle their own signals; graceful closure
was exercised repeatedly. Numeric non-root execution, read-only roots, `cap_drop: ALL`, stripped
setuid/setgid files, loopback exposure, and no Docker socket remain enforced and directly inspected.

## Runtime environment

- Docker client 29.1.3; Docker Engine 29.6.1.
- Standalone Docker Compose 5.3.1, selected through the repository compatibility wrapper.
- Isolated Compose project `modelguard-phase07-review` on loopback ports 18070 and 18507; negative
  scenarios used 18071 and 18072.
- Unrelated root-owned services on ports 8000 and 8501 were not stopped, modified, or inspected for
  application content.
- Trivy 0.72.0 with vulnerability database updated at 2026-08-02T13:11:51Z.
- ShellCheck 0.11.0.

## Validation evidence

### Build, Compose, and image boundary

```text
./scripts/build_local_images.sh
PASS — API, dashboard, and monitor built from the pinned Alpine digest. Build context was allowlisted;
source revision was MGH06___________________________________-dirty and uv.lock SHA-256 was
d91aa5086e9ef4a0fc03802abf77277f988e2aba974c21c8426b5f7ec522a9fd.

SOURCE_REVISION=<resolved> UV_LOCK_SHA256=<resolved> docker-compose up --build -d
PASS — exact build/start path completed; API and dashboard became healthy.

root/non-root image inspection, import probes, apk package probes, and docker inspect
PASS — effective image and Compose user 10001:10001; no setuid/setgid executable; no build-base,
GFortran, pytest, Ruff, Mypy, Bandit, pip-audit, MLflow, or uv; required role imports succeed;
read-only roots, cap-drop ALL, and loopback-only bindings are active.
```

Final unpacked image sizes were:

- API: 151,372,624 bytes.
- Dashboard: 255,127,539 bytes.
- Monitor: 149,605,358 bytes.

### Scenario evidence

```text
COMPOSE_PROJECT_NAME=modelguard-phase07-review ... ./scripts/smoke_local.sh
PASS — smoke-20260802t194142z-91810; API live/ready, dashboard ok, model 1.0.0, 601 persisted
target events, report 73f2823c5f0df24ca909ddefc59102e62118203d6b12b2bc0f9cb2cb97b6a06f,
and states succeeded/valid/healthy/unknown.

COMPOSE_PROJECT_NAME=modelguard-phase07-review ... ./scripts/demo_local.sh
PASS — demo-20260802t194241z-94190; baseline report
16c7443edf78c4cabb2b7dff8d267a703ec6651bad9dafd33979b09b1f63fb34 remained healthy; isolated
drifted report 972409bf7e667240c2bdaea19bb0612df0aba866adddce85689d0f98449e834d was degraded;
dashboard remained available.

COMPOSE_PROJECT_NAME=modelguard-phase07-review ... ./scripts/e2e_local.sh
PASS — e2e-20260802t194449z-98262; insufficient_data, corrupt_bundle, and sink_outage all passed.
The outage request remained HTTP 200 and emitted local_failed/event_sink metrics.

live headless Google Chrome against http://127.0.0.1:18507
PASS — Streamlit root rendered with the expected dashboard title; no validation-owned browser process
remained active.
```

### Image vulnerability evidence

```text
PATH=<verified-trivy-0.72.0> ./scripts/scan_local_images.sh
PASS — modelguard-api:local: 0 critical, 0 exceptions, 0 unaccepted.
PASS — modelguard-dashboard:local: 0 critical, 0 exceptions, 0 unaccepted.
PASS — modelguard-monitor:local: 0 critical, 0 exceptions, 0 unaccepted.
```

The policy stayed strict throughout; no scan finding was ignored and
`configs/trivy-exceptions.json` remains empty.

### Python, shell, dependency, secret, and bundle gates

```text
uv run --frozen --no-sync pytest -q --no-cov tests/unit/test_phase07_local_containers.py
PASS — 14 focused tests.

affected Phase 04 event/sink tests plus Phase 07 local-container tests
PASS — 26 focused regression tests.

PATH=<shellcheck-0.11.0> ./scripts/check_shell.sh
PASS — Bash syntax and ShellCheck passed for all 13 shell scripts.

PATH=<shellcheck-0.11.0> make verify
PASS — Ruff format/check: 160 files; strict Mypy: 52 source files; Pytest: 199 passed in 18.95
seconds at 84.74% branch coverage; Bandit: no finding; strict hashed pip-audit: no known
vulnerabilities; basic redacted secret/file scan: passed; trusted bundle verification: passed.

UV_CACHE_DIR="$PWD/.cache/uv" uv lock --check --offline
PASS — the lock resolves offline without changing uv.lock.

trusted bundle verification only
PASS — version 1.0.0, manifest
49cbe04bc4285fc71463d0071e3babc3a5f5c20011541a072b4844bb5c78afd9, smoke score
0.9981110662188358. The immutable Phase 02 bundle was not retrained or overwritten.

git diff --check; strict JSON/TOML/YAML and Compose syntax; manifest/language/disposable/scope scans
PASS — no whitespace, syntax, manifest-parity, Arabic-character, secret, cache, temporary-project-
file, or future-phase scope finding.
```

## Generated evidence

Generated validation artifacts are ignored and are not commit candidates:

- `artifacts/phase-07-evidence/build/images.json` — SHA-256
  `bd8f189a69e67a5ee0dfba72908c52c5381858d4a7d1ad74bc356fa5f4a8901a`.
- `artifacts/phase-07-evidence/trivy-20260802T200112Z/summary.json` — SHA-256
  `d85b1ac6ad8a52e207ce0b8a3b8861f361945d9a5d61420824ee895d9ad607e0`.
- `artifacts/phase-07-evidence/smoke-20260802t194142z-91810/smoke-summary.json` — SHA-256
  `8696019f0493545f685cb7ad23c2ded6bb4fe7f0428a5ae4973f1ed3dbbe9b60`.
- `artifacts/phase-07-evidence/demo-20260802t194241z-94190/demo-summary.json` — SHA-256
  `d69a0d4e3a1fecb5cc7ada42a6590aec6de450358185612c888d6e41e35ea11a`.
- `artifacts/phase-07-evidence/e2e-20260802t194449z-98262/e2e-summary.json` — SHA-256
  `a2c4044d42646eeb466b3f488a2347720ee444023463a00d107cc4165f826b9c`.

## Files changed

- Container definitions: `.dockerignore`, `docker-compose.yml`, deletion of the replaced
  `docker/.gitkeep`, and `docker/{api,dashboard,monitor}.Dockerfile`.
- Runtime contracts: `pyproject.toml`, `uv.lock`, `configs/phase-07-monitoring.json`, and
  `configs/trivy-exceptions.json`.
- Local orchestration/evidence: `scripts/{build_local_images,check_shell,demo_local,e2e_local,
  local_compose_lib,scan_local_images,smoke_local}.sh` and
  `scripts/{evaluate_trivy_scan,generate_local_traffic,validate_local_evidence}.py`.
- Tests: `tests/unit/test_phase07_local_containers.py` plus the focused Phase 04 sink regression.
- Narrow affected-contract repairs: `src/modelguard/inference/events.py` and
  `scripts/verify_environment.sh`.
- Commands/docs/records: Make/environment/start files, container demo and related security/demo/
  troubleshooting/command docs, acceptance criteria, checklist, phase status, manifest, and this
  report.

## Decisions, assumptions, and residual risks

- The monitor remains a one-shot job, not a daemon.
- Phase 07 changes only the local-demo finalization grace to zero. Phase 05's ten-minute monitoring
  policy and all production-style classification contracts are unchanged.
- Monitoring enumerates only closed `*.jsonl` files after a graceful API restart; active files are
  never read.
- Individual read-only bundle-file mounts expose exactly the seven trusted inputs to the fixed UID.
- Trivy results are time-bound and must be repeated for any release build. The current result is not
  a perpetual vulnerability-free claim.
- The final images were labeled from an intentionally dirty Phase 07 worktree. A later release must
  rebuild from the independently reviewed commit so its OCI revision is the exact clean Git SHA.
- Compose lacks the optional kernel `no-new-privileges` flag on this incompatible local daemon. The
  compensating non-root/setid/capability/read-only boundaries passed, but a later compatible runtime
  should re-evaluate enabling that flag.
- This is a local, synthetic, production-style demo. It is not production-ready and does not prove
  AWS networking, IAM, persistence, availability, or deployment behavior.

## Acceptance and phase decision

- **Phase 07 technical decision: GO.** The checklist and container acceptance items are complete.
- **Phase 08 decision: NO-GO until independent human review and a manual Phase 07 commit.**

## Exact next manual action

Review the complete Phase 07 diff and this evidence report, confirm that only the approved Phase 07
paths and the two documented narrow regression repairs are present, stage only those paths, and
create the manual commit. Then confirm a clean worktree before considering Phase 08. Do not push or
start Phase 08 as part of that review unless separately requested.

## Suggested commit message

`feat: add verified Phase 07 containerized local demo`

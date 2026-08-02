# Phase 03 Report

## Objective

Serve the immutable Phase 02 model bundle through a strict, observable FastAPI application whose
process liveness is independent from verified-model readiness, with explicit local and restricted
AWS access-mode contracts.

## Scope completed

- Added a strict Pydantic v2 prediction request that exactly mirrors the frozen Phase 02 feature
  order, types, numeric bounds, and categorical domains. Extra fields, nulls, coercion-sensitive
  values, out-of-range values, and non-finite values fail with a sanitized response that does not
  echo inputs.
- Added the successful response contract with a server-generated UUID request ID, finite `[0,1]`
  score, locked-threshold `low_risk | high_risk` decision, semantic model version, and non-negative
  measured latency.
- Reused the Phase 02 ordered bundle verifier. Startup validates the exact seven-file structure,
  symlink policy, checksums, strict manifest/schema/metrics/threshold/baseline contracts, cross-file
  identities, configured active version, trusted origin, model classes/shape, and a smoke score. It
  installs one in-memory predictor and never reloads per request.
- Added application lifespan behavior that keeps `/health/live` available if model loading fails,
  returns minimal `503 {"status":"not_ready"}` readiness, exposes no bundle path or exception text,
  stops prediction admission during shutdown, bounds sink cleanup, and closes the owned inference
  executor.
- Added `/health/live`, `/health/ready`, `/version`, `/metrics`, and `POST /v1/predict`. The version
  endpoint reports service version plus durable model identity without filesystem details.
- Added pure ASGI operational middleware that generates correlation IDs, bounds declared and
  streamed bodies before FastAPI parsing, caps concurrent prediction admission with a bounded wait,
  normalizes route/method telemetry labels, injects the request ID response header, and logs only
  safe fixed request metadata.
- Added an application-owned bounded inference executor. Request admission and model worker count
  are separate typed settings; the small CPU-bound sklearn model defaults to one worker to avoid
  thread contention while retaining a bounded request queue.
- Added one-line structured JSON logging with centralized key/value redaction. Uvicorn access logs
  are disabled because they may contain query strings. Application logs never include bodies,
  feature values, auth headers, tokens, direct user/event identifiers, environment dumps, or
  exception messages. Configured secrets are redacted across string, byte, path, enum, collection,
  and fallback object representations.
- Added per-application Prometheus counters/histograms for HTTP requests/latency, predictions by
  decision, model-load attempts/duration, closed-category errors, and event-sink outcomes/duration.
  No mutable global registry is used.
- Added a dependency-injected telemetry protocol and composite implementation. AWS mode adds
  EMF-compatible stdout JSON whose only dimensions are the fixed `Service`, `Environment`, and
  `AccessMode`; request/event IDs, tokens, features, and model versions are never dimensions.
- Added typed access modes. AWS settings reject local-open mode and missing, world-open, or
  noncanonical ALB CIDRs. `https_token` requires an SSM parameter ARN, an ECS-injected `SecretStr`,
  ALB-forwarded HTTPS, no query parameters, and constant-time bearer comparison.
  `http_cidr_only` rejects Authorization and makes no authentication or secure-transport claim.
  Health routes are token-exempt; AWS docs are disabled; `/metrics` returns 404 in AWS mode and
  future ALB routing must also exclude it.
- Added only a no-op async prediction-event interface seam. Calls and cleanup are time-bounded,
  failures are observable and fail open, and no local/AWS event persistence or AWS client was
  pre-built before Phase 04.
- Added bounded Uvicorn `make api`, reusable local `make load-test`, a committed strict example
  request, local/AWS curl examples, configuration/security documentation, and current-status docs.

## Files changed

- Service: `src/modelguard/api/{main,dependencies,errors,middleware,routes,schemas}.py` and package
  documentation.
- Inference: `src/modelguard/inference/{loader,predictor,events}.py`.
- Runtime boundaries: `src/modelguard/core/{config,logging,telemetry}.py`.
- Tests: `tests/unit/test_{api_schemas,inference,telemetry_logging}_phase03.py`, expanded settings
  tests/fixtures, `tests/contract/test_api_contract_phase03.py`, and
  `tests/integration/test_api{,_load}_phase03.py`.
- Commands/examples/docs: `Makefile`, `.env.example`, `scripts/load_test_api.py`,
  `examples/prediction-request.json`, `README.md`, `GETTING_STARTED.md`, `START_HERE.sh`, and
  `docs/10_COMMANDS_CHEATSHEET.md`.
- Phase records: `ACCEPTANCE_CRITERIA.md`, `checklists/PHASE_03.md`, `tasks/phase_status.json`,
  `FILE_MANIFEST.txt`, and this report.

## Commands and evidence

```text
UV_CACHE_DIR=.cache/uv uv sync --all-groups --locked --offline
PASS — resolved 159 packages and checked the existing environment using a writable copy of the host
uv cache. The initial direct uv attempt could not write the host cache; the first empty project-cache
attempt could not reach PyPI because outbound DNS is disabled.

UV_CACHE_DIR=.cache/uv uv run pytest tests/unit tests/integration -q  # pre-change baseline
PASS — 52 existing Phase 02 tests passed with 84.99% coverage.

UV_CACHE_DIR=.cache/uv uv run pytest <focused Phase 03 unit files> -q
PASS — 30 focused settings/schema/loader/predictor/telemetry/logging tests.

UV_CACHE_DIR=.cache/uv uv run pytest tests/contract/test_api_contract_phase03.py -q
PASS — 2 API/OpenAPI contract tests.

UV_CACHE_DIR=.cache/uv uv run pytest tests/integration/test_api_phase03.py -q
PASS — 7 readiness/access/body/concurrency/timeout/redaction integration tests.

UV_CACHE_DIR=.cache/uv uv run pytest tests/integration/test_api_load_phase03.py -q -s
PASS — 100 requests at concurrency 4; 42.11 requests/second, 0.0000 error rate, and 131.74 ms p95.
Targets: >=25 requests/second, exactly 0% errors, and <=250 ms p95. The performance body is marked
`no_cover` so line tracing does not distort timing; all other tests retain coverage.

UV_CACHE_DIR=.cache/uv uv run pytest tests/unit tests/contract tests/integration -q
PASS — final source: 92 passed in 8.65s; 85.73% total branch coverage.

make train TRAINING_OUTPUT_ROOT=/tmp/modelguard-phase03-training.<random>/artifacts
PASS — a fresh isolated run generated, trained, inspected, and trusted-origin verified version 1.0.0
without overwriting the canonical immutable Phase 02 output. Held-out average precision was
0.40842191798974226 versus prevalence 0.188; threshold 0.075; inspection reported 750 test rows;
the smoke score was 0.9981110662188358. The temporary output and sibling MLflow store were removed
after verification.

make api API_PORT=18083
PASS — Uvicorn bound to 127.0.0.1:18083 with one worker, connection concurrency 64, five-second
keep-alive, ten-second graceful shutdown, and access logs disabled. The model loaded in 56.624 ms
with version 1.0.0 and manifest SHA-256
49cbe04bc4285fc71463d0071e3babc3a5f5c20011541a072b4844bb5c78afd9. SIGINT produced complete
application/worker graceful-shutdown logs.

curl required live/ready/version/predict/metrics checks against TCP Uvicorn
PASS — liveness and readiness returned their minimal 200 contracts; `/version` returned the active
version and manifest digest; prediction returned a UUID, finite score 0.9981110662188358,
`high_risk`, model version 1.0.0, and measured latency; Prometheus exposed request, latency,
prediction, model-load, and event-sink series.

make load-test API_PORT=18083
PASS — 100 real TCP requests at concurrency 4; 45.78 requests/second, 0.0000 error rate, and
109.22 ms p95 against targets of >=25 requests/second, exactly 0% errors, and <=250 ms p95.

make inspect-model
PASS — metadata/checksum/identity validation, no deserialization; version 1.0.0, threshold 0.075,
750 held-out test rows.

make verify-model
PASS — trusted-origin model verification; smoke score 0.9981110662188358 and exact manifest identity.

make verify
PASS — 115 files were Ruff-formatted; Ruff lint passed; strict Mypy passed for 36 source files; 94
tests passed in 9.09s with 85.73% branch coverage; Bandit reported no findings; strict hashed
`pip-audit` reported no known vulnerabilities; the basic secret/file scan passed; and the canonical
trusted-origin model bundle verified. The initial sandbox run found a Bandit B105 false positive on
an enum member named `HTTPS_TOKEN`; the internal member was renamed without suppressing Bandit.

UV_CACHE_DIR=.cache/uv uv run pytest -q  # after final logging/cancellation hardening
PASS — superseded by the final `make verify` result above: 94 passed with 85.73% branch coverage.

./scripts/check_no_secrets.sh
PASS — defense-in-depth secret/file scan passed.

UV_CACHE_DIR=.cache/uv uv lock --check --offline
PASS — 159 locked packages resolved offline without lock changes.

UV_CACHE_DIR=.cache/uv uv run bandit -q -r src
PASS — no findings after the enum-name repair.

bash -n START_HERE.sh scripts/*.sh
PASS — all shell entry points, including the load command wrapper context, are syntactically valid.
```

The canonical Phase 02 output was not overwritten because bundle creation correctly refuses an
existing `artifacts/model-bundles/1.0.0`. Instead, the full `make train` workflow ran against a fresh
temporary output root, while the canonical bundle was independently inspected, trusted-origin
verified, loaded by live Uvicorn, and exercised throughout the API tests.

## Tests

- Unit: strict schema/bundle-schema parity, invalid/coerced/non-finite/extra/null inputs, settings
  invariants, trusted loader/version failure cases, predictor threshold semantics, Prometheus, EMF
  dimension allowlist, and structured logger redaction.
- Contract: exact route/OpenAPI fields, minimal health, durable version, response types/keys,
  one-time loader behavior, metrics exposition, and sanitized invalid-request responses.
- Integration: corrupt and missing bundle readiness; health exemption; forwarded-HTTPS and bearer
  enforcement; constant-time comparison invocation; query-token prohibition; CIDR-only credential
  rejection; declared and streamed body caps; bounded/rejected concurrent requests; fail-open sink
  timeout; graceful sink close; token/header/query/body log redaction.
- Load: 100 successful in-process HTTP predictions at concurrency 4 with explicit throughput,
  error-rate, and p95 assertions.
- Full suite on final source: 94 passed (92 required unit/contract/integration plus 2 smoke), 85.73%
  branch coverage.

## Generated artifacts

- Existing verified bundle: `artifacts/model-bundles/1.0.0/`; identity
  `{model_version: 1.0.0, manifest_sha256:
  49cbe04bc4285fc71463d0071e3babc3a5f5c20011541a072b4844bb5c78afd9}`.
- Approved project example request: `examples/prediction-request.json`.
- Phase evidence: `reports/phase-03.md`.
- Ephemeral test caches, coverage data, and runner logs were removed after evidence capture; no new
  committed model, prediction-event, AWS, or large generated artifact was created.

## Decisions/assumptions

- The configured bundle is a trusted local/publisher-controlled joblib origin. Checksums provide
  corruption detection, not authenticity; the API preserves the explicit trusted-origin setting.
- The active semantic version is configured independently and must match the verified bundle. The
  manifest digest remains part of durable identity but is never a CloudWatch dimension.
- Request admission defaults to 64 while the small CPU-bound model executor defaults to one worker.
  This produced better local throughput/tail latency than simultaneous sklearn scoring and remains
  configurable within a validated `workers <= admission` bound.
- Local mode is open by design. Application checks supplement but do not replace the later private
  ECS networking, restricted ALB security group/routing, ACM listener, and ECS-to-SSM secret
  injection.
- The current Starlette release recommends a separate `httpx2` package for its synchronous
  `TestClient`; adding a new dependency was unnecessary. Tests use the supported async ASGI transport
  directly and explicitly enter application lifespan.
- The Phase 03 sink seam receives only the prediction result and does nothing. Phase 04 owns the
  versioned event payload, identifiers, persistence, retry, and delivery contracts.

## Residual risks

- Joblib remains pickle-based and unsafe for untrusted input. Checksums and a manifest do not provide
  signing or publisher authentication.
- `X-Forwarded-Proto` is meaningful only behind the later private, correctly configured ALB that
  overwrites the header; the application check alone is not a secure transport boundary.
- AWS ALB CIDR/listener/path routing, SSM injection, and task-network enforcement belong to Phase 08
  and are not yet deployable. Phase 03 tests only the typed settings and application route matrix.
- EMF is contract-tested JSON emitted through an injected writer; no CloudWatch ingestion is claimed
  before AWS deployment evidence exists.
- Python cannot force-terminate a native inference thread that is permanently stuck. Admission and
  worker pools are bounded and Uvicorn has a graceful-shutdown limit, but the later container/process
  supervisor remains the final hard-stop boundary for that failure mode.
- The model and load results describe a synthetic local demo, not real fraud validity or production
  capacity.

## Acceptance checklist status

All Phase 03 functional checklist items are implemented and tested. Fresh isolated training, the
required Python test gate, static checks, Bandit, live dependency auditing, secret scanning, bundle
verification, literal TCP curls/load, process startup, and graceful shutdown pass.

## Phase decision

**GO for Phase 04 after the authorized Phase 03 commit.** The dedicated human-review gate below is
complete, no unexplained Phase 03 failure remains, and no Phase 04 persistence, AWS client,
container, infrastructure, or workflow work was started.

## Dedicated pre-commit human-review gate

- Completely reviewed all 14 modified and 20 new files against `PROJECT_SPEC.md`,
  `ARCHITECTURE.md`, `ACCEPTANCE_CRITERIA.md`, the Phase 03 prompt, this report, and the Phase 03
  checklist.
- Confirmed all 34 paths are Phase 03 service, inference, runtime-boundary, test, command, example,
  documentation, or evidence files. No Phase 04 persistence, Docker, Terraform, GitHub workflow,
  AWS client, monitoring, dashboard, storage, or infrastructure implementation is present.
- Confirmed `NoOpPredictionEventSink` remains the default dependency-injected event boundary and
  performs no file or network I/O.
- Repeated the required unit/contract/integration suite: 92 passed in 9.31s with 85.73% branch
  coverage.
- Repeated literal Uvicorn health/version/prediction/metrics checks and measured load: 44.13
  requests/second, 0% errors, and 132.45 ms p95; graceful shutdown completed.
- Repeated `make verify`: Ruff format/lint, strict Mypy for 36 source files, 94 tests in 9.26s with
  85.73% branch coverage, Bandit, strict hashed `pip-audit`, the secret/file scan, and canonical
  trusted-bundle verification all passed.
- Repeated manifest parity, `uv lock --check --offline`, shell syntax, diff-whitespace, secret, and
  Arabic content/filename scans. All passed; the Arabic scans returned zero findings.
- Confirmed only ignored local `.venv`, Phase 02 generated artifacts, and the local MLflow store are
  retained outside the commit candidate set; disposable caches, coverage, bytecode, temporary
  files, and runner logs are excluded and removed before commit.

## Suggested commit message

`feat: add verified Phase 03 inference API`

## Next manual action

After committing the reviewed Phase 03 files, wait for an explicit Phase 04 instruction. Do not push
or start Phase 04 as part of this gate.

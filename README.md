# ModelGuard AI

ModelGuard AI is a production-style AWS MLOps portfolio project for a versioned synthetic
fraud-risk model, observable inference, and deterministic drift incident handling.

## Current status

Phases 07 and 08 package three digest-pinned, non-root images and define the separate retained AWS
bootstrap plus disposable demo Terraform architecture. Phase 09 adds SHA-pinned GitHub Actions for
quality/security evidence, full-history secret scanning, credentialless Terraform validation,
trusted non-applying plans, build-once image scanning/publication, and a protected two-plan demo
deployment with customized legacy/immutable OIDC subjects, notification-PII-free saved plans,
immutable ECR digests, smoke checks, and separate ECS/model rollback targets.
Phase 09.1 makes the five release scanners reproducible: one reviewed lock pins actionlint,
ShellCheck, Checkov, Trivy, and Gitleaks; the same repository scripts enforce them locally and in
GitHub Actions; and only sanitized SARIF is eligible for Code Scanning upload.

The Phase 10 local-runtime baseline is committed at `aad098c`; its follow-up blocker-remediation
commit is `e5095af`. That patch adds the exact Botocore browser-login CRT dependency and a
create-only, checksum-verifying, version-pinned model publisher with serialized active/previous
promotion and rollback. Phase 10 is closed: retained audit/bootstrap controls were applied with
encrypted state recovery, immutable images and model `1.0.3` were published, the restricted live
demo passed API/dashboard/Firehose/monitoring evidence checks, and the exact saved destroy plan left
zero disposable demo resources. The USD 10 Budget and retained audit/bootstrap controls remain by
design; Phase 11 has not started. See
[`docs/CICD_SECURITY.md`](docs/CICD_SECURITY.md),
[`docs/TERRAFORM_AWS.md`](docs/TERRAFORM_AWS.md), and `reports/phase-10.md`.

The architecture and acceptance contract are defined in [ARCHITECTURE.md](ARCHITECTURE.md),
[PROJECT_SPEC.md](PROJECT_SPEC.md), and [ACCEPTANCE_CRITERIA.md](ACCEPTANCE_CRITERIA.md).

## Requirements and setup

- Git, Make, and uv 0.12.x.
- Python is pinned by `.python-version` and `requires-python` to Python 3.12; developer commands use
  `uv run` and never rely on the host's unversioned `python3` command.
- Docker Engine and Docker Compose 2 or newer for Phase 07 and the repository-local Checkov OCI
  image. Terraform 1.10 or newer remains required for provider-backed infrastructure validation.
  The five security scanners are installed only under ignored `.cache/security-tools/` from the
  checksums or OCI digest in `security/security-tools.lock.json`; no global scanner install is used.

```bash
./scripts/verify_environment.sh
uv sync --all-groups --locked
uv run --frozen --no-sync python -m scripts.human_aws_login dependency
make security-tools-bootstrap
make security-tools-check
uv run python -c 'import modelguard; print(modelguard.__version__)'
```

`scripts/setup_ubuntu.sh` is a manual-only installation guide. It deliberately does not execute
remote installer scripts whose artifacts are not pinned and verified in this repository.

## Quality gates

```bash
make format       # apply Ruff formatting and safe lint fixes
make lint         # formatting and lint checks
make typecheck    # strict Mypy checks for src/ and deployment-control helpers
make test         # Pytest with branch coverage
make security     # Bandit, pip-audit, and a basic redacted secret/file check
make security-tools-bootstrap # install the exact repository-local scanner toolchain
make security-tools-check     # verify cached scanner versions and artifact identities
make security-scan # actionlint, ShellCheck, Checkov, Gitleaks, and Trivy
make release-gates # make verify plus every reproducible security scan
make api          # bounded local FastAPI server on 127.0.0.1:8000
make load-test    # test a separately running local API against explicit load targets
make docker-build # build the three provenance-labeled local images
make smoke-local  # verify container health, prediction, events, report, and dashboard
make demo-local   # run the repeatable Healthy -> Drifted container flow
make e2e-local    # exercise insufficient data, corrupt bundle, and sink outage
make scan-images  # scan exact local image IDs for HIGH/CRITICAL findings
make verify       # quality/security gates plus verification of the generated bundle
```

The repository-level shell secret check is basic defense in depth. `make security-scan` additionally
runs pinned Gitleaks against complete Git history and an approved current-worktree snapshot with
100% value redaction and exact, owned, expiring exceptions; neither replaces human review of staged
changes. See [docs/CICD_SECURITY.md](docs/CICD_SECURITY.md) for tool pins, suppression policy, SARIF
handling, and update procedure.

## Audited local training

The committed [Phase 02 configuration](configs/phase-02-training.json) fixes every seed, split,
preprocessing, estimator, calibration, threshold, and baseline parameter. After `make setup`, run:

```bash
make train          # one clean run; refuses an existing data directory or model version
make inspect-model  # verifies structure, checksums, strict JSON, and identities; no joblib load
make verify-model   # repeats metadata checks, confirms trusted local origin, then smoke-predicts
```

`make train` creates exactly one local MLflow run under `mlruns/` and generated evidence under
`artifacts/`. It is intentionally not an overwrite command. To create another model, review and
version the committed configuration and select a new immutable model version rather than deleting or
reusing an existing bundle identity.

The workflow has explicit evidence boundaries:

1. Generate and validate independent synthetic rows with stable `event_id` values; latent logits and
   probabilities never leave generator memory.
2. Persist and re-verify the canonical train/validation/test assignment and all membership hashes.
3. Fit and five-fold sigmoid-calibrate using training rows only.
4. Select and lock `score >= threshold` on validation over all 1,001 integer-thousandth candidates.
5. Freeze training-reference feature/score/decision distributions without making training-performance
   claims.
6. Score the held-out test once and publish those results as the public evaluation.

Generated outputs are:

```text
artifacts/data/                    dataset, config/quality manifests, split CSV/manifest
artifacts/training/1.0.0/          model card, data card, reliability/confusion plots
artifacts/model-bundles/1.0.0/     exact seven-file immutable bundle
mlruns/                            local file-backed MLflow experiment and one run
```

The bundle identity is `{model_version, manifest_sha256}`. Checksums detect accidental or malicious
byte changes but do not authenticate a joblib file's origin; deserialization therefore requires an
explicit trusted-origin confirmation after every structural, checksum, contract, and identity check.

## Local inference API

Create the immutable bundle once with `make train`, then start the API in a separate terminal:

```bash
make api
```

Liveness reports only process health. Readiness succeeds only after the bundle is fully verified and
loaded once; the service never reloads the model per request.

```bash
curl -fsS http://127.0.0.1:8000/health/live
curl -fsS http://127.0.0.1:8000/health/ready
curl -fsS http://127.0.0.1:8000/version
curl -fsS http://127.0.0.1:8000/metrics | head
```

Local mode is intentionally open. Send the exact extra-field-forbidding Phase 02 feature contract:

```bash
curl --fail-with-body \
  -H 'Content-Type: application/json' \
  --data '{
    "amount": 4200.0,
    "transaction_hour": 2,
    "velocity_1h": 8,
    "distance_from_home_km": 180.0,
    "device_risk_score": 0.82,
    "merchant_risk_score": 0.64,
    "is_new_device": true,
    "country_code": "EG",
    "device_type": "mobile"
  }' \
  http://127.0.0.1:8000/v1/predict
```

The successful response contains a server-generated request ID, a finite `[0,1]` risk score, the
locked-threshold decision, model version, and measured service latency. Application logs are
one-line JSON and deliberately omit request bodies, query strings, authorization headers, token
values, feature values, filesystem paths, and environment dumps. Uvicorn access logs are disabled
because they can include query strings.

### Versioned prediction events

Local mode is the default and writes active files under `artifacts/predictions/` with a
`*.jsonl.open` suffix. Graceful shutdown or explicit rotation publishes final `*.jsonl` files that
the sink never reopens; monitoring must read only a frozen enumeration of those closed files. Each
successful prediction
creates a distinct event UUID and one canonical newline-terminated JSON record containing the
request UUID, UTC timestamp, complete model/manifest/input-schema identity, the exact approved
synthetic feature allowlist, score, decision, and the same frozen latency returned by the API.

After stopping the API, inspect and parse the closed local file without tailing an active writer:

```bash
find artifacts/predictions -maxdepth 1 -type f -name '*.jsonl' -print
uv run python -c \
  'import json, pathlib; p=next(pathlib.Path("artifacts/predictions").glob("*.jsonl")); print([json.loads(line)["event_id"] for line in p.open()])'
```

Set `EVENT_SINK=disabled` only when an intentional, observable drop mode is needed. AWS application
mode permits `EVENT_SINK=aws` (with `FIREHOSE_STREAM_NAME`) or `disabled`; it rejects local event
persistence. A successful Firehose `PutRecord` is logged and measured only as producer acceptance.
GZIP S3 delivery under physical UTC arrival-time date/hour prefixes, native Firehose delivery
signals, and S3-prefix freshness are downstream contracts and are not claimed by the API.

The complete schema, retry semantics, local rotation rules, Firehose physical contract, and Phase 05
handoff are documented in
[`docs/PREDICTION_EVENT_CONTRACT.md`](docs/PREDICTION_EVENT_CONTRACT.md).

## Deterministic monitoring

After the verified bundle exists, generate and finalize explicit stationary and shifted windows:

```bash
uv run python scripts/generate_monitoring_fixture.py \
  --scenario baseline --window-end 2026-01-01T01:00:00Z
uv run python -m modelguard.monitoring.cli run \
  --window-end 2026-01-01T01:00:00Z --as-of 2026-01-01T01:10:00Z
uv run python scripts/generate_monitoring_fixture.py \
  --scenario drifted --window-end 2026-01-01T02:00:00Z
uv run python -m modelguard.monitoring.cli run \
  --window-end 2026-01-01T02:00:00Z --as-of 2026-01-01T02:10:00Z
```

The CLI prints the independent states, report ID, immutable JSON/HTML paths, checksums, and whether
the newer-window-only `latest.json` pointer advanced. The default paths are
`artifacts/predictions/` and `artifacts/reports/`. Tests pass all four `--target-*` fields explicitly;
the quickstart convenience derives and freezes the same exact tuple from the verified bundle.

The monitor uses `[start,end)` event time, a ten-minute finalization grace, and no row-level
delivery-lateness claim. The minimum is 500 accepted target events. No label source means
performance `unknown`; a configured inadequate source is `pending_labels`; only adequate strict v1
labels compute metrics and vote using the locked synthetic-cost delta. Drift never stands in for
accuracy or performance.

The full math, classification/state precedence, label contract, report identity exclusions,
conditional alert semantics, and AWS injected boundaries are documented in
[docs/MONITORING_CONTRACT.md](docs/MONITORING_CONTRACT.md). The portable report schema is
[contracts/monitoring-report-v1.schema.json](contracts/monitoring-report-v1.schema.json).

## Read-only operations dashboard

After at least one local monitoring report exists, start Streamlit in a dedicated terminal:

```bash
make dashboard
```

Open `http://127.0.0.1:8501`. The page takes one actual UTC snapshot on each Streamlit rerun and
shows the persisted report completion timestamp, report age, window age, and accepted-event age. It
does not call itself real-time and does not reinterpret distribution drift as accuracy or model
performance.

The dashboard includes:

- separate run, data-quality, drift, and label-backed performance cards;
- the configured active model identity beside the immutable report target identity;
- event/input-schema, baseline, configuration, window, and report identities;
- exact `raw = rejected + outside_window + known_non_target + duplicate + accepted_target` counts;
- monitor-computed top feature scores/states and exact policy thresholds only when the policy hash
  matches the report;
- numeric/categorical baseline-versus-window distributions and prediction score/decision history
  restricted to reports with matching target, baseline, and policy identities;
- an offline HTML download in local mode, or a short-lived HTTPS presigned download in S3 mode.

Local mode reads `MODEL_BUNDLE_PATH`, `LOCAL_REPORT_DIR`, and `MONITORING_CONFIG_PATH`. AWS mode uses
the S3 report repository plus exact typed Region, S3/CloudWatch/Logs endpoint, metric, log-group, and
dashboard identities. Injected-client tests prove healthy, missing, denied, wrong-Region, malformed,
and partial-outage behavior without network calls. Source health is separate from the four persisted
monitoring states and cannot silently display healthy data. Dashboard reads and monitor writes remain
limited to the private `monitoring/` prefix, including `monitoring/run-status.json`; generated
presigned URLs are never stored or logged.

The complete evidence/claim boundary is documented in
[docs/DASHBOARD_CONTRACT.md](docs/DASHBOARD_CONTRACT.md).

## Containerized local end-to-end demo

Create the immutable bundle once, build the three images with exact source/lock labels, then start
the API and dashboard:

```bash
make train                    # omit only when the verified 1.0.0 bundle already exists
./scripts/build_local_images.sh
docker compose up -d
./scripts/smoke_local.sh
./scripts/demo_local.sh
./scripts/e2e_local.sh
./scripts/scan_local_images.sh
docker compose down -v
make verify
```

The build uses separate lock-backed runtime dependency groups and the official
`python:3.12.13-alpine3.23` index pinned by digest. Final images run as numeric
`10001:10001`, declare health checks, omit development dependencies and build toolchains, and never
contain the model bundle, `.env`, credentials, events, or reports. Compose repeats the non-root
identity, makes root filesystems read-only, drops all Linux capabilities, disables privilege
escalation by stripping setuid/setgid executables, binds ports to loopback, and mounts neither the
Docker socket nor any AWS service.

`smoke_local.sh` sends one explicit prediction plus at least 600 deterministic baseline requests,
gracefully restarts the API to publish its active event file, runs the one-shot monitor, and checks
for `run=succeeded`, `data_quality=valid`, `drift=healthy`, and `performance=unknown`. It also checks
image users, health checks, source/lock labels, event metrics, dashboard health, and the absence of
baked artifacts. `demo_local.sh` uses isolated event streams to prove Healthy → Drifted with two
distinct immutable report IDs. `e2e_local.sh` proves small-sample honesty, corrupt-bundle readiness,
and sink fail-open behavior.

Every default run uses a unique directory namespace inside the named volume and writes a validated
JSON summary under `artifacts/phase-07-evidence/<run-id>/`, so reruns do not delete or mix earlier
inputs. Phase 07 uses a committed zero-grace local-demo monitoring policy solely to finalize real
just-sent local traffic; the Phase 05 ten-minute policy remains unchanged.

The complete clean-clone, image, evidence, scenario, cleanup, and Trivy exception contracts are in
[docs/CONTAINER_LOCAL_DEMO.md](docs/CONTAINER_LOCAL_DEMO.md).

The measured local gate uses 100 requests at concurrency 4 and requires at least 25 requests/second,
zero errors, and p95 latency at most 250 ms:

```bash
make load-test
```

### AWS access-mode contract

Phase 03 implements the API access boundary, and Phase 04 adds a lazily constructed, event-only
Firehose client. Neither phase creates AWS infrastructure. Every later AWS ALB must use an explicit
restricted `ALB_ALLOWED_CIDR`; settings reject a missing, world-open, or noncanonical CIDR.

- `https_token` requires ALB-provided HTTPS, then checks `Authorization: Bearer` in constant time.
  ECS must inject `PREDICTION_BEARER_TOKEN` from the separately configured pre-created SSM
  SecureString ARN in `PREDICTION_TOKEN_SSM_ARN`. The token value must never enter Terraform state,
  files, command history, logs, screenshots, or metric dimensions. Query parameters are forbidden.
- `http_cidr_only` accepts prediction requests without a reusable token and rejects an Authorization
  header. It is a short-lived, restricted-CIDR, synthetic-only fallback. It provides neither secure
  transport nor authentication.

Health routes are token-exempt and minimal for ALB checks. `/version` remains CIDR-restricted at the
ALB. `/metrics` is a local/test Prometheus surface: the application returns 404 for it in AWS mode,
and the ALB must not route it publicly. AWS custom application signals use fixed-dimension EMF JSON
on stdout instead.

The supported authenticated AWS smoke invocation is the hardened script used by the protected
deployment workflow:

```bash
./scripts/smoke_aws.sh
```

The protected workflow supplies the required environment contract. The script validates and removes
the bearer from the exported environment before curl starts, then sends the Authorization header
only through anonymous `curl --disable --config -` stdin. Do not reproduce the request with a token
in curl arguments, an exported child environment, a command-history entry, or a temporary config
file.

The restricted HTTP fallback deliberately sends no credential:

```bash
curl --fail-with-body \
  -H 'Content-Type: application/json' \
  --data @examples/prediction-request.json \
  http://restricted-demo.example/v1/predict
```

### AWS code-only runtime readiness

The API hydrates an empty ECS runtime volume from the exact SSM pointer and seven S3 VersionIds,
verifies all bundle bytes and identities before trusted deserialization, installs atomically, and
remains not-ready after any interruption or corruption. The monitor image exposes a bounded one-shot
`aws-run` command with deterministic JSON output and separate configuration/access/evidence/sink exit
codes. The dashboard uses explicit regional evidence-source health without recalculating monitoring.

`scripts/verify_release_runtime.sh` tests these interfaces inside the actual immutable images and
emits a source/image-bound verification record. Activation rendering refuses to set
`runtime_contract_verified=true` without a matching digest-mode record; the committed default stays
false. See [docs/AWS_RUNTIME_CONTRACTS.md](docs/AWS_RUNTIME_CONTRACTS.md).

The operator-only `aws-operator` dependency group pins `awscrt==0.36.0`, exactly matching locked
Botocore's browser-login extra, while all runtime-image groups exclude it. The local dependency check
above performs no AWS call. After prerequisite infrastructure exists and a separate publication
approval is granted, `scripts.model_bundle_publisher` verifies the exact seven-file bundle locally,
refuses any prior S3 version history for the semantic version, conditionally creates and reads back
every object, and promotes active/previous under a conditional S3 lock. It writes no local file and
accepts no credential or secret-value argument. The exact future command and failure recovery are in
[docs/08_AWS_DEPLOYMENT_ORDER.md](docs/08_AWS_DEPLOYMENT_ORDER.md); the Phase 10 publication and
promotion are complete and their raw receipts remain only in encrypted evidence storage.

AWS deployment governance supports a protected team contract and a disclosed solo portfolio
contract. The latter is not separation of duties and requires a Public repository before Actions.
The sanitized repository is Public with the exact solo `main` ruleset, three contract environments,
custom OIDC subjects, least-privilege AWS roles, and required Actions checks. Retained CloudTrail,
bootstrap, artifact publication, live deployment, and disposable-demo teardown all completed under
their separate Phase 10 boundaries; the retained USD 10 Budget remains active. See
[docs/DEPLOYMENT_GOVERNANCE.md](docs/DEPLOYMENT_GOVERNANCE.md),
[docs/AWS_ACCOUNT_PREREQUISITES.md](docs/AWS_ACCOUNT_PREREQUISITES.md), and
[docs/PUBLIC_RELEASE_CHECKLIST.md](docs/PUBLIC_RELEASE_CHECKLIST.md).

## Local configuration

Copy `.env.example` to `.env` only when local, non-secret overrides are needed. Defaults load without
AWS credentials or network access. Request bodies are capped at 16 KiB, request admission at 64,
model inference workers at one, concurrency waiting at one second, the event-write operation at 750
ms, and graceful shutdown at ten seconds. `make api` also applies Uvicorn connection concurrency,
keep-alive, and graceful-shutdown bounds. Local event persistence is enabled by default. Firehose
uses explicit 100 ms connect and 200 ms read bounds, two total producer attempts, and a 25 ms base
retry delay inside that event-write boundary. The locked Phase 05 monitoring minimum is
`MIN_MONITORING_SAMPLES=500`; small windows are classified as insufficient data rather
than healthy. Dashboard JSON/HTML reads are size-bounded; S3 reads use short client timeouts and
private report links expire after five minutes by default.

## Repository layout

```text
src/modelguard/       training, inference, API, monitoring, dashboard, and telemetry packages
tests/                unit, contract, integration/load/monitoring, and smoke test roots
contracts/            portable versioned JSON Schemas
scripts/              bootstrap, validation, and safety helpers
prompts/              phase implementation contracts
checklists/           phase completion gates
reports/              phase evidence reports
artifacts/            ignored generated datasets, evidence, and immutable local bundles
configs/              committed versioned training and monitoring behavior
infrastructure/       guarded bootstrap, reusable modules, disposable demo, and retained audit design
mlruns/               ignored local MLflow file store created by Phase 02
```

## Security and limitations

This is a synthetic, temporary, production-style demo—not a production service. Calibrated scores
are meaningful only for the generator distribution, and the `10 × FN + FP` threshold is a synthetic
policy rather than a real economic optimum. Do not commit
credentials, `.env` files, Terraform variables/state/plans, generated model artifacts, or real
payment data. See [docs/03_SECURITY_BASELINE.md](docs/03_SECURITY_BASELINE.md) for the broader
security contract.

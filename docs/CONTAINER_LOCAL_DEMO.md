# Containerized Local Demo Contract

## Scope

Phase 07 packages the API, dashboard, and one-shot monitor as separate Python 3.12 images and runs
the complete synthetic workflow through Docker Compose. It creates no AWS client dependency in the
local path, needs no AWS credentials, does not mount the Docker socket, and adds no Kubernetes
resources.

The API and dashboard are long-running services. The monitor is deliberately a one-shot service with
default scale zero and is invoked with `docker compose run`; `docker compose build` still builds all
three images, while `docker compose up -d` starts only the two services that should remain alive.

## Clean-clone sequence

Requirements are Git, Make, uv 0.12.x, Python 3.12, Docker Engine, Docker Compose 2 or newer, and
curl. Run `make security-tools-bootstrap` once to install the checksum-verified Trivy and ShellCheck
binaries under the ignored repository cache. Global scanner packages are neither used nor accepted
as release evidence.

```bash
git clone <repository-url> modelguard-ai-launch-kit
cd modelguard-ai-launch-kit
./scripts/verify_environment.sh
make setup
make security-tools-bootstrap
make train

./scripts/build_local_images.sh
docker compose up -d
./scripts/smoke_local.sh
./scripts/demo_local.sh
./scripts/e2e_local.sh
./scripts/scan_local_images.sh
docker compose down -v
make verify
```

`make train` is required only when the immutable `artifacts/model-bundles/1.0.0/` bundle does not
already exist. It intentionally refuses to overwrite an existing model version. None of the commands
above reads an AWS profile or requires an AWS environment variable.

The build wrapper labels every image with the current Git revision (plus `-dirty` when appropriate)
and the exact SHA-256 of `uv.lock`. A direct `docker compose build` remains supported; it uses the
truthful `local-uncommitted` source label and the checked-in lock digest default. The wrapper is the
preferred evidence path because it resolves the actual worktree identity at build time.

## Image construction and runtime boundary

- All build and runtime stages use the official `python:3.12.13-alpine3.23` multi-platform index
  pinned by digest. A tag remains beside the digest for human auditability; the digest controls the
  bytes.
- uv is pinned to `0.12.1` in build stages. Runtime dependencies come from separate lock-backed
  `docker-api`, `docker-dashboard`, and `docker-monitor` groups. Developer tools and MLflow training
  dependencies are not installed into any final image. Streamlit transitively requires some
  data/runtime packages in the dashboard image.
- The locked scikit-learn release has no musllinux wheel, so the discarded Alpine dependency stage
  builds it from the verified sdist using `build-base`, GFortran, and Linux headers. Final stages
  retain only the required `libgomp` and `libstdc++` runtime libraries; compilers, uv, build caches,
  and package-build tools stay out. Source code and the role-specific virtual environment are copied
  into the runtime stage.
- The image declares and Compose repeats numeric user/group `10001:10001`. Root filesystems are
  read-only, all Linux capabilities are dropped, and every setuid/setgid executable is stripped
  before the final non-root user is selected. Only a bounded no-execute `/tmp` plus the named
  synthetic runtime volume are writable.
- The API health check calls `/health/ready`; the dashboard health check calls
  `/_stcore/health`; the one-shot monitor image checks that its CLI imports while its effective UID
  remains non-root.
- The seven model-bundle files are mounted read-only and individually. This preserves the bundle's
  secure host-directory mode while allowing the fixed container user to read only the named files.
  Missing bind sources are rejected instead of being silently created. Only the Phase 07 monitoring
  configuration file is mounted read-only where needed.
- `.dockerignore` allowlists only the lock/project metadata, application source, and Streamlit
  configuration needed by these builds. `.git`, `.env`, generated artifacts/reports, MLflow data,
  tests, infrastructure, caches, and credential-like file types never enter the builder context.
  Model bundles, prediction events, credentials, `.env`, and generated reports are never part of an
  image layer.

## Repeatable evidence namespaces

Each script generates and validates a lowercase `DEMO_RUN_ID` and uses a separate event-set name.
The services write under a shared named volume:

```text
/runtime/<run-id>/events/<event-set>/
/runtime/<run-id>/reports/
```

This makes reruns independent without deleting previous evidence. A graceful API restart closes the
active `*.jsonl.open` file into the immutable `*.jsonl` name before the monitor freezes its input.
The Phase 07 monitoring policy uses zero local finalization grace so an actual just-finished local
window can be demonstrated without waiting ten minutes. It retains the 500-event minimum and does
not introduce any row-level delivery-lateness claim; Phase 05's production-style ten-minute policy
remains unchanged.

Host-side machine-readable evidence is written under the ignored
`artifacts/phase-07-evidence/<run-id>/` root. Each summary contains a schema version, pass/fail state,
scenario states, exact accepted count, report identity, and/or hashes of the underlying evidence.
The scripts return nonzero if their evidence validator finds a mismatch.

## Scenario matrix

| Scenario | Command | Required proof |
| --- | --- | --- |
| Healthy traffic | `./scripts/smoke_local.sh` | API live/ready, prediction, local-persisted metric, closed events, `valid/healthy`, JSON/HTML report publication, dashboard health, image user/health/provenance, and no baked artifacts |
| Healthy to drifted | `./scripts/demo_local.sh` | 1,000 deterministic baseline requests produce `healthy`; an isolated 1,000-request shifted stream produces `degraded`; report IDs differ and the dashboard remains available |
| Insufficient data | `./scripts/e2e_local.sh` | 25 valid target events produce `insufficient_data` and drift `unknown` |
| Corrupt bundle | `./scripts/e2e_local.sh` | Process remains live, readiness and prediction return 503, and no model identity is served |
| Sink outage | `./scripts/e2e_local.sh` | An unwritable local sink increments `local_failed`/`event_sink` metrics while prediction still returns 200 |

The baseline and drifted request generator is `scripts/generate_local_traffic.py`. It accepts only a
loopback HTTP origin, uses deterministic seeds, validates every v1 response, writes aggregate JSON
evidence, and returns nonzero on any HTTP or contract failure. It never sends real payment data.

## Trivy gate and exception process

Verify the pinned local scanner before an image release:

```bash
make security-tools-check
```

The release gate is stricter and machine-readable:

```bash
./scripts/scan_local_images.sh
```

It resolves each local tag to its exact `sha256:` image ID and passes only that immutable identity to
the shared repository scanner. Every HIGH or CRITICAL vulnerability fails. CycloneDX evidence and
sanitized SARIF are generated under an ignored evidence directory; downloaded databases, scanner
caches, and generated reports are never committed. The image exception registry remains
`configs/trivy-exceptions.json` and is empty; any future entry must pass the same owned, justified,
expiring policy as all other scanner suppressions.

Remediate in this order:

1. Confirm the finding against the current Trivy database and identify whether it is an OS or Python
   package.
2. Upgrade the locked application dependency or refresh the pinned official base-image digest,
   rebuild all affected images once, and rerun the full smoke/demo and scan gates.
3. If no fixed artifact exists and the local synthetic exposure is acceptably bounded, add a
   temporary exact exception only after human review and rerun `make security-scan` plus the exact
   image scans.

Every exception must match the exact image, vulnerability ID, and package name and must include a
substantive rationale, accountable owner, and ISO `expires_on` date. The evaluator rejects duplicate,
expired, stale/unmatched, malformed, or longer-than-90-day exceptions. Expiry is a removal/review
deadline, not proof that a vulnerability is safe. Reviewers should record compensating controls and
prefer shortening exposure over renewing an exception.

Example shape (illustrative only; do not add it unless a real current finding requires it):

```json
{
  "image": "modelguard-api:local",
  "vulnerability_id": "CVE-YYYY-NNNN",
  "package_name": "affected-package",
  "rationale": "No fixed release exists; the service is loopback-only for this temporary demo.",
  "owner": "repository-maintainer",
  "expires_on": "YYYY-MM-DD"
}
```

Trivy results are time-bound evidence because both its database and upstream package status change.
Commit the policy and rationale, not generated scan databases or large scan artifacts.

## Troubleshooting and cleanup

Inspect the current services and bounded logs with:

```bash
docker compose ps
docker compose logs --tail=100 api dashboard
```

If a port is occupied, set `MODELGUARD_API_PORT` and/or `MODELGUARD_DASHBOARD_PORT` before bringing
the services up. The scripts use the same variables. The two failure-mode ports default to `18081`
and `18082` and can be changed with `E2E_CORRUPT_PORT` and `E2E_SINK_PORT`.

Normal cleanup is scoped to the Compose project and its synthetic named volume:

```bash
docker compose down -v
```

Do not mount `/var/run/docker.sock`, run an application container as root, or put credentials/model
artifacts into a Docker build context to work around a local permission issue.

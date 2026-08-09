# Troubleshooting

## Codex cannot see the project files

```bash
pwd
git rev-parse --show-toplevel
codex doctor --summary
```

Start Codex from the repository root.

## Codex changed files outside the current phase

```bash
git diff --name-only
```

Ask it to revert out-of-scope changes, or restore them manually before continuing. Do not advance to
the next phase.

## uv or dependency problems

```bash
uv --version
uv sync --all-groups --locked
uv run python -V
uv run pytest -q
```

## Docker permission denied

```bash
sudo usermod -aG docker "$USER"
newgrp docker
docker run --rm hello-world
```

Do not work around this by mounting the Docker socket into a project container or running an
application service as root. After group membership changes, start a fresh login shell. Verify both
`docker info` and `docker compose version` before running the Phase 07 scripts.

## Docker Compose service is unhealthy

```bash
docker compose ps
docker compose logs --tail=100 api dashboard
```

API liveness with failed readiness normally means the generated seven-file bundle is missing or did
not verify. Run `make verify-model`, then rebuild/recreate the service. The bundle is mounted rather
than baked into an image. Dashboard health is `/_stcore/health`; report absence is displayed as
unavailable evidence and is not itself a process-health failure.

## Local demo report has the wrong scenario state

Do not reuse a hand-written event directory. `smoke_local.sh`, `demo_local.sh`, and `e2e_local.sh`
create unique named-volume namespaces and validate exact counts. Keep the default minimum counts;
lowering drift thresholds or the monitoring minimum to force a pass invalidates the evidence.

## Trivy HIGH or CRITICAL finding

Run `./scripts/scan_local_images.sh`, inspect its CycloneDX and sanitized SARIF evidence, and follow
the remediation order in
`docs/CONTAINER_LOCAL_DEMO.md`. Upgrade a locked dependency or pinned base digest first. Temporary
exceptions require an exact finding/package/image match, rationale, owner, and expiry of at most 90
days; expired, stale, or unmatched exceptions fail the evaluator.

## Port already in use

```bash
sudo ss -ltnp | grep -E ':8000|:8501|:18081|:18082|:5000'
```

Override local Compose ports with `MODELGUARD_API_PORT` and `MODELGUARD_DASHBOARD_PORT`; override
failure-scenario ports with `E2E_CORRUPT_PORT` and `E2E_SINK_PORT`.

## Incorrect AWS identity

```bash
aws sts get-caller-identity
aws configure list
```

Never ask an agent to create access keys. Use the approved browser-based AWS login profile, and use GitHub
OIDC in CI.

## Terraform state or backend problems

Run bootstrap first, followed by backend initialization. Do not delete state or change the bucket
manually while resources still exist.

## Unstable drift test

- Fix the random seed.
- Use a sufficiently large sample.
- Test threshold behavior with clear constructed vectors instead of weak random differences.
- Do not lower thresholds merely to make the test pass.

## API is running but readiness fails

Review:

- Model bundle path and version.
- Checksums.
- Schema version.
- Active model pointer.
- S3 and SSM permissions in AWS mode.

## Ultra consumed too much context or expanded scope

Stop the session, retain the report only, then implement repairs in small XHigh or Max batches. Do
not grant Ultra unrestricted permission to modify the entire project.

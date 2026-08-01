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

## Port already in use

```bash
sudo ss -ltnp | grep -E ':8000|:8501|:5000'
```

## Incorrect AWS identity

```bash
aws sts get-caller-identity
aws configure list
```

Never ask an agent to create access keys. Use AWS SSO or a local short-lived profile, and use GitHub
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

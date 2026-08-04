#!/usr/bin/env bash
set -euo pipefail

cat <<'EOF'
ModelGuard AI does not automate Ubuntu tool installation.

The former convenience installer downloaded and executed changing remote artifacts without
repository-pinned versions and checksums. This script is now intentionally manual-only and makes
no system, package-manager, repository, group-membership, or network changes.

For Phase 01, install these prerequisites through a trusted, reviewed channel:

  1. Git
  2. Make
  3. uv 0.12.x

Then run:

  ./scripts/verify_environment.sh
  uv sync --all-groups --locked
  make verify

uv will select Python 3.12 from the committed .python-version and lock contract. Docker, AWS CLI,
Terraform, and Codex remain later-phase/manual prerequisites. Phase 09.1 installs actionlint,
ShellCheck, Trivy, and Gitleaks from checksum-verified release archives and Checkov from one exact
OCI digest under the ignored repository-local cache. After Docker is available, run
`make security-tools-bootstrap`; do not install those scanners globally.

No changes were made.
EOF

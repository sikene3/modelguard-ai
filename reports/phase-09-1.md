# Phase 09.1 report — Reproducible security release gates

## Outcome

**GO for the Phase 09.1 repository commit.** The five required scanners are installed in an ignored
repository-local cache from one exact lock, invoked through the same fail-closed repository scripts
locally and in GitHub Actions, and verified by real local scans. No Phase 10 implementation, live
GitHub operation, AWS access, image publication, or Terraform mutation occurred.

The requested baseline identifier was not an object in this repository. The clean Phase 09 tree is
represented after the authorized pre-publication rewrite by
`165bbacadad5860aa995549ae79298c3f72a70f5` with the requested message. The one-character baseline
discrepancy was treated as a transcription error at the time. The later, separately authorized
rewrite changed publication metadata and removed obsolete language-specific history; it did not
alter the canonical Phase 09 implementation.

## Read-first audit

| Scanner | Initial classification | Deficiency repaired |
| --- | --- | --- |
| actionlint | Partially enforced | CI-only source install replaced by one checksum-pinned local/CI binary and shared all-workflow command |
| ShellCheck | Partially enforced | optional host check replaced by a required pinned binary for all shell files and embedded workflow Bash |
| Checkov | Partially enforced | Terraform-only `uvx` path replaced by exact-digest OCI scanning for Terraform, Dockerfiles, and workflows |
| Trivy | Partially enforced | image-only/critical-only paths expanded to filesystem, configuration, and exact-image HIGH/CRITICAL gates |
| Gitleaks | Partially enforced | separate CI history container replaced by shared complete-history plus current-worktree scanning |

No scanner was absent, and no existing gate was duplicated. The partial paths were consolidated or
replaced by the shared implementation.

## Delivered controls

- `security/security-tools.lock.json` is the single strict source for scanner versions, release
  archive checksums, the Checkov Linux/amd64 OCI digest, and every third-party GitHub Action SHA plus
  release version.
- `scripts/security_tools.py` validates the lock, downloads only exact HTTPS release artifacts,
  verifies archive and extracted-member hashes, verifies the Checkov digest, and installs/caches only
  under ignored `.cache/security-tools/`. Missing, altered, floating, or mismatched tools fail.
- `scripts/security_scan.sh` owns each real invocation. `scripts/security_gate_runner.py` runs all
  five scanner groups, preserves every exit code, and returns failure if any group is missing or
  nonzero. Local and GitHub commands are identical.
- actionlint checks all five workflows and delegates embedded `run:` blocks to the same exact
  ShellCheck binary. The shell gate checks 20 approved `.sh` files with both `bash -n` and ShellCheck.
- Checkov runs with no network, a read-only repository mount/root filesystem, dropped capabilities,
  non-root UID/GID, and a bounded no-execute tmpfs. Its exact image is saved only to the ignored cache.
- Gitleaks scans nine commits with `--all`, 100% value redaction, and no inline allow comments, then
  scans the approved current working tree separately. Raw results are deleted after policy and SARIF
  conversion.
- Trivy scans repository dependencies/secrets and IaC configuration, failing on HIGH/CRITICAL. Image
  workflows resolve and scan exact content-addressed image IDs before any AWS identity or push. The
  protected publisher verifies and loads only that same scanned image archive; it never rebuilds.
- `scripts/sanitize_sarif.py` retains only scanner/rule/severity, safe path/line, and value-free
  suppression state. The pinned CodeQL action receives only this sanitized directory.
- Security scan jobs have only `contents: read` and `security-events: write`. They have no secrets,
  protected environment, `id-token: write`, AWS credential action, Terraform apply, ECR command, or
  deploy capability.
- Make exposes the required `security-tools-bootstrap`, `security-tools-check`, `security-scan`, and
  `release-gates` targets. Global scanner installations are not accepted as evidence.

## Exact installed tool identities

| Tool | Version | Approved source identity |
| --- | --- | --- |
| actionlint | 1.7.9 | archive SHA-256 `233b280d05e100837f4af1433c7b40a5dcb306e3aa68fb4f17f8a7f45a7df7b4` |
| ShellCheck | 0.11.0 | archive SHA-256 `8c3be12b05d5c177a04c29e3c78ce89ac86f1595681cab149b65b97c4e227198` |
| Checkov | 3.3.9 | OCI digest `sha256:3617c42277657f23ed75a554f10bce3a46867251c1c0ea2e5a1df3bad24e336f` |
| Trivy | 0.70.0 | archive SHA-256 `8b4376d5d6befe5c24d503f10ff136d9e0c49f9127a4279fd110b727929a5aa9` |
| Gitleaks | 8.30.1 | archive SHA-256 `551f6fc83ea457d62a0d98237cbad105af8d557003051f41f3e7ca7b3f2470eb` |

The local Trivy database used for this evidence reports `UpdatedAt=2026-08-04T07:37:45.669465823Z`.
Database bytes and metadata remain ignored, because vulnerability evidence is time-bound and must be
refreshed for each release.

## Real scanner results

```text
make security-tools-bootstrap
make security-tools-check
PASS — all five exact versions and cached artifact identities verified.

make security-scan
PASS — actionlint=0, ShellCheck=0, Checkov=0, Gitleaks=0, Trivy repository=0.

Checkov 3.3.9
PASS — Terraform: 435 passed, 0 failed, 54 skipped.
PASS — Dockerfiles: 317 passed, 0 failed, 3 skipped.
PASS — GitHub Actions: 686 passed, 0 failed, 2 skipped.

Gitleaks 8.30.1
PASS — nine commits/~2.04 MB scanned; one exact historical false positive accepted by policy.
PASS — approved current worktree/~1.99 MB scanned; zero findings.

Trivy 0.70.0
PASS — filesystem vulnerability/secret scan: zero blocking findings.
PASS — configuration scan: zero unaccepted blocking findings.
PASS — API image sha256:b123600ea5670ac4bdc608a19ed88c091d965ee7d1fdddd3919b70a7fb580886:
       zero HIGH/CRITICAL vulnerabilities.
PASS — dashboard image sha256:ca7567770e95af5f1043e2acd86788703b2d1a4d2e19d3797b97d31e6da3578b:
       zero HIGH/CRITICAL vulnerabilities.
PASS — monitor image sha256:94bbcbdc0069fe261bcaf2aa3bf78146a8ec9f72171770a49d71ba38a88fde3b:
       zero HIGH/CRITICAL vulnerabilities.
```

These three images were the existing verified local images; no image was rebuilt and no new image or
vulnerability database artifact is committed.

## Suppressions reviewed

| Scanner | Count | Exact approved scope |
| --- | ---: | --- |
| Checkov | 50 directives / 59 result instances | 54 Terraform resources, 3 digest-ARG Dockerfiles, and 2 strictly validated protected dispatches |
| ShellCheck | 6 | literal jq/JMESPath programs with explicitly bound values |
| Trivy repository configuration | 3 | exact ALB restricted-CIDR/HTTP-fallback and teardown-safe SSE-S3 findings |
| Trivy image vulnerabilities | 0 | the image exception registry remains empty |
| Gitleaks | 1 | exact historical Makefile fingerprint/path/rule/commit false positive |
| Bandit release-gate helpers | 6 | fixed no-shell command arrays and checksum-verified exact HTTPS download boundary |

Every record contains its finding ID, substantive justification, owner `modelguard-maintainers`, and
expiry `2026-10-31`; the policy refuses expired or more-than-90-day records. The Trivy repository
records are path-scoped, and no blanket scanner suppression or command-line skip exists.

## Tests and full validation

```text
uv run --frozen --no-sync pytest --no-cov -q \
  tests/unit/test_phase091_release_gates.py tests/unit/test_phase09_cicd.py
PASS — 57 passed.

uv run --frozen --no-sync pytest --no-cov -q \
  tests/unit/test_phase08_terraform.py tests/unit/test_phase09_cicd.py \
  tests/unit/test_phase091_release_gates.py
PASS — 74 passed.

uv run --frozen --no-sync pytest --no-cov -q \
  tests/integration/test_training_workflow_phase02.py
PASS — 4 passed; MLflow tracking regression remains green.

make verify
PASS — Ruff format/lint; strict Mypy over 64 source files; 273 tests; 84.72% branch coverage;
Bandit; strict hashed pip-audit with no known vulnerabilities; basic secret/file check; trusted model
bundle verification.

terraform fmt -check -recursive infrastructure
PASS.

uvx --from yamllint==1.37.1 yamllint .github/workflows
PASS — no warnings or errors.

./scripts/security_scan.sh actionlint
./scripts/security_scan.sh shellcheck
PASS — all workflows, embedded Bash, and 20 shell files.

git diff --check
PASS.

make release-gates
PASS — the complete `make verify` result and all five repository scanner groups passed again after
the report and 288-path manifest were finalized.

Sorted manifest parity; English/Arabic-character; disposable-file; secret/file; bearer-token
argument; Phase 10 scope; workflow parsing; Bash syntax; and diff scans
PASS — no mismatch, Arabic content/name, unapproved output, credential, token-in-argv pattern,
future-phase implementation, malformed workflow/shell, or whitespace error was found.
```

The approved Phase 09.1 set contains 49 paths: 38 modified and 11 new. `FILE_MANIFEST.txt` is sorted
and exactly matches all 288 approved project paths while intentionally excluding itself.

## Generated evidence boundary

- `.cache/security-tools/`: downloaded archives/binaries, exact Checkov OCI tar, install state, Trivy
  database/cache, and ephemeral raw scanner files; ignored and not committed.
- `artifacts/security/sarif/`: sanitized local SARIF; ignored and not committed.
- `artifacts/security/image-release-phase-09-1/`: local CycloneDX image evidence; ignored and not
  committed.
- Security-scanning jobs upload only sanitized SARIF and the already documented non-secret
  build/image evidence. They never upload raw secret results, caches, databases, environment dumps,
  Terraform state/plans, credentials, or sensitive logs. The separate protected saved-plan transfer
  remains the non-scanner Phase 09 deployment boundary documented in `docs/CICD_SECURITY.md`.

## Residual external gates

No GitHub workflow was dispatched. GitHub expression evaluation, Code Scanning ingestion,
protected-environment approval, same-run artifact transfer, and OIDC token issuance remain mandatory
live release evidence. No AWS command, registry publication, Terraform provider-backed validation,
plan/apply, or deployment ran during Phase 09.1. Phase 10 remains unstarted.

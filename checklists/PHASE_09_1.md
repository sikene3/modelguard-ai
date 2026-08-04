# Phase 09.1 Checklist — Reproducible Security Release Gates

- [x] Existing actionlint, ShellCheck, Checkov, Trivy, and Gitleaks enforcement audited before edits
- [x] One strict lock records every scanner version and archive SHA-256 or OCI digest
- [x] Floating versions, mutable action references, mutable container tags, and missing digests rejected
- [x] Scanner bootstrap writes only to ignored repository-local `.cache/security-tools/`
- [x] Downloaded binaries, OCI archives, vulnerability databases, caches, and reports remain ignored
- [x] `security-tools-bootstrap`, `security-tools-check`, `security-scan`, and `release-gates` Make targets
- [x] Local and GitHub execution call the same repository-owned scanner script and configuration
- [x] actionlint checks every workflow and invokes exact ShellCheck for embedded workflow Bash
- [x] ShellCheck checks every approved shell file and refuses a missing or mismatched binary
- [x] Checkov checks Terraform, Dockerfiles, and GitHub Actions through one exact OCI digest
- [x] Gitleaks checks complete history and an approved current-worktree snapshot with 100% redaction
- [x] Trivy checks repository vulnerabilities/secrets, configuration, and exact image IDs
- [x] Every HIGH or CRITICAL Trivy result is blocking
- [x] Every suppression is exact, justified, owned, expiring, and version controlled
- [x] Missing tools and scanner nonzero exits propagate to a failed aggregate gate
- [x] Security jobs have no AWS credentials, OIDC permission, protected environment, or deploy command
- [x] Every third-party action has a full SHA and adjacent human-readable release comment
- [x] Supported scanner output is sanitized before pinned Code Scanning upload
- [x] Regression tests cover scanner invocation, tool absence, nonzero exits, mutable pins, permissions,
      exact build image identity, suppression policy, and SARIF redaction
- [x] Full local verification, focused regressions, Terraform formatting, YAML/Bash parsing, manifest,
      language, disposable-file, secret, bearer-argument, and diff checks pass
- [x] All five scanners and all three existing exact local images were scanned for real
- [x] No GitHub workflow, GitHub/AWS API, image publication, Terraform apply, or Phase 10 work ran

## Evidence

- Detailed commands, counts, tool identities, suppressions, and residual live gates:
  `reports/phase-09-1.md`.
- Full project gate: 273 tests passed with 84.72% branch coverage; Ruff, strict Mypy, Bandit, hashed
  pip-audit, the basic secret/file check, and trusted bundle verification passed.
- Focused contracts: 57 Phase 09/09.1 tests and 74 combined Phase 08/09/09.1 tests passed; the Phase 02
  MLflow regression remained 4/4 green.
- Scanner aggregate: actionlint, ShellCheck, Checkov, Gitleaks, and Trivy all returned zero after
  policy evaluation. Checkov reported 435 Terraform, 317 Dockerfile, and 686 GitHub Actions passes,
  with zero failures and 54/3/2 reviewed skips respectively.
- Trivy exact-image result: zero HIGH or CRITICAL vulnerabilities in each existing API, dashboard,
  and monitor image ID. Generated CycloneDX/SARIF and scanner caches remain ignored.
- Live GitHub expression, Code Scanning upload, protected-environment, OIDC, artifact-transfer, and AWS
  behavior remain mandatory external release gates and are not claimed as locally executed.

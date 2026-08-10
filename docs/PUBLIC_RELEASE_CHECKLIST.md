# Controlled publication record and remaining activation checklist

The sanitized baseline completed this checklist and the checksum-verified Publication Audit before
its single authorized initial push and Public conversion. The repository is now Public with Actions
disabled. This record does not authorize another visibility mutation, direct `main` push, Actions
enablement, release, package publication, Code Scanning change, OIDC change, or AWS mutation. Any
later Phase 10 corrective branch must pass its applicable release and privacy gates before a
ruleset-governed pull request.

Completed for the exact published baseline immediately before Public conversion:

- [x] Disable GitHub Actions and read the setting back as disabled.
- [x] Confirm the exact owner/repository and intended source commit.
- [x] Audit every tracked, ignored, and untracked path; review symlinks and unusual filenames.
- [x] Scan complete Git history across every commit and ref with the pinned Gitleaks policy.
- [x] Run `make release-gates`, including actionlint, ShellCheck, Checkov, Gitleaks, Trivy filesystem
      and configuration scans, Ruff, strict Mypy, Bandit, hashed pip-audit, tests, and trusted bundle
      verification.
- [x] Confirm no credentials, tokens, account emails, personal data, `.env` files, Terraform state or
      plans, `.terraform` directories, credential/config stores, databases, SARIF, scanner caches,
      vulnerability databases, downloaded binaries, virtual environments, logs, generated evidence,
      model artifacts, container archives, or temporary files are tracked or untracked.
- [x] Audit every generated-artifact and large-file candidate; verify the Git object database has no
      unexpected large or sensitive blob.
- [x] Regenerate `FILE_MANIFEST.txt` through the prescribed manifest workflow and prove exact parity.
- [x] Run the repository-wide Arabic-character and bearer-token argument scans.
- [x] Inspect every workflow trigger, permission, action SHA, artifact, cache, environment, secret,
      variable, OIDC claim, shell expansion, and deployment guard.
- [x] Confirm the Public repository exposes no sensitive issue, release, package, branch, tag,
      environment, variable, secret metadata, or historical content.

Completed for the separately authorized conversion itself:

- [x] Reconfirm Actions is disabled immediately before changing visibility.
- [x] Change only visibility; make no simultaneous OIDC, environment, secret, variable, workflow, or
      branch/ruleset change.
- [x] Read visibility back as Public and read Actions back as disabled.
- [x] Verify anonymous Public reachability and the absence of sensitive material through the sealed
      audit's unauthenticated read-only checks.
- [x] Repeat complete history/worktree secret scans and manifest parity against the exact public
      commit.
- [ ] Keep Actions disabled until the exact OIDC/IAM trust, governance mode, environments,
      protections, variables, release gates, cost prerequisites, and rollback plan receive separate
      approval.

If any scan fails, an unexpected object appears, or sensitive material ever entered Git history,
stop. Do not rely on deleting the current file alone; rotate any affected credential and use a
separately reviewed history-remediation/publication plan.

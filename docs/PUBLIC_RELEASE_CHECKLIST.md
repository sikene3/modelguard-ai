# Controlled future-publication checklist

The repository remains Private. This checklist does not authorize a visibility change, remote
addition, push, Actions enablement, release, package publication, Code Scanning change, or GitHub API
mutation.

Immediately before a separately approved Public conversion:

- [ ] Disable GitHub Actions and read the setting back as disabled.
- [ ] Confirm the exact owner/repository and intended source commit.
- [ ] Audit every tracked, ignored, and untracked path; review symlinks and unusual filenames.
- [ ] Scan complete Git history across every commit and ref with the pinned Gitleaks policy.
- [ ] Run `make release-gates`, including actionlint, ShellCheck, Checkov, Gitleaks, Trivy filesystem
      and configuration scans, Ruff, strict Mypy, Bandit, hashed pip-audit, tests, and trusted bundle
      verification.
- [ ] Confirm no credentials, tokens, account emails, personal data, `.env` files, Terraform state or
      plans, `.terraform` directories, credential/config stores, databases, SARIF, scanner caches,
      vulnerability databases, downloaded binaries, virtual environments, logs, generated evidence,
      model artifacts, container archives, or temporary files are tracked or untracked.
- [ ] Audit every generated-artifact and large-file candidate; verify the Git object database has no
      unexpected large or sensitive blob.
- [ ] Regenerate `FILE_MANIFEST.txt` through the prescribed manifest workflow and prove exact parity.
- [ ] Run the repository-wide Arabic-character and bearer-token argument scans.
- [ ] Inspect every workflow trigger, permission, action SHA, artifact, cache, environment, secret,
      variable, OIDC claim, shell expansion, and deployment guard.
- [ ] Confirm the Public repository exposes no sensitive issue, release, package, branch, tag,
      environment, variable, secret metadata, or historical content.

For the separately authorized conversion itself:

- [ ] Reconfirm Actions is disabled immediately before changing visibility.
- [ ] Change only visibility; make no simultaneous OIDC, environment, secret, variable, workflow, or
      branch/ruleset change.
- [ ] Read visibility back as Public and read Actions back as disabled.
- [ ] Inspect the public web view manually while signed out; verify no sensitive material is visible.
- [ ] Repeat complete history/worktree secret scans and manifest parity against the exact public
      commit.
- [ ] Keep Actions disabled until the exact OIDC/IAM trust, governance mode, environments,
      protections, variables, release gates, cost prerequisites, and rollback plan receive separate
      approval.

If any scan fails, an unexpected object appears, or sensitive material ever entered Git history,
stop. Do not rely on deleting the current file alone; rotate any affected credential and use a
separately reviewed history-remediation/publication plan.

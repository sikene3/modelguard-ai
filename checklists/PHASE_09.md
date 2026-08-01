# Phase 09 Checklist

- [ ] CI workflow
- [ ] Container scan workflow
- [ ] Terraform plan workflow
- [ ] Image publish workflow
- [ ] Protected deploy workflow
- [ ] OIDC only
- [ ] Immutable tags
- [ ] Actions/base images pinned; build once and promote exact digest
- [ ] Each image is built/scanned once and deployed as `repository@sha256`
- [ ] Protected environment and deployment concurrency
- [ ] Durable last-known-good task/model rollback targets
- [ ] Post-deploy smoke
- [ ] No PR auto-apply
- [ ] Exact alternative OIDC subjects; untrusted jobs have no id-token/AWS/state access
- [ ] Pinned history secret scan with redacted output and expiring scoped allowlist
- [ ] Raw plan restricted to same-identity transfer; redacted summary is public evidence
- [ ] Protected prerequisite and activation plans enforce the startup barrier

## Evidence

- Commands:
- Test results:
- Artifact paths:
- Commit:
- Residual risks:

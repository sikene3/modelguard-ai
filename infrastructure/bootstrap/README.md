# Human/SSO bootstrap boundary

This root is deliberately separate from `environments/demo`. A human operator using short-lived AWS
SSO credentials reviews and applies it. It owns the KMS-encrypted, versioned, public-blocked,
TLS-only S3 state bucket; native S3 lockfile permissions; the GitHub OIDC provider; customized exact-
subject CI plan/deploy roles binding repository identity, ref, environment, workflow, and audience;
scoped retained CI read/compute/data/operations policies and attachments; and the mandatory workload
permission boundary. The retained customer-managed key also encrypts the exact alert topic under
SNS-topic encryption-context restrictions so AWS Budgets can publish without a second lingering key.

The bootstrap state remains local (and Git-ignored) unless the operator already has an independent
administrative backend. Preserve it in an approved encrypted location. Never import these resources
into disposable demo state. `prevent_destroy` guards the retained trust/state resources.

Validation does not need credentials:

```bash
terraform -chdir=infrastructure/bootstrap init -backend=false
terraform -chdir=infrastructure/bootstrap validate
```

Phase 08 does not authorize plan/apply. In Phase 10, copy the example to a Git-ignored `.tfvars`,
verify the exact account and Region, use SSO, save/review a bootstrap plan, and apply it manually.
First confirm a retained account/organization CloudTrail trail captures S3 data events for the exact
state-bucket ARN. The demo backend uses `use_lockfile=true`; no DynamoDB lock table is needed.

The tfvars also require exact GitHub owner/repository names, numeric immutable IDs, subject-format
flag, main ref, protected environments, and workflow paths. Apply these matching IAM conditions
before activating `.github/oidc-subject-template.json` in GitHub. Default-subject tokens fail during
that safe transition; never activate the GitHub template first.

Final cleanup is a distinct operation after the demo state has been destroyed and archived. It
requires removing `prevent_destroy` in a separately reviewed change, emptying every version and
lockfile only after confirming no backend user remains, applying a saved bootstrap-destroy plan with
SSO, and recording the KMS key's 30-day pending-deletion state. Never run that cleanup from the demo
deploy role.

# Human bootstrap boundary

This root is deliberately separate from `environments/demo`. A human operator using temporary
browser-authenticated credentials reviews and applies it. It owns the KMS-encrypted, versioned, public-blocked,
TLS-only S3 state bucket; native S3 lockfile permissions; the GitHub OIDC provider; customized exact-
subject CI plan/deploy roles binding repository identity, ref, environment, workflow, and audience;
scoped retained CI read/compute/data/operations policies and attachments; and the mandatory workload
permission boundary. The retained customer-managed key also encrypts the exact drift/alarm topic
under exact SNS-topic encryption-context restrictions. Exact Budget and CloudWatch service
statements remain bounded, but the retained USD 10 budget is created manually and is not Terraform
owned.

The bootstrap state remains local (and Git-ignored) unless the operator already has an independent
administrative backend. Preserve it in an approved encrypted location. Never import these resources
into disposable demo state. `prevent_destroy` guards the retained trust/state resources.

Validation does not need credentials:

```bash
terraform -chdir=infrastructure/bootstrap init -backend=false
terraform -chdir=infrastructure/bootstrap validate
```

Phase 08 does not authorize plan/apply. In Phase 10, copy the example to a Git-ignored `.tfvars`, run
the local `python -m scripts.human_aws_login dependency` check, require the separately authenticated
`AWS_PROFILE=modelguard-bootstrap`, and run `python -m scripts.human_aws_login verify` for the exact
account and `us-east-1` before any human plan/apply helper. Root, environment, shared-file, static,
or unnamed default-chain credentials are forbidden. Use that temporary browser identity to
save/review a bootstrap plan,
and apply it manually. First separately review and apply `../audit-bootstrap` so its retained
CloudTrail trail captures data events for the two exact future state/lock objects; preserve that
root's local state through its encrypted offline procedure. The demo backend uses
`use_lockfile=true`; no DynamoDB lock table is needed.

The tfvars also require exact GitHub owner/repository names, numeric immutable IDs, subject-format
flag, main ref, protected environments, and workflow paths. Apply these matching IAM conditions
before activating `.github/oidc-subject-template.json` in GitHub. Default-subject tokens fail during
that safe transition; never activate the GitHub template first.

Final cleanup is a distinct operation after the demo state has been destroyed and archived. It
requires removing `prevent_destroy` in a separately reviewed change, emptying every version and
lockfile only after confirming no backend user remains, applying a saved bootstrap-destroy plan with
temporary browser authentication, and recording the KMS key's 30-day pending-deletion state. Never run that cleanup from the demo
deploy role.

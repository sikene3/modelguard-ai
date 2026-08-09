# Deployment governance modes

ModelGuard has two explicit governance modes. They share the same exact GitHub OIDC subject,
separate plan/deploy roles, permission boundary, immutable release identities, saved-plan checks,
bounded demo lifetime, and fail-closed behavior. Selecting a mode does not change an IAM subject or
broaden trust.

## Mode comparison

| Control | `team_protected` | `solo_portfolio` |
|---|---|---|
| Intended use | Team-controlled deployment | Personal portfolio demonstration only |
| Repository visibility | Private is supported | Must be Public before Actions or public Code Scanning is enabled |
| Human separation of duties | Real independent required reviewer | None; explicitly not production-grade separation of duties |
| Self-review | Prevented | Unavoidable and disclosed |
| Administrator bypass | Disabled | No claim that an owner is independently constrained |
| Privileged entry | Protected main and environments | Manual `workflow_dispatch` ancestry only |
| Required evidence | Source, images, plan, model, confirmation | Same evidence plus explicit solo disclosure and exact manual confirmations |
| Destroy | Separate protected confirmation | Separate phrase `DESTROY SOLO modelguard-ai demo` |

Automated tests, scanners, immutable hashes, and typed phrases reduce error and tampering risk. They
do not replace an independent reviewer.

## Common fail-closed contract

`scripts/deployment_governance.py` checks exact values and returns only a bounded pass/refusal JSON
record. It rejects a different repository, visibility, ref, environment, caller `workflow_ref`,
called `job_workflow_ref`, event, source revision, confirmation, image set, model-pointer hash, run
identity, plan hash, or plan-identity hash. Direct image publication requires both identities to be
`publish-images.yml`; the team reusable path requires caller `deploy-demo.yml` and called job
`publish-images.yml`, both at the same exact source revision.

Every trusted AWS subject is customized with ordered claims `repo`, `ref`, `environment`, and
`workflow_ref`; audience is exactly `sts.amazonaws.com`. Immutable-subject mode uses the exact
`owner@owner-id/repository@repository-id` identity. Terraform uses `StringEquals` with no wildcard.
The plan role trusts only `demo-plan` plus `terraform-plan.yml`; deploy/publish subjects use `demo`,
and destroy uses `demo-destroy`. The deploy role never trusts `demo-plan`.

AWS trust must be created and read back before the matching GitHub repository subject template is
activated. A committed template file is not activation. AWS-capable workflows must remain disabled
until the live template, owner ID, repository ID, environments, variables, and IAM output subjects
all match.

## `team_protected`

This is the stronger mode. Before deployment, configure protected `main`, exact environments, a real
trusted reviewer who is not the actor, prevention of self-review, and no administrator bypass.
Environment approvals protect plan/application boundaries. If no independent reviewer exists, this
mode is not deployable; a second account or fictitious reviewer must never be used.

## `solo_portfolio`

This mode honestly acknowledges that one person controls source, review, and deployment. It is not a
production approval model. Before it can be selected:

1. Complete `docs/PUBLIC_RELEASE_CHECKLIST.md` while Actions is disabled.
2. Change visibility to Public only in a separately authorized step, keep Actions disabled, and
   manually inspect the public repository.
3. Configure exact immutable OIDC owner/repository IDs and read back the live template and IAM trust.
4. Configure exact `demo-plan`, `demo`, and `demo-destroy` environments and non-secret variables.
5. Keep publish/deploy/activation/rollback/destroy rooted in manual dispatch. A push, pull request,
   fork, reusable-call-only entry, altered ref, or missing evidence must fail before AWS credentials.
6. Inspect the value-free redacted plan only after the raw plan has been sealed into the encrypted
   retained-backend transfer. Before approving the separate apply job, set the exact run identity,
   raw plan SHA-256, identity SHA-256, and mode-specific phrase. Activation additionally binds all
   three ECR `repository@sha256` values and the promoted model-pointer SHA-256. Plaintext plans,
   backend/tfvars, model/image metadata, and account identifiers are never Public artifacts.
7. Use the separate manual `rollback-demo.yml` and `destroy-demo.yml` workflows. Solo rollback is
   never triggered automatically, and destroy rejects a missing mode rather than falling back to
   team wording. The deployed Terraform state and immutable last-known-good record both persist the
   selected governance mode; apply, rollback, and destroy refuse a different mode even if a
   repository variable changes. Keep the bounded `AutoDestroyDate`; it is a guardrail, not an
   unattended delete.

The current repository is intentionally Private, empty remotely, Actions-disabled, has no remote,
and has not configured these external controls. Therefore the local mode contract is implemented and
tested, but solo deployment is not authorized or active by this code-only readiness work.

## Upgrade path

When a real trusted reviewer becomes available:

1. leave Actions disabled and stop all deployment activity;
2. configure the reviewer, prevent self-review, remove administrator bypass, and protect `main`;
3. change `DEPLOYMENT_GOVERNANCE_MODE` and matching bootstrap input to `team_protected` through a
   separately reviewed change;
4. re-read the live repository, environment, branch/ruleset, OIDC template, and AWS trust settings;
5. run all release gates and a credentialless refusal test before re-enabling controlled workflows.

Changing governance mode never justifies an IAM wildcard, merging the plan/deploy roles, trusting
`demo-plan` from deploy, skipping saved-plan identity, or weakening teardown confirmation.

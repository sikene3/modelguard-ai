# AWS deployment order

The authoritative Phase 08 architecture, IAM table, activation barriers, alarm sources, costs, and
teardown inventory are in [TERRAFORM_AWS.md](TERRAFORM_AWS.md). The protected automation and GitHub
setup are in [CICD_SECURITY.md](CICD_SECURITY.md). This page is the short operator sequence. Phase 08
performs validation only; live plan/apply evidence below belongs to Phase 10.

## 1. Retained audit, budget, and trust prerequisites

1. Manually create the retained `modelguard-ai-demo-monthly` USD 10 budget in the AWS Console with
   50/80/100 percent actual and 100 percent forecast alerts. Enter its endpoint only in the Console;
   alerts are warnings, not a hard spending limit. Run the value-free read-only preflight.
2. Separately review `infrastructure/audit-bootstrap`, preserve its initial local state through the
   documented encrypted offline procedure, and only in a later authorized step apply and verify the
   retained exact-state-object CloudTrail design.
3. Copy `infrastructure/bootstrap/bootstrap.auto.tfvars.example` to a Git-ignored tfvars file.
4. Run `uv sync --all-groups --locked`, then the network-free
   `uv run --frozen --no-sync python -m scripts.human_aws_login dependency` check. Only after a
   separate authentication approval, run `aws login --profile modelguard-bootstrap` and verify the
   exact STS account/Region with the guarded helper.
5. Supply the exact GitHub owner/repository names, immutable owner/repository IDs, subject-format
   flag, main ref, protected environments, and workflow paths.
6. Create, display, review, and manually apply a saved bootstrap plan so AWS trusts the customized
   subjects before GitHub emits them.
7. Compare the OIDC subject/template outputs, then activate the matching repository-level GitHub
   subject template. Never activate the GitHub template before the IAM trust exists.
8. Preserve bootstrap state in an approved encrypted location.
9. Record the state bucket, retained state/alert KMS key, backend key, permission boundary, and CI
   role ARNs.

Bootstrap is retained and owns state/OIDC/CI roles/boundary. Demo state must never import or mutate
those resources.

## 2. Configure the guarded backend and noncommitted inputs

Use `python -m scripts.render_ci_terraform` to render the stage inputs into an absolute, Git-ignored
operator directory. The only supported human variable file is that renderer's mode-`0600`
`demo-ci.tfvars.json`; set `TFVARS_FILE` to its exact path and set `BACKEND_CONFIG` to the same
directory's rendered mode-`0600` `backend.hcl`. That file must contain the exact bootstrap outputs,
KMS encryption, and `use_lockfile=true`. The apply and destroy helpers reject
symlinks, non-owner files, any filename that does not end in `.tfvars.json`, invalid JSON, and any
mode other than `0600`; the backend guard applies the same owner/mode/symlink checks before init. Do
not copy or pass the HCL `demo.auto.tfvars.example` to these helpers or silently substitute a
separately copied backend file.

For this no-independent-review deployment, set the governance value exactly once and pass it both to
the renderer and every later human helper:

```bash
export DEPLOYMENT_GOVERNANCE_MODE=solo_portfolio
```

There is no default. `team_protected` is valid only after a real independent reviewer exists. Supply
the restricted ALB CIDR, bounded AutoDestroyDate, exact boundary, and bootstrap
`alert_kms_key_arn` output to the renderer. Keep `budget_prerequisite_verified=false` until the
exact value-free USD 10 budget preflight passes. Notification addresses are not Terraform inputs.
For preferred `https_token`, include only the ACM certificate ARN and pre-created SecureString ARN.
Never fetch or place token bytes in Terraform, shell history, a plan, an output, or evidence. The
SecureString must use the AWS-managed SSM key for this phase.

## 3. Reviewed prerequisite saved plan

Keep:

```json
{
  "deployment_stage": "prerequisites",
  "activate_services": false,
  "teardown_authorized": false,
  "runtime_contract_verified": false
}
```

Omit all image references. Initialize with the reviewed backend file, save only
`prerequisites.tfplan`, and seal it with `scripts/terraform_demo_guard.py`. Render the sealed plan
through `scripts.plan_evidence` and review only its mode-`0600`, action-only
`prerequisites.tfplan.redacted.md`; never print the raw plan or its JSON. Verify the same manifest
immediately before the Phase 10 apply. The evidence must show API/dashboard count zero, schedule
disabled, and no alarm actions. The guard refuses a plan older than 24 hours. Never use
`terraform -target`. New manifests use `modelguard.saved-plan-identity.v2` and bind the exact Owner
tag, deployment governance mode, activation flag, and teardown authorization. Destroy manifests
also bind the runtime source state derived from the reviewed plan. The guard explicitly refuses
legacy v1 identities.

For prerequisite and activation applies, that explicit `scripts.plan_evidence` invocation is the
only persistent evidence-generation step. `safe_apply.sh` never creates, overwrites, or reuses the
persistent `.redacted.json` or
`.redacted.md` paths. It renders an independent review copy into one owner-only temporary directory,
prints only its Markdown, and removes the directory on success, cancellation, or failure. Therefore
an existing persistent evidence set does not block a repeated apply review.

The supported Phase 10 apply entry point is `scripts/safe_apply.sh` with the explicit
`AWS_PROFILE=modelguard-bootstrap` browser-login profile and
`PLAN_STAGE=prerequisites`; it consumes the already reviewed plan and identity manifest and refuses
arbitrary filenames. It does not create or target a plan.

## 4. Enroll drift notifications, then publish and verify immutable prerequisites

After prerequisite apply, use temporary browser-authenticated non-root credentials and the interactive
`scripts.notification_enrollment enroll --profile modelguard-bootstrap` command for the demo
drift/alarm SNS topic. The retained
budget endpoint is separate and remains Console-only. Neither endpoint is written to a file,
Terraform plan, workflow input, or artifact. Confirm the SNS subscription, then pass the
deployment's value-free verification gate before image publication.

Build and scan each Git-SHA image once, push one immutable provenance tag, and resolve each ECR
digest. Publish the seven-file bundle create-only, read it back, record every S3 VersionId, and
promote the exact `{model_version, manifest_sha256, bundle VersionIds}` pointer outside Terraform.

The supported publication command is one explicit mutation boundary after the prerequisite apply
and before activation planning:

```bash
uv run --frozen --no-sync python -m scripts.model_bundle_publisher publish-and-promote \
  --bundle artifacts/model-bundles/1.0.0 \
  --expected-account-id "$EXPECTED_AWS_ACCOUNT_ID" \
  --region us-east-1 \
  --profile modelguard-bootstrap \
  --confirmation "PUBLISH AND PROMOTE modelguard-ai model"
```

Do not redirect its output into tracked or Public evidence. It accepts no secret-value argument and
writes no local file. Review the bounded stdout identities and independently re-read the active
pointer before activation inputs are rendered. The command holds an S3 conditional lock across
version-history inspection, seven create-only uploads/readbacks, and previous-first/active-last SSM
promotion. A verified rollback releases the lock. An unprovable rollback deliberately retains it;
stop, read both pointers and the exact lock/object versions, and obtain a separate repair approval.
Never delete, overwrite, or reuse a partial semantic-version prefix—publish a new reviewed version.

Use SSM metadata APIs—not token-value retrieval—to verify that the configured token ARN names a
SecureString. The active model pointer itself is a non-secret String and is fetched for exact bundle
identity. Verify ACM, ECR digests, bundle/pointer identity, and the value-free notification enrollment
count. Run the digest-pinned runtime contract tests for API model bootstrap, dashboard S3 access, and
the one-shot monitor `aws-run` interface.

The code-only runtime now implements all three interfaces. Keep the committed
`runtime_contract_verified=false`; the activation renderer can set it true only from the exact
digest-mode `modelguard.runtime-contract-verification.v2` record produced after testing the actual
three release images. Local image-ID evidence cannot activate Terraform, and live ECS readiness is
still mandatory after apply.

## 5. Reviewed activation saved plan

Set:

```json
{
  "deployment_stage": "activation",
  "activate_services": true,
  "teardown_authorized": false,
  "runtime_contract_verified": true,
  "budget_prerequisite_verified": true,
  "expected_model_version": "<semantic-version>",
  "expected_model_manifest_sha256": "<64-hex>",
  "expected_model_object_version_ids": {"<all-seven-names>": "<exact-VersionIds>"},
  "api_image_ref": "<api-repository>@sha256:<digest>",
  "dashboard_image_ref": "<dashboard-repository>@sha256:<digest>",
  "monitor_image_ref": "<monitor-repository>@sha256:<digest>"
}
```

Render a fresh activation `demo-ci.tfvars.json`, save only `activation.tfplan`, seal its identity,
and review only the action-only redacted evidence. The plan must show desired count one, schedule and
alarms enabled, exact in-project digest references, and a live active pointer exactly matching the
verified model version, manifest, and seven VersionIds.

Apply only through the same manual script with `PLAN_STAGE=activation`. Its typed confirmation,
second immediate plan-identity verification, and final live SSM active-pointer read are mandatory.
That read uses the explicit `modelguard-bootstrap` profile and Region without decryption, then
`verify-active-pointer` binds it to the reviewed activation JSON before the mutation. The
prerequisites stage performs no pointer read.

Select governance according to `docs/DEPLOYMENT_GOVERNANCE.md`. `team_protected` cannot proceed
without a real independent reviewer. `solo_portfolio` cannot proceed while the repository is
Private and must retain manual privileged entry, exact source/image/plan evidence, separate roles,
bounded lifetime, and separate destroy confirmation. Automated checks are not independent review.

## 6. Smoke, evidence, and guarded destroy

After Phase 10 activation, verify both health routes, authenticated HTTPS prediction (or explicitly
disclosed credential-free HTTP fallback), Firehose delivery, one successful monitor heartbeat,
dashboard evidence, and every alarm source.

Render a fresh, one-run destroy input set in a new private Git-ignored directory. Use the exact
deployed AutoDestroyDate even when it is expired; changing it would fail the before-tag evidence
check. Supply the same deployed account, Region, backend, Owner, governance, CIDR, and access
settings (plus the same ACM/SSM ARNs when using HTTPS):

```bash
umask 077
uv run --frozen --no-sync python -m scripts.render_ci_terraform \
  --output-dir /absolute/git-ignored/operator-inputs/destroy \
  --stage destroy --teardown-authorized \
  --account-id 123456789012 --region us-east-1 \
  --owner-tag '<deployed-owner>' --governance-mode solo_portfolio \
  --auto-destroy-date '<exact-deployed-AutoDestroyDate>' \
  --backend-bucket modelguard-ai-terraform-state-123456789012-us-east-1 \
  --backend-kms-key-arn '<bootstrap-state-key-arn>' \
  --permission-boundary-arn '<bootstrap-boundary-arn>' \
  --alert-kms-key-arn '<bootstrap-alert-key-arn>' \
  --alb-allowed-cidr '<deployed-restricted-cidr>' \
  --access-mode '<deployed-access-mode>'
export TFVARS_FILE=/absolute/git-ignored/operator-inputs/destroy/demo-ci.tfvars.json
export BACKEND_CONFIG=/absolute/git-ignored/operator-inputs/destroy/backend.hcl
export TEARDOWN_AUTHORIZED=true
```

The destroy renderer emits `deployment_stage=prerequisites`, `activate_services=false`, dormant
runtime/model inputs, and `teardown_authorized=true`. Never reuse this one-run file for apply or
activation.

After capture, run `scripts/safe_destroy.sh` with `AWS_PROFILE=modelguard-bootstrap`, exact
`DEPLOYMENT_GOVERNANCE_MODE=solo_portfolio`, and its explicit account/Region/backend/mode-`0600`
`.tfvars.json`/date inputs. Before the run, create one approved external encrypted evidence directory
with exact mode `0700`, and set `POST_DESTROY_INVENTORY` to a new absolute path such as
`/absolute/encrypted/phase-10/teardown/post-destroy-inventory-initial.json`. It creates and binds
`destroy.tfplan`, suppresses raw Terraform streams,
creates mode-`0600` sealed action-only evidence beside that plan, displays only the redacted
Markdown, requires two manual confirmations, verifies the saved plan, applies it, then runs tag and
service-specific orphan queries through
`scripts/verify_aws_teardown.sh`. The reviewed destroy evidence must contain at least one managed
resource and every managed action must be exactly `delete`; managed no-op or mixed actions fail
closed. Provider-reported drift is tolerated only for an exact allowlisted, tagged ModelGuard
resource during destroy; the evidence retains only its address and action. Foreign, untagged, or
non-destroy drift still fails. Its v2 manifest keeps the destroy input's
`activate_services=false` and separately records
`source_activation_state` as `active`, `dormant`, or `mixed_or_partial`, derived only from the two
ECS services and Scheduler before-values in the saved plan. A present deployment-guard before-value
must match the sealed governance mode; its absence is permitted as recoverable partial state. Retain
that create-only JSON evidence. After the eventual-consistency delay, run the verifier again with
the same account/profile/Region and a
different new path such as `post-destroy-inventory-confirmation.json`; never overwrite the initial
receipt.

If the destroy apply completed but inventory capture or durable retention failed, leave the failed
workflow failed and do not create, accept, or apply a zero-delete replacement plan. Recovery is a
browser-authenticated human procedure, not a green workflow rerun: bind the failed repository,
workflow run/attempt, source commit, reviewed plan and identity hashes, account, and Region; inspect
the exact retained backend read-only and prove it contains zero managed resources; then run
`scripts/verify_aws_teardown.sh` twice with distinct new create-only paths and manually attach both
checksums to the failed run's private evidence record. Keep the old confidential transfer until this
provenance and both receipts are independently reconciled. If managed state remains, create a fresh
ordinary nonempty, delete-only destroy review.

Use this bounded read-only state proof with the same exact mode-`0600` destroy backend file; raw
state is never written or displayed:

```bash
uv run --frozen --no-sync python -m scripts.human_aws_login verify \
  --profile modelguard-bootstrap --region us-east-1 \
  --expected-account-id "$EXPECTED_AWS_ACCOUNT_ID" >/dev/null
uv run --frozen --no-sync python scripts/terraform_demo_guard.py verify-backend \
  --input "$BACKEND_CONFIG" --bucket "$BACKEND_BUCKET_NAME" \
  --account-id "$EXPECTED_AWS_ACCOUNT_ID" --region us-east-1 >/dev/null
terraform -chdir=infrastructure/environments/demo init \
  -input=false -reconfigure -lockfile=readonly -backend-config="$BACKEND_CONFIG" >/dev/null
test "$(terraform -chdir=infrastructure/environments/demo workspace show)" = default
terraform -chdir=infrastructure/environments/demo state pull 2>/dev/null | \
  uv run --frozen --no-sync python scripts/terraform_demo_guard.py \
    verify-empty-managed-state >/dev/null
```

Any identity, backend, workspace, malformed-state, or managed-resource finding stops the recovery
receipt sequence.

The four destroy review targets—plan, identity, redacted JSON, and redacted Markdown—are create-only
as one review set. The helper refuses before planning if any target already exists. If an operator
cancels after the set is sealed, archive the complete set to approved private storage or deliberately
remove those four exact reviewed files before starting a new destroy review; the helper never
silently overwrites or deletes them.

State bucket/KMS, OIDC, CI roles, and the permission boundary remain intentionally. The pre-created
ACM certificate and SecureString also remain because demo state never owned them. Final bootstrap
cleanup is a separate guarded human plan after state is archived and no backend user remains.

The model publisher adds no standing resource. Its request cost is bounded to one lock lifecycle,
one version-history read, seven puts, seven exact readbacks, and a small number of pointer reads/writes;
all objects remain subject to the existing finite demo lifecycle and teardown. The retained USD 10
monthly budget remains a warning guardrail, not a hard maximum or automatic shutdown.

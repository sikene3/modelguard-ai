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
4. Verify the exact STS account and configured Region using temporary browser credentials.
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

Copy `infrastructure/environments/demo/backend.hcl.example` to an absolute, Git-ignored path and
replace it with exact bootstrap outputs. It must retain KMS encryption and `use_lockfile=true`.

Copy `demo.auto.tfvars.example` to an absolute, Git-ignored path. Supply the restricted ALB CIDR,
bounded AutoDestroyDate, exact boundary, and bootstrap `alert_kms_key_arn` output. Keep
`budget_prerequisite_verified=false` until the exact value-free USD 10 budget preflight passes.
Notification addresses are not Terraform inputs. For
preferred `https_token`, include only the ACM certificate ARN and pre-created SecureString ARN.
Never fetch or place token bytes in Terraform, shell history, a plan, an output, or evidence.
The SecureString must use the AWS-managed SSM key for this phase.

## 3. Reviewed prerequisite saved plan

Keep:

```hcl
deployment_stage          = "prerequisites"
activate_services         = false
runtime_contract_verified = false
```

Omit all image references. Initialize with the reviewed backend file, save only
`prerequisites.tfplan`, display it, and seal it with `scripts/terraform_demo_guard.py`. Verify the
same manifest immediately before the Phase 10 apply. The plan must show API/dashboard count zero,
schedule disabled, and no alarm actions. The guard refuses a plan older than 24 hours. Never use
`terraform -target`.

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

```hcl
deployment_stage          = "activation"
activate_services         = true
runtime_contract_verified = true
budget_prerequisite_verified = true
expected_model_version     = "<semantic-version>"
expected_model_manifest_sha256 = "<64-hex>"
# expected_model_object_version_ids = { all seven names = exact S3 VersionIds }
api_image_ref              = "<api-repository>@sha256:<digest>"
dashboard_image_ref        = "<dashboard-repository>@sha256:<digest>"
monitor_image_ref          = "<monitor-repository>@sha256:<digest>"
```

Save only `activation.tfplan`, display/review it, seal its identity, and verify that exact file just
before apply. The plan must show desired count one, schedule and alarms enabled, exact in-project
digest references, and a live active pointer exactly matching the verified model version, manifest,
and seven VersionIds.

Apply only through the same manual script with `PLAN_STAGE=activation`. Its typed confirmation and
second immediate identity verification are mandatory.

Select governance according to `docs/DEPLOYMENT_GOVERNANCE.md`. `team_protected` cannot proceed
without a real independent reviewer. `solo_portfolio` cannot proceed while the repository is
Private and must retain manual privileged entry, exact source/image/plan evidence, separate roles,
bounded lifetime, and separate destroy confirmation. Automated checks are not independent review.

## 6. Smoke, evidence, and guarded destroy

After Phase 10 activation, verify both health routes, authenticated HTTPS prediction (or explicitly
disclosed credential-free HTTP fallback), Firehose delivery, one successful monitor heartbeat,
dashboard evidence, and every alarm source.

After capture, run `scripts/safe_destroy.sh` with `AWS_PROFILE=modelguard-bootstrap`, a mandatory
`DEPLOYMENT_GOVERNANCE_MODE`, and its explicit account/Region/backend/tfvars/date
inputs. It creates and binds `destroy.tfplan`, requires two manual confirmations, verifies the saved
plan, applies it, then runs tag and service-specific orphan queries through
`scripts/verify_aws_teardown.sh`. Retain the JSON evidence and repeat the read-only verifier after an
eventual-consistency delay.

State bucket/KMS, OIDC, CI roles, and the permission boundary remain intentionally. The pre-created
ACM certificate and SecureString also remain because demo state never owned them. Final bootstrap
cleanup is a separate guarded human plan after state is archived and no backend user remains.

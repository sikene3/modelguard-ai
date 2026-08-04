# AWS deployment order

The authoritative Phase 08 architecture, IAM table, activation barriers, alarm sources, costs, and
teardown inventory are in [TERRAFORM_AWS.md](TERRAFORM_AWS.md). The protected automation and GitHub
setup are in [CICD_SECURITY.md](CICD_SECURITY.md). This page is the short operator sequence. Phase 08
performs validation only; live plan/apply evidence below belongs to Phase 10.

## 1. Human/SSO bootstrap

1. Copy `infrastructure/bootstrap/bootstrap.auto.tfvars.example` to a Git-ignored tfvars file.
2. Verify the exact STS account and configured Region using short-lived AWS SSO credentials.
3. Supply the exact GitHub owner/repository names, immutable owner/repository IDs, subject-format
   flag, main ref, protected environments, and workflow paths.
4. Create, display, review, and manually apply a saved bootstrap plan so AWS trusts the customized
   subjects before GitHub emits them.
5. Compare the OIDC subject/template outputs, then activate the matching repository-level GitHub
   subject template. Never activate the GitHub template before the IAM trust exists.
6. Preserve bootstrap state in an approved encrypted location.
7. Record the state bucket, retained state/alert KMS key, backend key, permission boundary, and CI
   role ARNs.

Bootstrap is retained and owns state/OIDC/CI roles/boundary. Demo state must never import or mutate
those resources.

## 2. Configure the guarded backend and noncommitted inputs

Copy `infrastructure/environments/demo/backend.hcl.example` to an absolute, Git-ignored path and
replace it with exact bootstrap outputs. It must retain KMS encryption and `use_lockfile=true`.

Copy `demo.auto.tfvars.example` to an absolute, Git-ignored path. Supply the restricted ALB CIDR,
bounded AutoDestroyDate, exact boundary, and bootstrap `alert_kms_key_arn` output. Notification
addresses are not Terraform inputs. For
preferred `https_token`, include only the ACM certificate ARN and pre-created SecureString ARN.
Never fetch or place token bytes in Terraform, shell history, a plan, an output, or evidence.
The SecureString must use the AWS-managed SSM key for this phase. Activate the `Project` cost
allocation tag before relying on the mandatory tagged budget.

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

The supported Phase 10 apply entry point is `scripts/safe_apply.sh` with
`PLAN_STAGE=prerequisites`; it consumes the already reviewed plan and identity manifest and refuses
arbitrary filenames. It does not create or target a plan.

## 4. Enroll notifications, then publish and verify immutable prerequisites

After prerequisite apply, use short-lived human/SSO credentials and the interactive
`scripts.notification_enrollment enroll` command. Terraform already points the budget notification
to the non-secret SNS topic ARN; the command enrolls one mandatory email endpoint for both budget and
drift alarms without writing it to a file, Terraform plan, workflow input, or artifact. Confirm the
AWS email, then pass the deployment's value-free verification gate before image publication.

Build and scan each Git-SHA image once, push one immutable provenance tag, and resolve each ECR
digest. Publish the seven-file bundle create-only, read it back, record every S3 VersionId, and
promote the exact `{model_version, manifest_sha256, bundle VersionIds}` pointer outside Terraform.

Use SSM metadata APIs—not token-value retrieval—to verify that the configured token ARN names a
SecureString. The active model pointer itself is a non-secret String and is fetched for exact bundle
identity. Verify ACM, ECR digests, bundle/pointer identity, and the value-free notification enrollment
count. Run the digest-pinned runtime contract tests for API model bootstrap, dashboard S3 access, and
the one-shot monitor `aws-run` interface.

The current local monitor image does not implement `aws-run`. Keep
`runtime_contract_verified=false` until a later phase adds and tests that AWS one-shot orchestration;
the Phase 08 activation guard therefore prevents the present image from being scheduled.

## 5. Reviewed activation saved plan

Set:

```hcl
deployment_stage          = "activation"
activate_services         = true
runtime_contract_verified = true
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

## 6. Smoke, evidence, and guarded destroy

After Phase 10 activation, verify both health routes, authenticated HTTPS prediction (or explicitly
disclosed credential-free HTTP fallback), Firehose delivery, one successful monitor heartbeat,
dashboard evidence, and every alarm source.

After capture, run `scripts/safe_destroy.sh` with its explicit account/Region/backend/tfvars/date
inputs. It creates and binds `destroy.tfplan`, requires two manual confirmations, verifies the saved
plan, applies it, then runs tag and service-specific orphan queries through
`scripts/verify_aws_teardown.sh`. Retain the JSON evidence and repeat the read-only verifier after an
eventual-consistency delay.

State bucket/KMS, OIDC, CI roles, and the permission boundary remain intentionally. The pre-created
ACM certificate and SecureString also remain because demo state never owned them. Final bootstrap
cleanup is a separate guarded human/SSO plan after state is archived and no backend user remains.

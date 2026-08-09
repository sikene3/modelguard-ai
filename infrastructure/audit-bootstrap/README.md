# Retained CloudTrail audit prerequisite

This independent Terraform root designs one retained, Region-pinned CloudTrail data-event trail for
the future `modelguard-ai/demo/terraform.tfstate` state and `.tflock` objects in the retained state
bucket. It is
not part of the disposable demo state and must never be applied or destroyed by a demo workflow.

The design creates a private versioned S3 log bucket, a rotating customer-managed KMS key and alias,
an exact CloudTrail/bucket/key policy boundary, bounded lifecycle retention, log-file validation, and
one single-Region trail. Material resources use `prevent_destroy`. The advanced selector records S3
object data events only for the future Terraform-state prefix; it does not collect broad S3 data
events or promise a complete account-wide management-event trail.

## State preservation before any later apply

This root intentionally starts with local Terraform state because it creates an audit prerequisite
that is separate from the main backend. Before a separately approved apply, the operator must:

1. Work only on an OS-encrypted local volume using a temporary directory with mode `0700`.
2. Keep Terraform state and backup files mode `0600`; never put them in this repository, a chat,
   GitHub, an artifact, email, or an unencrypted synchronization service.
3. After apply, stop all Terraform processes, calculate a SHA-256 digest locally, and make two
   encrypted offline copies using an organization-approved encrypted archive or encrypted removable
   volume. Encryption keys/passphrases must be entered interactively and never placed in commands,
   shell history, environment variables, source, or logs.
4. Restore one copy into a new encrypted temporary directory and verify its SHA-256 digest before
   treating preservation as complete. Record only the value-free verification status, not state
   contents or encryption material.
5. Retain the original encrypted copy until a later reviewed migration to a retained remote backend.

No `terraform init`, `plan`, `apply`, import, state command, or AWS mutation is authorized by this
design-only phase.

## Exact scanner decisions

Nine resource-local Checkov directives are deliberate and expiring. The KMS document's three
directives cover the unavoidable self-key `Resource="*"` form while exact principals, enumerated
actions, source account, trail ARN, and encryption context remain enforced. The trail stays
single-Region and S3-only: a second CloudWatch copy, SNS topic, cross-Region replica, unconsumed
bucket notification, or recursive server-access log path would add retained resources, authority,
and cost outside the exact two-object audit contract. These are not global exclusions; the security
policy validates each finding ID, rationale, owner, and expiry, and focused tests pin the exact set.

## Cost and recovery limits

CloudTrail S3 data events, KMS requests/key storage, S3 object/version storage, and retrieval can all
incur usage-based charges. The design does not promise zero cost. Current logs expire after the
configured retention period (365 days by default), and noncurrent versions after 90 days; expiration
reduces cost but permanently limits historical recovery. `prevent_destroy` blocks routine Terraform
destruction but cannot replace account security, backups, or an explicit recovery procedure.

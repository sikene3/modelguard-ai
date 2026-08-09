# Retained AWS account prerequisites

These prerequisites are intentionally outside the disposable demo lifecycle. This document is a
manual design and read-only verification contract. It does not authorize an AWS mutation.

## USD 10 monthly budget

Create one AWS Cost Budget manually in the AWS Console:

- Name: `modelguard-ai-demo-monthly`
- Type and period: cost, monthly
- Amount: USD 10
- Alerts: 50% actual, 80% actual, 100% actual, and 100% forecast
- Notification endpoint: entered and confirmed by the operator only in the AWS Console

AWS Budgets sends warnings; it does not impose a hard spending cap and cannot guarantee that charges
stop at USD 10. Service usage, billing-data delay, forecast behavior, and notification delivery can
all affect timing.

The endpoint must never enter source, Terraform, state, a saved plan, GitHub secrets or variables,
workflow inputs or artifacts, reports, logs, commands, examples, screenshots, or chat. Do not use
Terraform to own the budget or subscription. The demo Terraform has only a value-free activation
guard.

After a separately authorized manual creation, run the read-only preflight with temporary browser
credentials:

```bash
uv run python -m scripts.aws_readiness_preflight budget \
  --profile modelguard-bootstrap --region us-east-1
```

The check calls only budget identity and notification-threshold APIs. It deliberately never calls a
subscriber endpoint API and prints no account ID or endpoint. It passes only for the exact name,
USD amount, monthly cost type, and exact four-threshold set.

## Retained CloudTrail state-object audit

`infrastructure/audit-bootstrap` is a separate Terraform root for the future exact
`modelguard-ai/demo/terraform.tfstate` and `.tflock` object data events. It creates a retained
single-Region trail, private versioned KMS-encrypted log bucket, KMS key and alias, public-access
block, TLS-only/exact-service bucket policy, log-file validation, finite lifecycle, and
`prevent_destroy`. It is not part of demo state or demo teardown.

Before any later apply, review its README and preserve its initial local state on encrypted storage
with two offline copies and a verified restore. CloudTrail data events, S3 storage/retrieval, KMS key
storage, and KMS requests can incur usage-based cost. Expiration is permanent and bounds recovery.
No init, plan, apply, or state operation ran during this local segment.

## Firehose account readiness

Firehose remains the prediction-event architecture. There is no fallback to another service. A
read-only preflight distinguishes three states:

- `stream_not_created`: the service API is available and the future exact stream is absent;
- an existing exact stream with an allowed provider status;
- `firehose_service_subscription_required`: AWS returned `SubscriptionRequiredException`.

The subscription-required result is an external account/service readiness blocker, not evidence
that a delivery stream is merely absent. Resolve it only through AWS Support or the documented AWS
account activation path in a separately authorized session. Do not broaden IAM, create a stream,
activate a service, or silently switch storage during preflight.

```bash
uv run python -m scripts.aws_readiness_preflight firehose \
  --profile modelguard-bootstrap --region us-east-1
```

The command is read-only. A permission denial or malformed response fails closed.

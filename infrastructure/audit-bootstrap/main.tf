data "aws_caller_identity" "current" {}
data "aws_partition" "current" {}
data "aws_region" "current" {}

locals {
  project_name      = "modelguard-ai"
  state_bucket_name = "modelguard-ai-terraform-state-${var.aws_account_id}-${var.aws_region}"
  trail_name        = "modelguard-ai-terraform-state-data-events"
  trail_arn         = "arn:${data.aws_partition.current.partition}:cloudtrail:${var.aws_region}:${var.aws_account_id}:trail/${local.trail_name}"
  log_bucket_name   = "modelguard-ai-audit-${var.aws_account_id}-${var.aws_region}"
  log_prefix        = "terraform-state-data-events"
  common_tags = {
    Project         = local.project_name
    Environment     = "audit-bootstrap"
    Owner           = var.owner_tag
    ManagedBy       = "Terraform"
    Ownership       = "retained-audit"
    AutoDestroyDate = var.review_date
  }
}

resource "terraform_data" "account_region_guard" {
  input = "${local.project_name}-audit-bootstrap"

  lifecycle {
    precondition {
      condition = (
        data.aws_caller_identity.current.account_id == var.aws_account_id &&
        data.aws_region.current.region == var.aws_region
      )
      error_message = "Refusing retained audit bootstrap outside the exact account and Region."
    }
  }
}

data "aws_iam_policy_document" "audit_kms" {
  # checkov:skip=CKV_AWS_109:The same-account root is the retained recovery/IAM boundary; CloudTrail is separately constrained by exact principal, account, trail ARN, and encryption context. [owner=modelguard-maintainers; expires=2026-10-31]
  # checkov:skip=CKV_AWS_111:KMS key policies require Resource="*" to denote their own key; explicit account-administration actions and exact CloudTrail conditions bound use. [owner=modelguard-maintainers; expires=2026-10-31]
  # checkov:skip=CKV_AWS_356:The not-yet-created key ARN cannot self-reference in its policy; exact principals, enumerated actions, account, trail ARN, and encryption context are enforced. [owner=modelguard-maintainers; expires=2026-10-31]
  statement {
    sid    = "AccountControlsAuditKey"
    effect = "Allow"

    principals {
      type        = "AWS"
      identifiers = ["arn:${data.aws_partition.current.partition}:iam::${var.aws_account_id}:root"]
    }

    actions = [
      "kms:CancelKeyDeletion",
      "kms:CreateAlias",
      "kms:CreateGrant",
      "kms:Decrypt",
      "kms:DeleteAlias",
      "kms:DescribeKey",
      "kms:DisableKey",
      "kms:DisableKeyRotation",
      "kms:EnableKey",
      "kms:EnableKeyRotation",
      "kms:Encrypt",
      "kms:GenerateDataKey",
      "kms:GetKeyPolicy",
      "kms:GetKeyRotationStatus",
      "kms:ListGrants",
      "kms:ListKeyPolicies",
      "kms:ListResourceTags",
      "kms:PutKeyPolicy",
      "kms:ReEncryptFrom",
      "kms:ReEncryptTo",
      "kms:RetireGrant",
      "kms:RevokeGrant",
      "kms:ScheduleKeyDeletion",
      "kms:TagResource",
      "kms:UntagResource",
      "kms:UpdateAlias",
      "kms:UpdateKeyDescription",
    ]
    resources = ["*"]
  }

  statement {
    sid    = "AllowExactCloudTrailEncryption"
    effect = "Allow"

    principals {
      type        = "Service"
      identifiers = ["cloudtrail.amazonaws.com"]
    }

    actions = [
      "kms:DescribeKey",
      "kms:GenerateDataKey*",
    ]
    resources = ["*"]

    condition {
      test     = "StringEquals"
      variable = "AWS:SourceAccount"
      values   = [var.aws_account_id]
    }

    condition {
      test     = "StringEquals"
      variable = "AWS:SourceArn"
      values   = [local.trail_arn]
    }

    condition {
      test     = "StringEquals"
      variable = "kms:EncryptionContext:aws:cloudtrail:arn"
      values   = [local.trail_arn]
    }
  }
}

resource "aws_kms_key" "audit" {
  description             = "Retained ModelGuard Terraform-state CloudTrail log encryption"
  enable_key_rotation     = true
  deletion_window_in_days = 30
  policy                  = data.aws_iam_policy_document.audit_kms.json

  tags = merge(local.common_tags, { Name = "${local.project_name}-audit" })

  lifecycle {
    prevent_destroy = true
  }
}

resource "aws_kms_alias" "audit" {
  name          = "alias/${local.project_name}-audit"
  target_key_id = aws_kms_key.audit.key_id

  lifecycle {
    prevent_destroy = true
  }
}

resource "aws_s3_bucket" "audit" {
  # checkov:skip=CKV_AWS_18:The CloudTrail log sink cannot safely server-log to itself; exact CloudTrail delivery, TLS denial, versioning, and KMS encryption cover this retained boundary. [owner=modelguard-maintainers; expires=2026-10-31]
  # checkov:skip=CKV_AWS_144:Cross-Region replication contradicts the explicitly single-Region personal-account design and would add unapproved retained resources and cost. [owner=modelguard-maintainers; expires=2026-10-31]
  # checkov:skip=CKV2_AWS_62:Bucket notifications would create an unconsumed retained event path; the bucket itself is the exact CloudTrail evidence destination. [owner=modelguard-maintainers; expires=2026-10-31]
  bucket        = local.log_bucket_name
  force_destroy = false

  tags = merge(local.common_tags, { Name = local.log_bucket_name })

  lifecycle {
    prevent_destroy = true
  }
}

resource "aws_s3_bucket_public_access_block" "audit" {
  bucket                  = aws_s3_bucket.audit.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true

  lifecycle {
    prevent_destroy = true
  }
}

resource "aws_s3_bucket_ownership_controls" "audit" {
  bucket = aws_s3_bucket.audit.id

  rule {
    object_ownership = "BucketOwnerEnforced"
  }

  lifecycle {
    prevent_destroy = true
  }
}

resource "aws_s3_bucket_versioning" "audit" {
  bucket = aws_s3_bucket.audit.id

  versioning_configuration {
    status = "Enabled"
  }

  lifecycle {
    prevent_destroy = true
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "audit" {
  bucket = aws_s3_bucket.audit.id

  rule {
    apply_server_side_encryption_by_default {
      kms_master_key_id = aws_kms_key.audit.arn
      sse_algorithm     = "aws:kms"
    }
    bucket_key_enabled = true
  }

  lifecycle {
    prevent_destroy = true
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "audit" {
  bucket = aws_s3_bucket.audit.id

  rule {
    id     = "retained-audit-log-recovery-window"
    status = "Enabled"

    filter {}

    expiration {
      days = var.current_log_retention_days
    }

    noncurrent_version_expiration {
      noncurrent_days = var.noncurrent_log_retention_days
    }

    abort_incomplete_multipart_upload {
      days_after_initiation = 1
    }
  }

  depends_on = [aws_s3_bucket_versioning.audit]

  lifecycle {
    prevent_destroy = true
  }
}

data "aws_iam_policy_document" "audit_bucket" {
  statement {
    sid    = "DenyInsecureTransport"
    effect = "Deny"

    principals {
      type        = "*"
      identifiers = ["*"]
    }

    actions = ["s3:*"]
    resources = [
      aws_s3_bucket.audit.arn,
      "${aws_s3_bucket.audit.arn}/*",
    ]

    condition {
      test     = "Bool"
      variable = "aws:SecureTransport"
      values   = ["false"]
    }
  }

  statement {
    sid    = "AllowExactCloudTrailBucketCheck"
    effect = "Allow"

    principals {
      type        = "Service"
      identifiers = ["cloudtrail.amazonaws.com"]
    }

    actions   = ["s3:GetBucketAcl"]
    resources = [aws_s3_bucket.audit.arn]

    condition {
      test     = "StringEquals"
      variable = "AWS:SourceAccount"
      values   = [var.aws_account_id]
    }

    condition {
      test     = "StringEquals"
      variable = "AWS:SourceArn"
      values   = [local.trail_arn]
    }
  }

  statement {
    sid    = "AllowExactCloudTrailLogDelivery"
    effect = "Allow"

    principals {
      type        = "Service"
      identifiers = ["cloudtrail.amazonaws.com"]
    }

    actions = ["s3:PutObject"]
    resources = [
      "${aws_s3_bucket.audit.arn}/${local.log_prefix}/AWSLogs/${var.aws_account_id}/*",
    ]

    condition {
      test     = "StringEquals"
      variable = "AWS:SourceAccount"
      values   = [var.aws_account_id]
    }

    condition {
      test     = "StringEquals"
      variable = "AWS:SourceArn"
      values   = [local.trail_arn]
    }

    condition {
      test     = "StringEquals"
      variable = "s3:x-amz-acl"
      values   = ["bucket-owner-full-control"]
    }
  }
}

resource "aws_s3_bucket_policy" "audit" {
  bucket = aws_s3_bucket.audit.id
  policy = data.aws_iam_policy_document.audit_bucket.json

  depends_on = [aws_s3_bucket_public_access_block.audit]

  lifecycle {
    prevent_destroy = true
  }
}

resource "aws_cloudtrail" "terraform_state_data_events" {
  # checkov:skip=CKV_AWS_252:An SNS path would be an unconsumed retained notification resource and could invite endpoint PII; value-free S3 evidence is the approved contract. [owner=modelguard-maintainers; expires=2026-10-31]
  # checkov:skip=CKV_AWS_67:Only two exact us-east-1 Terraform state objects are in scope; an all-Region trail would violate the approved single-Region data-event boundary. [owner=modelguard-maintainers; expires=2026-10-31]
  # checkov:skip=CKV2_AWS_10:Duplicating retained data events into CloudWatch Logs adds IAM, storage, ingestion, and retention cost without serving the exact S3 recovery contract. [owner=modelguard-maintainers; expires=2026-10-31]
  name                          = local.trail_name
  s3_bucket_name                = aws_s3_bucket.audit.id
  s3_key_prefix                 = local.log_prefix
  kms_key_id                    = aws_kms_key.audit.arn
  enable_log_file_validation    = true
  enable_logging                = true
  include_global_service_events = false
  is_multi_region_trail         = false

  advanced_event_selector {
    name = "Exact Terraform state object data events"

    field_selector {
      field  = "eventCategory"
      equals = ["Data"]
    }

    field_selector {
      field  = "resources.type"
      equals = ["AWS::S3::Object"]
    }

    field_selector {
      field = "resources.ARN"
      equals = [
        "arn:${data.aws_partition.current.partition}:s3:::${local.state_bucket_name}/modelguard-ai/demo/terraform.tfstate",
        "arn:${data.aws_partition.current.partition}:s3:::${local.state_bucket_name}/modelguard-ai/demo/terraform.tfstate.tflock",
      ]
    }
  }

  tags = merge(local.common_tags, { Name = local.trail_name })

  depends_on = [
    aws_s3_bucket_policy.audit,
    aws_s3_bucket_server_side_encryption_configuration.audit,
  ]

  lifecycle {
    prevent_destroy = true
  }
}

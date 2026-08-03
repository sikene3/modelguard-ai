data "aws_caller_identity" "current" {}
data "aws_partition" "current" {}
data "aws_region" "current" {}

locals {
  environment       = "bootstrap"
  state_bucket_name = "${var.project_name}-terraform-state-${var.aws_account_id}-${var.aws_region}"
  common_tags = {
    Project         = var.project_name
    Environment     = local.environment
    Owner           = var.owner_tag
    ManagedBy       = "Terraform"
    Ownership       = "bootstrap"
    AutoDestroyDate = var.bootstrap_review_date
  }
}

resource "terraform_data" "bootstrap_guard" {
  input = "${var.project_name}-bootstrap"

  lifecycle {
    precondition {
      condition = (
        data.aws_caller_identity.current.account_id == var.aws_account_id &&
        data.aws_region.current.region == var.aws_region
      )
      error_message = "Refusing bootstrap outside the exact guarded AWS account and Region."
    }
  }
}

data "aws_iam_policy_document" "state_kms" {
  # checkov:skip=CKV_AWS_109:The account-root statement is the standard KMS key-policy recovery and IAM-delegation boundary; it does not grant another account access.
  # checkov:skip=CKV_AWS_111:KMS key policies require Resource="*" to denote the key carrying the policy; the principal is this exact account root.
  # checkov:skip=CKV_AWS_356:KMS key policies cannot replace Resource="*" with the not-yet-created key ARN; the exact same-account principal bounds access.

  statement {
    sid    = "AccountControlsKeyAndEnablesIamDelegation"
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
    # KMS key policies require Resource="*" to mean the key carrying this policy.
    resources = ["*"]
  }
}

resource "aws_kms_key" "state" {
  description             = "ModelGuard Terraform remote-state encryption"
  enable_key_rotation     = true
  deletion_window_in_days = 30
  policy                  = data.aws_iam_policy_document.state_kms.json

  tags = merge(local.common_tags, { Name = "${var.project_name}-terraform-state" })

  lifecycle {
    prevent_destroy = true
  }
}

resource "aws_kms_alias" "state" {
  name          = "alias/${var.project_name}-terraform-state"
  target_key_id = aws_kms_key.state.key_id

  lifecycle {
    prevent_destroy = true
  }
}

resource "aws_s3_bucket" "state" {
  # checkov:skip=CKV_AWS_18:Retained state uses a separately retained CloudTrail data-event trail; a state-owned logging bucket would create circular ownership.
  # checkov:skip=CKV_AWS_144:Cross-Region replication is outside this single-Region portfolio demo; KMS encryption, versioning, and guarded retention are enabled.
  # checkov:skip=CKV2_AWS_62:State-bucket event notifications are not a project contract; access is audited by the separately retained CloudTrail prerequisite.

  bucket        = local.state_bucket_name
  force_destroy = false

  tags = merge(local.common_tags, { Name = local.state_bucket_name })

  lifecycle {
    prevent_destroy = true
  }
}

resource "aws_s3_bucket_public_access_block" "state" {
  bucket                  = aws_s3_bucket.state.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true

  lifecycle {
    prevent_destroy = true
  }
}

resource "aws_s3_bucket_ownership_controls" "state" {
  bucket = aws_s3_bucket.state.id

  rule {
    object_ownership = "BucketOwnerEnforced"
  }

  lifecycle {
    prevent_destroy = true
  }
}

resource "aws_s3_bucket_versioning" "state" {
  bucket = aws_s3_bucket.state.id

  versioning_configuration {
    status = "Enabled"
  }

  lifecycle {
    prevent_destroy = true
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "state" {
  bucket = aws_s3_bucket.state.id

  rule {
    apply_server_side_encryption_by_default {
      kms_master_key_id = aws_kms_key.state.arn
      sse_algorithm     = "aws:kms"
    }
    bucket_key_enabled = true
  }

  lifecycle {
    prevent_destroy = true
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "state" {
  bucket = aws_s3_bucket.state.id

  rule {
    id     = "finite-noncurrent-state-retention"
    status = "Enabled"

    filter {}

    noncurrent_version_expiration {
      noncurrent_days = var.state_noncurrent_retention_days
    }

    expiration {
      expired_object_delete_marker = true
    }

    abort_incomplete_multipart_upload {
      days_after_initiation = 1
    }
  }

  depends_on = [aws_s3_bucket_versioning.state]

  lifecycle {
    prevent_destroy = true
  }
}

data "aws_iam_policy_document" "state_bucket" {
  statement {
    sid    = "DenyInsecureTransport"
    effect = "Deny"

    principals {
      type        = "*"
      identifiers = ["*"]
    }

    actions = ["s3:*"]
    resources = [
      aws_s3_bucket.state.arn,
      "${aws_s3_bucket.state.arn}/*",
    ]

    condition {
      test     = "Bool"
      variable = "aws:SecureTransport"
      values   = ["false"]
    }
  }
}

resource "aws_s3_bucket_policy" "state" {
  bucket = aws_s3_bucket.state.id
  policy = data.aws_iam_policy_document.state_bucket.json

  depends_on = [aws_s3_bucket_public_access_block.state]

  lifecycle {
    prevent_destroy = true
  }
}

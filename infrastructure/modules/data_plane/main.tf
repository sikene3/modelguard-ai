data "aws_partition" "current" {}

locals {
  audit_bucket_arn = aws_s3_bucket.this["audit"].arn
  source_bucket_arns = [
    for key, bucket in aws_s3_bucket.this : bucket.arn if key != "audit"
  ]
}

# SSE-S3 avoids a KMS key that would remain pending deletion after the temporary demo is destroyed.
# The data is synthetic and every bucket is private, versioned, lifecycle-bounded, and TLS-only.
resource "aws_s3_bucket" "this" {
  # checkov:skip=CKV_AWS_145:Private synthetic demo data uses mandatory SSE-S3 so verified teardown leaves no customer key pending deletion.
  # checkov:skip=CKV_AWS_144:Cross-Region replication is intentionally outside the single-Region temporary demo scope; versioning and finite retention are enabled.
  # checkov:skip=CKV_AWS_18:Models, predictions, and reports log to audit; the audit sink cannot safely server-log to itself.
  # checkov:skip=CKV2_AWS_62:Bucket event notifications are not part of this Firehose/monitor contract and would add an unconsumed event path.

  for_each = var.buckets

  bucket        = each.value.name
  force_destroy = true

  tags = merge(var.tags, {
    Name     = each.value.name
    DataRole = each.key
  })
}

resource "aws_s3_bucket_public_access_block" "this" {
  for_each = aws_s3_bucket.this

  bucket                  = each.value.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_ownership_controls" "this" {
  for_each = aws_s3_bucket.this

  bucket = each.value.id

  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}

resource "aws_s3_bucket_versioning" "this" {
  for_each = aws_s3_bucket.this

  bucket = each.value.id

  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "this" {
  for_each = aws_s3_bucket.this

  bucket = each.value.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "this" {
  for_each = aws_s3_bucket.this

  bucket = each.value.id

  rule {
    id     = "bounded-demo-retention"
    status = "Enabled"

    filter {}

    expiration {
      days = var.buckets[each.key].expiration_days
    }

    noncurrent_version_expiration {
      noncurrent_days = var.buckets[each.key].noncurrent_expiration
    }

    abort_incomplete_multipart_upload {
      days_after_initiation = 1
    }
  }

  depends_on = [aws_s3_bucket_versioning.this]
}

data "aws_iam_policy_document" "bucket" {
  for_each = aws_s3_bucket.this

  statement {
    sid    = "DenyInsecureTransport"
    effect = "Deny"

    principals {
      type        = "*"
      identifiers = ["*"]
    }

    actions = ["s3:*"]
    resources = [
      each.value.arn,
      "${each.value.arn}/*",
    ]

    condition {
      test     = "Bool"
      variable = "aws:SecureTransport"
      values   = ["false"]
    }
  }

  dynamic "statement" {
    for_each = each.key == "audit" ? [1] : []
    content {
      sid    = "AllowAlbLogDelivery"
      effect = "Allow"

      principals {
        type        = "Service"
        identifiers = ["logdelivery.elasticloadbalancing.amazonaws.com"]
      }

      actions = ["s3:PutObject"]
      resources = [
        "${local.audit_bucket_arn}/${var.alb_log_prefix}/AWSLogs/${var.account_id}/*",
      ]

      condition {
        test     = "StringEquals"
        variable = "aws:SourceAccount"
        values   = [var.account_id]
      }

      condition {
        test     = "ArnLike"
        variable = "aws:SourceArn"
        values = [
          "arn:${data.aws_partition.current.partition}:elasticloadbalancing:${var.region}:${var.account_id}:loadbalancer/app/${var.alb_name}/*",
        ]
      }
    }
  }

  dynamic "statement" {
    for_each = each.key == "audit" ? [1] : []
    content {
      sid    = "AllowS3ServerAccessLogs"
      effect = "Allow"

      principals {
        type        = "Service"
        identifiers = ["logging.s3.amazonaws.com"]
      }

      actions   = ["s3:PutObject"]
      resources = ["${local.audit_bucket_arn}/s3-access/*"]

      condition {
        test     = "StringEquals"
        variable = "aws:SourceAccount"
        values   = [var.account_id]
      }

      condition {
        test     = "ArnLike"
        variable = "aws:SourceArn"
        values   = local.source_bucket_arns
      }
    }
  }
}

resource "aws_s3_bucket_policy" "this" {
  for_each = aws_s3_bucket.this

  bucket = each.value.id
  policy = data.aws_iam_policy_document.bucket[each.key].json

  depends_on = [aws_s3_bucket_public_access_block.this]
}

resource "aws_s3_bucket_logging" "this" {
  for_each = {
    for key, bucket in aws_s3_bucket.this : key => bucket
    if var.buckets[key].receives_access_logging
  }

  bucket        = each.value.id
  target_bucket = aws_s3_bucket.this["audit"].id
  target_prefix = "s3-access/${each.key}/"

  depends_on = [aws_s3_bucket_policy.this]
}

resource "aws_ecr_repository" "this" {
  # checkov:skip=CKV_AWS_136:AWS-managed AES256 avoids a disposable key lingering after teardown; repositories are private, immutable, scanned, and contain no secrets.

  for_each = var.ecr_repository_names

  name                 = each.value
  image_tag_mutability = "IMMUTABLE"
  force_delete         = true

  encryption_configuration {
    encryption_type = "AES256"
  }

  image_scanning_configuration {
    scan_on_push = true
  }

  tags = merge(var.tags, {
    Name      = each.value
    Component = each.key
  })
}

resource "aws_ecr_lifecycle_policy" "this" {
  for_each = aws_ecr_repository.this

  repository = each.value.name
  policy = jsonencode({
    rules = [
      {
        rulePriority = 1
        description  = "Remove untagged demo images after one day"
        selection = {
          tagStatus   = "untagged"
          countType   = "sinceImagePushed"
          countUnit   = "days"
          countNumber = 1
        }
        action = { type = "expire" }
      },
      {
        rulePriority = 2
        description  = "Retain only ten immutable provenance tags"
        selection = {
          tagStatus     = "tagged"
          tagPrefixList = ["git-"]
          countType     = "imageCountMoreThan"
          countNumber   = 10
        }
        action = { type = "expire" }
      },
    ]
  })
}

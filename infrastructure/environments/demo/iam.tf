locals {
  role_names = {
    execution = "${local.name_prefix}-ecs-execution"
    api       = "${local.name_prefix}-api"
    dashboard = "${local.name_prefix}-dashboard"
    monitor   = "${local.name_prefix}-monitor"
    firehose  = "${local.name_prefix}-firehose"
    scheduler = "${local.name_prefix}-scheduler"
  }
  firehose_arn = "arn:${local.partition}:firehose:${var.aws_region}:${var.aws_account_id}:deliverystream/${local.name_prefix}-predictions"
  aws_managed_key_arn_pattern = (
    "arn:${local.partition}:kms:${var.aws_region}:${var.aws_account_id}:key/*"
  )
}

data "aws_iam_policy_document" "ecs_task_trust" {
  statement {
    sid     = "EcsTasksOnly"
    effect  = "Allow"
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["ecs-tasks.amazonaws.com"]
    }

    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [var.aws_account_id]
    }

    condition {
      test     = "ArnLike"
      variable = "aws:SourceArn"
      values   = ["arn:${local.partition}:ecs:${var.aws_region}:${var.aws_account_id}:*"]
    }
  }
}

data "aws_iam_policy_document" "firehose_trust" {
  statement {
    sid     = "FirehoseOnly"
    effect  = "Allow"
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["firehose.amazonaws.com"]
    }

    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [var.aws_account_id]
    }

    condition {
      test     = "ArnEquals"
      variable = "aws:SourceArn"
      values   = [local.firehose_arn]
    }
  }
}

data "aws_iam_policy_document" "scheduler_trust" {
  statement {
    sid     = "SchedulerOnly"
    effect  = "Allow"
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["scheduler.amazonaws.com"]
    }

    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [var.aws_account_id]
    }

    condition {
      test     = "ArnEquals"
      variable = "aws:SourceArn"
      values = [
        "arn:${local.partition}:scheduler:${var.aws_region}:${var.aws_account_id}:schedule/${local.name_prefix}-monitor/${local.name_prefix}-monitor",
      ]
    }
  }
}

resource "aws_iam_role" "ecs_execution" {
  name                 = local.role_names.execution
  path                 = local.workload_path
  assume_role_policy   = data.aws_iam_policy_document.ecs_task_trust.json
  permissions_boundary = var.permission_boundary_arn
  max_session_duration = 3600

  tags = merge(local.common_tags, { Name = local.role_names.execution, Component = "execution" })
}

resource "aws_iam_role" "api" {
  name                 = local.role_names.api
  path                 = local.workload_path
  assume_role_policy   = data.aws_iam_policy_document.ecs_task_trust.json
  permissions_boundary = var.permission_boundary_arn
  max_session_duration = 3600

  tags = merge(local.common_tags, { Name = local.role_names.api, Component = "api" })
}

resource "aws_iam_role" "dashboard" {
  name                 = local.role_names.dashboard
  path                 = local.workload_path
  assume_role_policy   = data.aws_iam_policy_document.ecs_task_trust.json
  permissions_boundary = var.permission_boundary_arn
  max_session_duration = 3600

  tags = merge(local.common_tags, { Name = local.role_names.dashboard, Component = "dashboard" })
}

resource "aws_iam_role" "monitor" {
  name                 = local.role_names.monitor
  path                 = local.workload_path
  assume_role_policy   = data.aws_iam_policy_document.ecs_task_trust.json
  permissions_boundary = var.permission_boundary_arn
  max_session_duration = 3600

  tags = merge(local.common_tags, { Name = local.role_names.monitor, Component = "monitor" })
}

resource "aws_iam_role" "firehose" {
  name                 = local.role_names.firehose
  path                 = local.workload_path
  assume_role_policy   = data.aws_iam_policy_document.firehose_trust.json
  permissions_boundary = var.permission_boundary_arn
  max_session_duration = 3600

  tags = merge(local.common_tags, { Name = local.role_names.firehose, Component = "firehose" })
}

resource "aws_iam_role" "scheduler" {
  name                 = local.role_names.scheduler
  path                 = local.workload_path
  assume_role_policy   = data.aws_iam_policy_document.scheduler_trust.json
  permissions_boundary = var.permission_boundary_arn
  max_session_duration = 3600

  tags = merge(local.common_tags, { Name = local.role_names.scheduler, Component = "scheduler" })
}

data "aws_iam_policy_document" "ecs_execution" {
  statement {
    sid       = "EcrAuthorization"
    effect    = "Allow"
    actions   = ["ecr:GetAuthorizationToken"]
    resources = ["*"]
  }

  statement {
    sid    = "PullOnlyDemoImages"
    effect = "Allow"
    actions = [
      "ecr:BatchCheckLayerAvailability",
      "ecr:BatchGetImage",
      "ecr:GetDownloadUrlForLayer",
    ]
    resources = values(module.data_plane.ecr_repository_arns)
  }

  statement {
    sid    = "WriteOnlyTaskLogs"
    effect = "Allow"
    actions = [
      "logs:CreateLogStream",
      "logs:PutLogEvents",
    ]
    resources = [
      for group in values(aws_cloudwatch_log_group.application) : "${group.arn}:*"
    ]
  }

  dynamic "statement" {
    for_each = var.api_access_mode == "https_token" ? compact([var.prediction_token_ssm_arn]) : []
    content {
      sid       = "InjectOnlyReferencedPredictionToken"
      effect    = "Allow"
      actions   = ["ssm:GetParameters"]
      resources = [statement.value]
    }
  }

  dynamic "statement" {
    for_each = var.api_access_mode == "https_token" ? [1] : []
    content {
      sid       = "DecryptOnlyAwsManagedSsmKey"
      effect    = "Allow"
      actions   = ["kms:Decrypt"]
      resources = [local.aws_managed_key_arn_pattern]

      condition {
        test     = "ForAnyValue:StringEquals"
        variable = "kms:ResourceAliases"
        values   = ["alias/aws/ssm"]
      }
    }
  }
}

resource "aws_iam_role_policy" "ecs_execution" {
  name   = "pull-logs-and-token-reference"
  role   = aws_iam_role.ecs_execution.id
  policy = data.aws_iam_policy_document.ecs_execution.json
}

data "aws_iam_policy_document" "api" {
  statement {
    sid    = "ReadVersionedModelBundle"
    effect = "Allow"
    actions = [
      "s3:GetObject",
      "s3:GetObjectVersion",
    ]
    resources = ["${module.data_plane.bucket_arns["models"]}/model-bundles/*"]
  }

  statement {
    sid       = "ListModelBundlePrefix"
    effect    = "Allow"
    actions   = ["s3:ListBucket"]
    resources = [module.data_plane.bucket_arns["models"]]

    condition {
      test     = "StringLike"
      variable = "s3:prefix"
      values   = ["model-bundles/*"]
    }
  }

  statement {
    sid    = "ReadExactModelPointers"
    effect = "Allow"
    actions = [
      "ssm:GetParameter",
      "ssm:GetParameters",
    ]
    resources = [
      aws_ssm_parameter.active_model.arn,
      aws_ssm_parameter.previous_model.arn,
    ]
  }

  statement {
    sid    = "WritePredictionEventsOnly"
    effect = "Allow"
    actions = [
      "firehose:PutRecord",
      "firehose:PutRecordBatch",
    ]
    resources = [local.firehose_arn]
  }
}

resource "aws_iam_role_policy" "api" {
  name   = "model-pointer-and-prediction-events"
  role   = aws_iam_role.api.id
  policy = data.aws_iam_policy_document.api.json
}

data "aws_iam_policy_document" "dashboard" {
  statement {
    sid       = "ReadActiveModelManifest"
    effect    = "Allow"
    actions   = ["s3:GetObject"]
    resources = ["${module.data_plane.bucket_arns["models"]}/model-bundles/*/manifest.json"]
  }

  statement {
    sid       = "ReadMonitoringEvidence"
    effect    = "Allow"
    actions   = ["s3:GetObject"]
    resources = ["${module.data_plane.bucket_arns["reports"]}/monitoring/*"]
  }

  statement {
    sid       = "ListMonitoringEvidencePrefix"
    effect    = "Allow"
    actions   = ["s3:ListBucket"]
    resources = [module.data_plane.bucket_arns["reports"]]

    condition {
      test     = "StringLike"
      variable = "s3:prefix"
      values   = ["monitoring/*"]
    }
  }
}

resource "aws_iam_role_policy" "dashboard" {
  name   = "read-only-model-and-reports"
  role   = aws_iam_role.dashboard.id
  policy = data.aws_iam_policy_document.dashboard.json
}

data "aws_iam_policy_document" "monitor" {
  statement {
    sid    = "ReadVersionedModelBundleObjects"
    effect = "Allow"
    actions = [
      "s3:GetObject",
      "s3:GetObjectVersion",
    ]
    resources = ["${module.data_plane.bucket_arns["models"]}/model-bundles/*"]
  }

  statement {
    sid       = "ListVersionedModelBundlePrefix"
    effect    = "Allow"
    actions   = ["s3:ListBucket"]
    resources = [module.data_plane.bucket_arns["models"]]

    condition {
      test     = "StringLike"
      variable = "s3:prefix"
      values   = ["model-bundles/*"]
    }
  }

  statement {
    sid    = "ReadVersionedPredictionObjects"
    effect = "Allow"
    actions = [
      "s3:GetObject",
      "s3:GetObjectVersion",
    ]
    resources = ["${module.data_plane.bucket_arns["predictions"]}/predictions/*"]
  }

  statement {
    sid       = "ListPredictionInputPrefix"
    effect    = "Allow"
    actions   = ["s3:ListBucket"]
    resources = [module.data_plane.bucket_arns["predictions"]]

    condition {
      test     = "StringLike"
      variable = "s3:prefix"
      values   = ["predictions/*"]
    }
  }

  statement {
    sid    = "UseMonitoringEvidenceObjects"
    effect = "Allow"
    actions = [
      "s3:GetObject",
      "s3:PutObject",
    ]
    resources = ["${module.data_plane.bucket_arns["reports"]}/monitoring/*"]
  }

  statement {
    sid       = "ListMonitoringEvidencePrefix"
    effect    = "Allow"
    actions   = ["s3:ListBucket"]
    resources = [module.data_plane.bucket_arns["reports"]]

    condition {
      test     = "StringLike"
      variable = "s3:prefix"
      values   = ["monitoring/*"]
    }
  }

  statement {
    sid    = "ReadExactModelPointers"
    effect = "Allow"
    actions = [
      "ssm:GetParameter",
      "ssm:GetParameters",
    ]
    resources = [
      aws_ssm_parameter.active_model.arn,
      aws_ssm_parameter.previous_model.arn,
    ]
  }

  statement {
    sid       = "PublishDriftTransitions"
    effect    = "Allow"
    actions   = ["sns:Publish"]
    resources = [aws_sns_topic.alerts.arn]
  }

  statement {
    sid    = "UseRetainedKeyForExactAlertTopic"
    effect = "Allow"
    actions = [
      "kms:Decrypt",
      "kms:GenerateDataKey",
    ]
    resources = [var.alert_kms_key_arn]

    condition {
      test     = "StringEquals"
      variable = "kms:EncryptionContext:aws:sns:topicArn"
      values   = [aws_sns_topic.alerts.arn]
    }

    condition {
      test     = "StringEquals"
      variable = "kms:ViaService"
      values   = ["sns.${var.aws_region}.amazonaws.com"]
    }
  }
}

resource "aws_iam_role_policy" "monitor" {
  name   = "read-inputs-write-reports-alert"
  role   = aws_iam_role.monitor.id
  policy = data.aws_iam_policy_document.monitor.json
}

data "aws_iam_policy_document" "firehose" {
  statement {
    sid    = "UsePredictionBucketMetadata"
    effect = "Allow"
    actions = [
      "s3:GetBucketLocation",
      "s3:ListBucketMultipartUploads",
    ]
    resources = [module.data_plane.bucket_arns["predictions"]]
  }

  statement {
    sid       = "ListPredictionDeliveryPrefixes"
    effect    = "Allow"
    actions   = ["s3:ListBucket"]
    resources = [module.data_plane.bucket_arns["predictions"]]

    condition {
      test     = "StringLike"
      variable = "s3:prefix"
      values = [
        "predictions/*",
        "errors/*",
      ]
    }
  }

  statement {
    sid    = "DeliverPredictionObjects"
    effect = "Allow"
    actions = [
      "s3:AbortMultipartUpload",
      "s3:GetObject",
      "s3:PutObject",
    ]
    resources = [
      "${module.data_plane.bucket_arns["predictions"]}/predictions/*",
      "${module.data_plane.bucket_arns["predictions"]}/errors/*",
    ]
  }

  statement {
    sid    = "WriteFirehoseLogs"
    effect = "Allow"
    actions = [
      "logs:PutLogEvents",
    ]
    resources = ["${aws_cloudwatch_log_group.firehose.arn}:log-stream:${aws_cloudwatch_log_stream.firehose.name}"]
  }
}

resource "aws_iam_role_policy" "firehose" {
  name   = "deliver-predictions-to-s3"
  role   = aws_iam_role.firehose.id
  policy = data.aws_iam_policy_document.firehose.json
}

data "aws_iam_policy_document" "scheduler" {
  statement {
    sid       = "RunExactMonitorTask"
    effect    = "Allow"
    actions   = ["ecs:RunTask"]
    resources = [aws_ecs_task_definition.monitor.arn]

    condition {
      test     = "ArnEquals"
      variable = "ecs:cluster"
      values   = [aws_ecs_cluster.this.arn]
    }
  }

  statement {
    sid     = "PassOnlyMonitorTaskRolesToEcs"
    effect  = "Allow"
    actions = ["iam:PassRole"]
    resources = [
      aws_iam_role.ecs_execution.arn,
      aws_iam_role.monitor.arn,
    ]

    condition {
      test     = "StringEquals"
      variable = "iam:PassedToService"
      values   = ["ecs-tasks.amazonaws.com"]
    }
  }
}

resource "aws_iam_role_policy" "scheduler" {
  name   = "run-exact-monitor-task"
  role   = aws_iam_role.scheduler.id
  policy = data.aws_iam_policy_document.scheduler.json
}

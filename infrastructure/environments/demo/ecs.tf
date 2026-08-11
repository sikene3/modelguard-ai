resource "aws_ecs_cluster" "this" {
  # checkov:skip=CKV_AWS_65:Paid Container Insights is deliberately disabled; no alarm claims its metrics and the tested native/EMF matrix covers this temporary demo. [owner=modelguard-maintainers; expires=2026-10-31]

  name = local.name_prefix

  # Container Insights is intentionally disabled: no desired/running alarms depend on its paid
  # metrics. Native service and bounded EMF sources cover the required Phase 08 matrix.
  setting {
    name  = "containerInsights"
    value = "disabled"
  }

  tags = merge(local.common_tags, { Name = local.name_prefix })
}

locals {
  api_environment = merge({
    APP_ENV                           = "aws"
    RUNTIME_COMPONENT                 = "api"
    HOME                              = "/tmp"
    LOG_LEVEL                         = "INFO"
    MODEL_BUNDLE_PATH                 = "/runtime/model-bundle"
    ACTIVE_MODEL_VERSION              = local.active_model_version
    MODEL_BUNDLE_TRUSTED_ORIGIN       = "true"
    API_ACCESS_MODE                   = var.api_access_mode
    ALB_ALLOWED_CIDR                  = var.alb_allowed_cidr
    API_MAX_CONCURRENCY               = "64"
    API_INFERENCE_WORKERS             = "1"
    EVENT_SINK                        = "aws"
    EVENT_SINK_TIMEOUT_SECONDS        = "0.75"
    FIREHOSE_STREAM_NAME              = aws_kinesis_firehose_delivery_stream.predictions.name
    AWS_REGION                        = var.aws_region
    MODEL_BUCKET                      = module.data_plane.bucket_names["models"]
    PREDICTION_BUCKET                 = module.data_plane.bucket_names["predictions"]
    REPORT_BUCKET                     = module.data_plane.bucket_names["reports"]
    ACTIVE_MODEL_SSM_PARAMETER        = aws_ssm_parameter.active_model.name
    GRACEFUL_SHUTDOWN_TIMEOUT_SECONDS = "10"
    },
    var.api_access_mode == "https_token" ? {
      # The ARN is non-secret identity metadata required by the application validator. The token
      # bytes arrive separately through the ECS secrets array below.
      PREDICTION_TOKEN_SSM_ARN = coalesce(var.prediction_token_ssm_arn, "")
    } : {},
  )

  api_secrets = (
    var.api_access_mode == "https_token" && var.prediction_token_ssm_arn != null ?
    [{
      name       = "PREDICTION_BEARER_TOKEN"
      value_from = var.prediction_token_ssm_arn
    }] : []
  )

  dashboard_environment = {
    APP_ENV                               = "aws"
    HOME                                  = "/tmp"
    LOG_LEVEL                             = "INFO"
    DASHBOARD_REPOSITORY                  = "s3"
    ACTIVE_MODEL_VERSION                  = local.active_model_version
    AWS_REGION                            = var.aws_region
    MODEL_BUCKET                          = module.data_plane.bucket_names["models"]
    REPORT_BUCKET                         = module.data_plane.bucket_names["reports"]
    DASHBOARD_MODEL_PREFIX                = "model-bundles/"
    DASHBOARD_REPORT_PREFIX               = "monitoring/"
    DASHBOARD_HISTORY_LIMIT               = "24"
    DASHBOARD_PRESIGNED_URL_TTL_SECONDS   = "300"
    DASHBOARD_AWS_CONNECT_TIMEOUT_SECONDS = "0.5"
    DASHBOARD_AWS_READ_TIMEOUT_SECONDS    = "2.0"
    DASHBOARD_IDENTIFIER                  = "modelguard-ai-demo-operations"
    AWS_HEALTH_REQUIRED                   = "true"
    DASHBOARD_SOURCE_REGION               = var.aws_region
    DASHBOARD_METRIC_NAMESPACE            = "ModelGuardAI"
    DASHBOARD_HEALTH_METRIC_NAME          = "MonitorCompletions"
    DASHBOARD_MONITOR_LOG_GROUP           = aws_cloudwatch_log_group.application["monitor"].name
    DASHBOARD_S3_ENDPOINT_URL             = "https://s3.${var.aws_region}.amazonaws.com"
    DASHBOARD_CLOUDWATCH_ENDPOINT_URL     = "https://monitoring.${var.aws_region}.amazonaws.com"
    DASHBOARD_LOGS_ENDPOINT_URL           = "https://logs.${var.aws_region}.amazonaws.com"
    MONITORING_CONFIG_PATH                = "/app/configs/phase-05-monitoring.json"
  }
}

module "api_service" {
  source = "../../modules/ecs_service"

  name                = "api"
  family              = "${local.name_prefix}-api"
  cluster_arn         = aws_ecs_cluster.this.arn
  image_ref           = local.effective_image_refs["api"]
  container_port      = 8000
  cpu                 = 512
  memory              = 1024
  execution_role_arn  = aws_iam_role.ecs_execution.arn
  task_role_arn       = aws_iam_role.api.arn
  environment         = local.api_environment
  secrets             = local.api_secrets
  writable_mount_path = "/runtime"
  health_check_command = [
    "CMD",
    "python",
    "-c",
    "import urllib.request; r=urllib.request.urlopen('http://127.0.0.1:8000/health/ready', timeout=2); raise SystemExit(0 if r.status == 200 else 1)",
  ]
  log_group_name     = aws_cloudwatch_log_group.application["api"].name
  region             = var.aws_region
  desired_count      = local.runtime_desired_count
  private_subnet_ids = module.network.private_subnet_ids
  security_group_id  = module.network.api_security_group_id
  target_group_arn   = aws_lb_target_group.api.arn
  tags               = local.common_tags

  depends_on = [
    aws_iam_role_policy.ecs_execution,
    aws_iam_role_policy.api,
    aws_lb_listener_rule.api,
  ]
}

module "dashboard_service" {
  source = "../../modules/ecs_service"

  name               = "dashboard"
  family             = "${local.name_prefix}-dashboard"
  cluster_arn        = aws_ecs_cluster.this.arn
  image_ref          = local.effective_image_refs["dashboard"]
  container_port     = 8501
  cpu                = 512
  memory             = 1024
  execution_role_arn = aws_iam_role.ecs_execution.arn
  task_role_arn      = aws_iam_role.dashboard.arn
  environment        = local.dashboard_environment
  health_check_command = [
    "CMD",
    "python",
    "-c",
    "import urllib.request; r=urllib.request.urlopen('http://127.0.0.1:8501/_stcore/health', timeout=2); raise SystemExit(0 if r.status == 200 and r.read().strip() == b'ok' else 1)",
  ]
  log_group_name     = aws_cloudwatch_log_group.application["dashboard"].name
  region             = var.aws_region
  desired_count      = local.runtime_desired_count
  private_subnet_ids = module.network.private_subnet_ids
  security_group_id  = module.network.dashboard_security_group_id
  target_group_arn   = aws_lb_target_group.dashboard.arn
  tags               = local.common_tags

  depends_on = [
    aws_iam_role_policy.ecs_execution,
    aws_iam_role_policy.dashboard,
    aws_lb_listener.http_demo,
    aws_lb_listener.https,
  ]
}

locals {
  monitor_environment = [
    for name in sort(keys({
      APP_ENV                    = "aws"
      RUNTIME_COMPONENT          = "monitor"
      HOME                       = "/tmp"
      LOG_LEVEL                  = "INFO"
      EVENT_SINK                 = "disabled"
      MODEL_BUNDLE_PATH          = "/runtime/model-bundle"
      ACTIVE_MODEL_VERSION       = local.active_model_version
      ACTIVE_MODEL_SSM_PARAMETER = aws_ssm_parameter.active_model.name
      AWS_REGION                 = var.aws_region
      MODEL_BUCKET               = module.data_plane.bucket_names["models"]
      PREDICTION_BUCKET          = module.data_plane.bucket_names["predictions"]
      REPORT_BUCKET              = module.data_plane.bucket_names["reports"]
      SNS_TOPIC_ARN              = aws_sns_topic.alerts.arn
      MIN_MONITORING_SAMPLES     = tostring(var.minimum_monitor_records)
      MONITORING_CONFIG_PATH     = "/app/configs/phase-05-monitoring.json"
      })) : {
      name = name
      value = {
        APP_ENV                    = "aws"
        RUNTIME_COMPONENT          = "monitor"
        HOME                       = "/tmp"
        LOG_LEVEL                  = "INFO"
        EVENT_SINK                 = "disabled"
        MODEL_BUNDLE_PATH          = "/runtime/model-bundle"
        ACTIVE_MODEL_VERSION       = local.active_model_version
        ACTIVE_MODEL_SSM_PARAMETER = aws_ssm_parameter.active_model.name
        AWS_REGION                 = var.aws_region
        MODEL_BUCKET               = module.data_plane.bucket_names["models"]
        PREDICTION_BUCKET          = module.data_plane.bucket_names["predictions"]
        REPORT_BUCKET              = module.data_plane.bucket_names["reports"]
        SNS_TOPIC_ARN              = aws_sns_topic.alerts.arn
        MIN_MONITORING_SAMPLES     = tostring(var.minimum_monitor_records)
        MONITORING_CONFIG_PATH     = "/app/configs/phase-05-monitoring.json"
      }[name]
    }
  ]
}

resource "aws_ecs_task_definition" "monitor" {
  family                   = "${local.name_prefix}-monitor"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = "1024"
  memory                   = "2048"
  execution_role_arn       = aws_iam_role.ecs_execution.arn
  task_role_arn            = aws_iam_role.monitor.arn

  runtime_platform {
    cpu_architecture        = "X86_64"
    operating_system_family = "LINUX"
  }

  volume {
    name = "runtime"
  }

  volume {
    name = "scratch"
  }

  container_definitions = jsonencode([
    {
      name                   = "monitor"
      image                  = local.effective_image_refs["monitor"]
      essential              = true
      user                   = "10001:10001"
      readonlyRootFilesystem = true
      privileged             = false
      cpu                    = 1024
      memory                 = 2048
      # This is the digest-pinned image contract for Phase 10. The hard activation precondition in
      # locals.tf keeps this task unscheduled until a reviewed image proves this one-shot command.
      command     = ["aws-run"]
      stopTimeout = 60
      environment = local.monitor_environment
      mountPoints = [
        {
          sourceVolume  = "runtime"
          containerPath = "/runtime"
          readOnly      = false
        },
        {
          sourceVolume  = "scratch"
          containerPath = "/tmp"
          readOnly      = false
        },
      ]
      linuxParameters = {
        initProcessEnabled = true
        capabilities = {
          add  = []
          drop = ["ALL"]
        }
      }
      logConfiguration = {
        logDriver = "awslogs"
        options = {
          awslogs-group         = aws_cloudwatch_log_group.application["monitor"].name
          awslogs-region        = var.aws_region
          awslogs-stream-prefix = "monitor"
          mode                  = "non-blocking"
          max-buffer-size       = "1m"
        }
      }
    }
  ])

  tags = merge(local.common_tags, { Component = "monitor" })

  depends_on = [
    aws_iam_role_policy.ecs_execution,
    aws_iam_role_policy.monitor,
  ]
}

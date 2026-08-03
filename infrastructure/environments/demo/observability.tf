resource "aws_sns_topic" "alerts" {
  name              = "${local.name_prefix}-alerts"
  display_name      = "ModelGuard demo alerts"
  kms_master_key_id = "alias/aws/sns"

  tags = merge(local.common_tags, { Name = "${local.name_prefix}-alerts" })
}

resource "aws_sns_topic_subscription" "optional_drift_email" {
  count = var.drift_notification_email == null ? 0 : 1

  topic_arn = aws_sns_topic.alerts.arn
  protocol  = "email"
  endpoint  = var.drift_notification_email
}

resource "aws_cloudwatch_log_group" "application" {
  # checkov:skip=CKV_AWS_158:Short-lived synthetic logs use AWS-managed encryption so verified teardown leaves no customer key pending deletion.
  # checkov:skip=CKV_AWS_338:One-year retention contradicts the temporary-demo cost and cleanup contract; the bounded retention variable is documented and validated.

  for_each = toset(["api", "dashboard", "monitor"])

  name              = "/${var.project_name}/${var.environment}/${each.key}"
  retention_in_days = var.log_retention_days

  tags = merge(local.common_tags, { Name = "${local.name_prefix}-${each.key}", Component = each.key })
}

resource "aws_cloudwatch_log_group" "firehose" {
  # checkov:skip=CKV_AWS_158:Short-lived synthetic logs use AWS-managed encryption so verified teardown leaves no customer key pending deletion.
  # checkov:skip=CKV_AWS_338:One-year retention contradicts the temporary-demo cost and cleanup contract; the bounded retention variable is documented and validated.

  name              = "/${var.project_name}/${var.environment}/firehose"
  retention_in_days = var.log_retention_days

  tags = merge(local.common_tags, { Name = "${local.name_prefix}-firehose", Component = "firehose" })
}

resource "aws_cloudwatch_log_stream" "firehose" {
  name           = "S3Delivery"
  log_group_name = aws_cloudwatch_log_group.firehose.name
}

locals {
  alarm_actions = [aws_sns_topic.alerts.arn]
  api_emf_dimensions = {
    Service     = "api"
    Environment = "aws"
    AccessMode  = var.api_access_mode
  }
  monitor_emf_dimensions = {
    Service     = "monitor"
    Environment = "aws"
  }
}

resource "aws_cloudwatch_metric_alarm" "alb_api_5xx" {
  # checkov:skip=CKV_AWS_319:Actions are intentionally disabled only in the prerequisite plan and enabled by the guarded activation plan.

  alarm_name          = "${local.name_prefix}-alb-api-5xx"
  alarm_description   = "Native ALB target 5xx responses; source AWS/ApplicationELB HTTPCode_Target_5XX_Count."
  actions_enabled     = var.activate_services
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 1
  threshold           = 0
  metric_name         = "HTTPCode_Target_5XX_Count"
  namespace           = "AWS/ApplicationELB"
  period              = 60
  statistic           = "Sum"
  treat_missing_data  = "notBreaching"
  alarm_actions       = local.alarm_actions
  ok_actions          = local.alarm_actions

  dimensions = {
    LoadBalancer = aws_lb.this.arn_suffix
    TargetGroup  = aws_lb_target_group.api.arn_suffix
  }

  tags = merge(local.common_tags, { Signal = "alb-api-5xx" })
}

resource "aws_cloudwatch_metric_alarm" "alb_api_latency" {
  # checkov:skip=CKV_AWS_319:Actions are intentionally disabled only in the prerequisite plan and enabled by the guarded activation plan.

  alarm_name          = "${local.name_prefix}-alb-api-latency"
  alarm_description   = "Native ALB target latency; source AWS/ApplicationELB TargetResponseTime."
  actions_enabled     = var.activate_services
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 2
  threshold           = 1
  metric_name         = "TargetResponseTime"
  namespace           = "AWS/ApplicationELB"
  period              = 60
  extended_statistic  = "p95"
  treat_missing_data  = "notBreaching"
  alarm_actions       = local.alarm_actions
  ok_actions          = local.alarm_actions

  dimensions = {
    LoadBalancer = aws_lb.this.arn_suffix
    TargetGroup  = aws_lb_target_group.api.arn_suffix
  }

  tags = merge(local.common_tags, { Signal = "alb-api-latency" })
}

resource "aws_cloudwatch_metric_alarm" "alb_healthy_hosts" {
  # checkov:skip=CKV_AWS_319:Actions are intentionally disabled only in the prerequisite plan and enabled by the guarded activation plan.

  for_each = {
    api       = aws_lb_target_group.api.arn_suffix
    dashboard = aws_lb_target_group.dashboard.arn_suffix
  }

  alarm_name          = "${local.name_prefix}-alb-${each.key}-healthy-hosts"
  alarm_description   = "Native ALB healthy targets; missing/zero breaches only after activation actions are enabled."
  actions_enabled     = var.activate_services
  comparison_operator = "LessThanThreshold"
  evaluation_periods  = 2
  threshold           = 1
  metric_name         = "HealthyHostCount"
  namespace           = "AWS/ApplicationELB"
  period              = 60
  statistic           = "Minimum"
  treat_missing_data  = "breaching"
  alarm_actions       = local.alarm_actions
  ok_actions          = local.alarm_actions

  dimensions = {
    LoadBalancer = aws_lb.this.arn_suffix
    TargetGroup  = each.value
  }

  tags = merge(local.common_tags, { Signal = "alb-${each.key}-healthy-hosts" })
}

resource "aws_cloudwatch_metric_alarm" "firehose_delivery" {
  # checkov:skip=CKV_AWS_319:Actions are intentionally disabled only in the prerequisite plan and enabled by the guarded activation plan.

  alarm_name          = "${local.name_prefix}-firehose-delivery"
  alarm_description   = "Native Firehose S3 delivery success percentage; producer acceptance is a separate API EMF signal."
  actions_enabled     = var.activate_services
  comparison_operator = "LessThanThreshold"
  evaluation_periods  = 1
  threshold           = 99
  metric_name         = "DeliveryToS3.Success"
  namespace           = "AWS/Firehose"
  period              = 300
  statistic           = "Average"
  treat_missing_data  = "notBreaching"
  alarm_actions       = local.alarm_actions
  ok_actions          = local.alarm_actions

  dimensions = {
    DeliveryStreamName = aws_kinesis_firehose_delivery_stream.predictions.name
  }

  tags = merge(local.common_tags, { Signal = "firehose-delivery" })
}

resource "aws_cloudwatch_metric_alarm" "scheduler_submission_failures" {
  # checkov:skip=CKV_AWS_319:Actions are intentionally disabled only in the prerequisite plan and enabled by the guarded activation plan.

  alarm_name          = "${local.name_prefix}-scheduler-target-errors"
  alarm_description   = "Native Scheduler submission TargetErrorCount; submission failure is explicitly not monitor completion."
  actions_enabled     = var.activate_services
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 1
  threshold           = 0
  metric_name         = "TargetErrorCount"
  namespace           = "AWS/Scheduler"
  period              = 300
  statistic           = "Sum"
  treat_missing_data  = "notBreaching"
  alarm_actions       = local.alarm_actions
  ok_actions          = local.alarm_actions

  dimensions = {
    ScheduleGroup = aws_scheduler_schedule_group.monitor.name
  }

  tags = merge(local.common_tags, { Signal = "scheduler-submission" })
}

resource "aws_cloudwatch_metric_alarm" "api_event_write_failures" {
  # checkov:skip=CKV_AWS_319:Actions are intentionally disabled only in the prerequisite plan and enabled by the guarded activation plan.

  alarm_name          = "${local.name_prefix}-api-event-write-failures"
  alarm_description   = "Bounded API EMF EventSinkErrors emitted for serialization, timeout, and Firehose producer failures."
  actions_enabled     = var.activate_services
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 1
  threshold           = 0
  metric_name         = "EventSinkErrors"
  namespace           = "ModelGuardAI"
  period              = 300
  statistic           = "Sum"
  treat_missing_data  = "notBreaching"
  alarm_actions       = local.alarm_actions
  ok_actions          = local.alarm_actions
  dimensions          = local.api_emf_dimensions

  tags = merge(local.common_tags, { Signal = "api-event-write-failures" })
}

resource "aws_cloudwatch_metric_alarm" "monitor_completion" {
  # checkov:skip=CKV_AWS_319:Actions are intentionally disabled only in the prerequisite plan and enabled by the guarded activation plan.

  alarm_name          = "${local.name_prefix}-monitor-completion"
  alarm_description   = "One bounded EMF MonitorCompletions heartbeat per successful run; missing data breaches."
  actions_enabled     = var.activate_services
  comparison_operator = "LessThanThreshold"
  evaluation_periods  = 1
  threshold           = 1
  metric_name         = "MonitorCompletions"
  namespace           = "ModelGuardAI"
  period              = var.monitor_heartbeat_period_seconds
  statistic           = "Sum"
  treat_missing_data  = "breaching"
  alarm_actions       = local.alarm_actions
  ok_actions          = local.alarm_actions
  dimensions          = local.monitor_emf_dimensions

  tags = merge(local.common_tags, { Signal = "monitor-completion" })
}

resource "aws_cloudwatch_metric_alarm" "monitor_input" {
  # checkov:skip=CKV_AWS_319:Actions are intentionally disabled only in the prerequisite plan and enabled by the guarded activation plan.

  alarm_name          = "${local.name_prefix}-monitor-input"
  alarm_description   = "One bounded EMF RawRecords input count per successful run; low or missing data breaches."
  actions_enabled     = var.activate_services
  comparison_operator = "LessThanThreshold"
  evaluation_periods  = 1
  threshold           = var.minimum_monitor_records
  metric_name         = "RawRecords"
  namespace           = "ModelGuardAI"
  period              = var.monitor_heartbeat_period_seconds
  statistic           = "Minimum"
  treat_missing_data  = "breaching"
  alarm_actions       = local.alarm_actions
  ok_actions          = local.alarm_actions
  dimensions          = local.monitor_emf_dimensions

  tags = merge(local.common_tags, { Signal = "monitor-input" })
}

resource "aws_cloudwatch_metric_alarm" "monitor_rejected" {
  # checkov:skip=CKV_AWS_319:Actions are intentionally disabled only in the prerequisite plan and enabled by the guarded activation plan.

  alarm_name          = "${local.name_prefix}-monitor-rejected"
  alarm_description   = "One bounded EMF RejectedRecords count per successful run; excess or missing data breaches."
  actions_enabled     = var.activate_services
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 1
  threshold           = var.maximum_rejected_records
  metric_name         = "RejectedRecords"
  namespace           = "ModelGuardAI"
  period              = var.monitor_heartbeat_period_seconds
  statistic           = "Maximum"
  treat_missing_data  = "breaching"
  alarm_actions       = local.alarm_actions
  ok_actions          = local.alarm_actions
  dimensions          = local.monitor_emf_dimensions

  tags = merge(local.common_tags, { Signal = "monitor-rejected" })
}

resource "aws_cloudwatch_metric_alarm" "monitor_predictions" {
  # checkov:skip=CKV_AWS_319:Actions are intentionally disabled only in the prerequisite plan and enabled by the guarded activation plan.

  alarm_name          = "${local.name_prefix}-monitor-predictions"
  alarm_description   = "One bounded EMF AcceptedTargetRecords prediction count per successful run; low or missing data breaches."
  actions_enabled     = var.activate_services
  comparison_operator = "LessThanThreshold"
  evaluation_periods  = 1
  threshold           = var.minimum_monitor_records
  metric_name         = "AcceptedTargetRecords"
  namespace           = "ModelGuardAI"
  period              = var.monitor_heartbeat_period_seconds
  statistic           = "Minimum"
  treat_missing_data  = "breaching"
  alarm_actions       = local.alarm_actions
  ok_actions          = local.alarm_actions
  dimensions          = local.monitor_emf_dimensions

  tags = merge(local.common_tags, { Signal = "monitor-predictions" })
}

resource "aws_cloudwatch_metric_alarm" "monitor_report_freshness" {
  # checkov:skip=CKV_AWS_319:Actions are intentionally disabled only in the prerequisite plan and enabled by the guarded activation plan.

  alarm_name          = "${local.name_prefix}-monitor-report-freshness"
  alarm_description   = "One bounded EMF ReportFreshnessSeconds value per successful run; stale or missing data breaches."
  actions_enabled     = var.activate_services
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 1
  threshold           = var.monitor_heartbeat_period_seconds * 2
  metric_name         = "ReportFreshnessSeconds"
  namespace           = "ModelGuardAI"
  period              = var.monitor_heartbeat_period_seconds
  statistic           = "Maximum"
  treat_missing_data  = "breaching"
  alarm_actions       = local.alarm_actions
  ok_actions          = local.alarm_actions
  dimensions          = local.monitor_emf_dimensions

  tags = merge(local.common_tags, { Signal = "monitor-report-freshness" })
}

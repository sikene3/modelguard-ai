resource "aws_scheduler_schedule_group" "monitor" {
  name = "${local.name_prefix}-monitor"

  tags = merge(local.common_tags, { Name = "${local.name_prefix}-monitor" })
}

resource "aws_scheduler_schedule" "monitor" {
  # checkov:skip=CKV_AWS_297:AWS-owned Scheduler encryption is sufficient for a synthetic command with no secret payload and avoids a disposable customer key lingering after teardown.

  name                         = "${local.name_prefix}-monitor"
  group_name                   = aws_scheduler_schedule_group.monitor.name
  description                  = "Run one bounded ModelGuard drift-monitor ECS task"
  state                        = local.monitor_schedule_state
  schedule_expression          = var.monitor_schedule_expression
  schedule_expression_timezone = "UTC"

  flexible_time_window {
    mode = "OFF"
  }

  target {
    arn      = aws_ecs_cluster.this.arn
    role_arn = aws_iam_role.scheduler.arn

    ecs_parameters {
      task_definition_arn     = aws_ecs_task_definition.monitor.arn
      launch_type             = "FARGATE"
      platform_version        = "LATEST"
      task_count              = 1
      enable_ecs_managed_tags = true
      propagate_tags          = "TASK_DEFINITION"

      network_configuration {
        assign_public_ip = false
        security_groups  = [module.network.monitor_security_group_id]
        subnets          = module.network.private_subnet_ids
      }
    }

    retry_policy {
      maximum_event_age_in_seconds = 3600
      maximum_retry_attempts       = 1
    }
  }

  depends_on = [aws_iam_role_policy.scheduler]
}

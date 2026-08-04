output "activation_state" {
  description = "Non-secret runtime barrier summary."
  value = {
    deployment_stage        = var.deployment_stage
    activate_services       = var.activate_services
    api_desired_count       = local.runtime_desired_count
    dashboard_desired_count = local.runtime_desired_count
    monitor_schedule_state  = local.monitor_schedule_state
    image_reference_mode    = "repository@sha256"
  }
}

output "alb_url" {
  description = "Restricted demo entry point; never a public-anonymous or enterprise-auth claim."
  value       = "${var.api_access_mode == "https_token" ? "https" : "http"}://${aws_lb.this.dns_name}"
}

output "ecr_repository_urls" {
  description = "Prerequisite repositories used to push once and resolve immutable digests."
  value       = module.data_plane.ecr_repository_urls
}

output "data_bucket_names" {
  description = "Private disposable model, prediction, report, and audit bucket names."
  value       = module.data_plane.bucket_names
}

output "model_pointer_names" {
  description = "Promotion-owned pointer locations; values are intentionally not output."
  value = {
    active   = aws_ssm_parameter.active_model.name
    previous = aws_ssm_parameter.previous_model.name
  }
}

output "ecs_cluster_arn" {
  description = "ECS cluster used by services and the one-shot scheduled monitor."
  value       = aws_ecs_cluster.this.arn
}

output "task_definition_arns" {
  description = "Current digest-form task definitions."
  value = {
    api       = module.api_service.task_definition_arn
    dashboard = module.dashboard_service.task_definition_arn
    monitor   = aws_ecs_task_definition.monitor.arn
  }
}

output "workload_role_arns" {
  description = "Exact boundary-constrained roles for IAM/PassRole evidence."
  value = {
    execution = aws_iam_role.ecs_execution.arn
    api       = aws_iam_role.api.arn
    dashboard = aws_iam_role.dashboard.arn
    monitor   = aws_iam_role.monitor.arn
    firehose  = aws_iam_role.firehose.arn
    scheduler = aws_iam_role.scheduler.arn
  }
}

output "alert_topic_arn" {
  description = "KMS-encrypted budget/drift topic; its email endpoint is enrolled outside Terraform."
  value       = aws_sns_topic.alerts.arn
}

output "post_destroy_inventory_identity" {
  description = "Exact tags/prefix used by the verified post-destroy inventory gate."
  value = {
    project     = var.project_name
    environment = var.environment
    name_prefix = local.name_prefix
    ownership   = "demo"
  }
}

output "task_definition_arn" {
  description = "Immutable task-definition revision ARN."
  value       = aws_ecs_task_definition.this.arn
}

output "task_definition_family" {
  description = "Task-definition family name."
  value       = aws_ecs_task_definition.this.family
}

output "service_name" {
  description = "ECS service name."
  value       = aws_ecs_service.this.name
}

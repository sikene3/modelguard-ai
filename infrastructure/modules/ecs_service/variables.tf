variable "name" {
  description = "Component name and ECS container name."
  type        = string

  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{1,30}$", var.name))
    error_message = "name must be a lowercase ECS-safe identifier."
  }
}

variable "family" {
  description = "Deterministic ECS task-definition family."
  type        = string
}

variable "cluster_arn" {
  description = "ECS cluster ARN."
  type        = string
}

variable "image_ref" {
  description = "Immutable repository@sha256 image reference; mutable tags are rejected."
  type        = string

  validation {
    condition     = can(regex("^[A-Za-z0-9./_-]+@sha256:[0-9a-f]{64}$", var.image_ref))
    error_message = "image_ref must be an immutable repository@sha256:<64 lowercase hex> reference."
  }
}

variable "container_port" {
  description = "Single container and target-group port."
  type        = number

  validation {
    condition     = var.container_port >= 1024 && var.container_port <= 65535
    error_message = "container_port must be an unprivileged TCP port."
  }
}

variable "cpu" {
  description = "Fargate task CPU units."
  type        = number
}

variable "memory" {
  description = "Fargate task memory in MiB."
  type        = number
}

variable "execution_role_arn" {
  description = "Dedicated ECS execution-role ARN."
  type        = string
}

variable "task_role_arn" {
  description = "Dedicated component task-role ARN."
  type        = string
}

variable "environment" {
  description = "Non-secret container environment variables."
  type        = map(string)
  default     = {}
}

variable "secrets" {
  description = "ECS secret references; only provider ARNs, never values."
  type = list(object({
    name       = string
    value_from = string
  }))
  default = []

  validation {
    condition = alltrue([
      for secret in var.secrets :
      can(regex("^arn:[^:]+:ssm:[a-z0-9-]+:[0-9]{12}:parameter/.+$", secret.value_from))
    ])
    error_message = "Every ECS secret must reference an SSM parameter ARN."
  }
}

variable "health_check_command" {
  description = "Container-local health command in ECS CMD/CMD-SHELL form."
  type        = list(string)

  validation {
    condition     = length(var.health_check_command) >= 2 && contains(["CMD", "CMD-SHELL"], var.health_check_command[0])
    error_message = "health_check_command must use ECS CMD or CMD-SHELL syntax."
  }
}

variable "writable_mount_path" {
  description = "Optional task-scoped ephemeral writable mount for runtime artifacts."
  type        = string
  default     = null
  nullable    = true

  validation {
    condition     = var.writable_mount_path == null || can(regex("^/[A-Za-z0-9._/-]+$", var.writable_mount_path))
    error_message = "writable_mount_path must be an absolute container path when set."
  }
}

variable "log_group_name" {
  description = "Pre-created finite-retention CloudWatch log-group name."
  type        = string
}

variable "region" {
  description = "AWS Region for the awslogs driver."
  type        = string
}

variable "desired_count" {
  description = "Zero during prerequisites and exactly one during activation."
  type        = number

  validation {
    condition     = contains([0, 1], var.desired_count)
    error_message = "desired_count must be zero or one."
  }
}

variable "private_subnet_ids" {
  description = "Two private subnet IDs used by the service."
  type        = list(string)

  validation {
    condition     = length(var.private_subnet_ids) == 2
    error_message = "Two private subnet IDs are required."
  }
}

variable "security_group_id" {
  description = "Component task security-group ID."
  type        = string
}

variable "target_group_arn" {
  description = "ALB target-group ARN for the component."
  type        = string
}

variable "tags" {
  description = "Required common resource tags."
  type        = map(string)
}

variable "aws_account_id" {
  description = "Exact guarded AWS account ID for the disposable demo."
  type        = string

  validation {
    condition     = can(regex("^[0-9]{12}$", var.aws_account_id))
    error_message = "aws_account_id must contain exactly 12 digits."
  }
}

variable "aws_region" {
  description = "Single guarded AWS Region for all disposable resources."
  type        = string
  default     = "us-east-1"

  validation {
    condition     = can(regex("^[a-z]{2}(-[a-z]+)+-[0-9]+$", var.aws_region))
    error_message = "aws_region must be a valid commercial AWS Region name."
  }
}

variable "project_name" {
  description = "Fixed project identity used by names, tags, IAM, backend, and guards."
  type        = string
  default     = "modelguard-ai"

  validation {
    condition     = var.project_name == "modelguard-ai"
    error_message = "The demo is pinned to project_name=modelguard-ai."
  }
}

variable "environment" {
  description = "Fixed disposable environment identity."
  type        = string
  default     = "demo"

  validation {
    condition     = var.environment == "demo"
    error_message = "The Phase 08 root is pinned to environment=demo."
  }
}

variable "owner_tag" {
  description = "Non-sensitive team/operator label; do not use an email address."
  type        = string

  validation {
    condition     = can(regex("^[A-Za-z0-9._-]{2,64}$", var.owner_tag)) && !strcontains(var.owner_tag, "@")
    error_message = "owner_tag must be a short non-email identifier."
  }
}

variable "auto_destroy_date" {
  description = "UTC YYYY-MM-DD teardown reminder no more than 14 days after planning; never automatic."
  type        = string

  validation {
    condition = (
      can(regex("^20[0-9]{2}-(0[1-9]|1[0-2])-([0-2][0-9]|3[01])$", var.auto_destroy_date)) &&
      can(timecmp("${var.auto_destroy_date}T00:00:00Z", "2000-01-01T00:00:00Z"))
    )
    error_message = "auto_destroy_date must use UTC YYYY-MM-DD form."
  }
}

variable "backend_bucket_name" {
  description = "Exact bootstrap-owned backend bucket name repeated for the external saved-plan guard."
  type        = string

  validation {
    condition     = can(regex("^[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$", var.backend_bucket_name))
    error_message = "backend_bucket_name must be an AWS-safe bucket name."
  }
}

variable "backend_state_key" {
  description = "Exact backend key repeated for guard comparison; Terraform cannot introspect its backend."
  type        = string
  default     = "modelguard-ai/demo/terraform.tfstate"

  validation {
    condition     = var.backend_state_key == "modelguard-ai/demo/terraform.tfstate"
    error_message = "backend_state_key is fixed to modelguard-ai/demo/terraform.tfstate."
  }
}

variable "permission_boundary_arn" {
  description = "Bootstrap-owned mandatory boundary ARN for every workload role."
  type        = string

  validation {
    condition     = can(regex("^arn:[^:]+:iam::[0-9]{12}:policy/modelguard-ai/bootstrap/modelguard-ai-workload-boundary$", var.permission_boundary_arn))
    error_message = "permission_boundary_arn must be the exact ModelGuard bootstrap boundary ARN."
  }
}

variable "alert_kms_key_arn" {
  description = "Retained bootstrap customer-managed key used only with the exact SNS topic context."
  type        = string

  validation {
    condition = can(regex(
      "^arn:aws:kms:${var.aws_region}:${var.aws_account_id}:key/[0-9a-fA-F-]{36}$",
      var.alert_kms_key_arn,
    ))
    error_message = "alert_kms_key_arn must be one exact KMS key ARN in the guarded account and Region."
  }
}

variable "deployment_stage" {
  description = "Reviewed saved-plan stage; activation must exactly agree with activate_services."
  type        = string
  default     = "prerequisites"

  validation {
    condition     = contains(["prerequisites", "activation"], var.deployment_stage)
    error_message = "deployment_stage must be prerequisites or activation."
  }
}

variable "activate_services" {
  description = "Activation barrier. False keeps API/dashboard at zero and the monitor schedule disabled."
  type        = bool
  default     = false
}

variable "runtime_contract_verified" {
  description = "Human/CI proof that all digest-pinned images implement the AWS startup and one-shot monitor contracts."
  type        = bool
  default     = false
}

variable "expected_model_version" {
  description = "Verified active-pointer model version bound into an activation plan."
  type        = string
  default     = null
  nullable    = true

  validation {
    condition     = var.expected_model_version == null || can(regex("^[0-9]+\\.[0-9]+\\.[0-9]+$", var.expected_model_version))
    error_message = "expected_model_version must be a semantic version when set."
  }
}

variable "expected_model_manifest_sha256" {
  description = "Verified active-pointer bundle manifest SHA-256 bound into an activation plan."
  type        = string
  default     = null
  nullable    = true

  validation {
    condition     = var.expected_model_manifest_sha256 == null || can(regex("^[0-9a-f]{64}$", var.expected_model_manifest_sha256))
    error_message = "expected_model_manifest_sha256 must be an exact lowercase SHA-256 when set."
  }
}

variable "expected_model_object_version_ids" {
  description = "Verified active-pointer S3 VersionIds bound into an activation plan."
  type        = map(string)
  default     = {}

  validation {
    condition = alltrue([
      for version_id in values(var.expected_model_object_version_ids) :
      length(version_id) >= 1 && length(version_id) <= 1024
    ])
    error_message = "expected_model_object_version_ids values must be nonempty bounded S3 VersionIds."
  }
}

variable "availability_zones" {
  description = "Exactly two distinct AZs in aws_region."
  type        = list(string)
  default     = ["us-east-1a", "us-east-1b"]

  validation {
    condition     = length(var.availability_zones) == 2 && length(distinct(var.availability_zones)) == 2
    error_message = "Exactly two distinct availability zones are required."
  }
}

variable "vpc_cidr" {
  description = "Private VPC IPv4 CIDR."
  type        = string
  default     = "10.42.0.0/16"

  validation {
    condition = (
      can(cidrnetmask(var.vpc_cidr)) &&
      try(cidrhost(var.vpc_cidr, 0) == split("/", var.vpc_cidr)[0], false) &&
      !strcontains(var.vpc_cidr, ":") &&
      !contains(["0.0.0.0/0", "::/0"], var.vpc_cidr)
    )
    error_message = "vpc_cidr must be a restricted canonical IPv4 CIDR."
  }
}

variable "public_subnet_cidrs" {
  description = "Public ALB subnet CIDRs in availability_zones order."
  type        = list(string)
  default     = ["10.42.0.0/24", "10.42.1.0/24"]

  validation {
    condition = (
      length(var.public_subnet_cidrs) == 2 &&
      length(distinct(var.public_subnet_cidrs)) == 2 &&
      alltrue([
        for cidr in var.public_subnet_cidrs :
        can(cidrnetmask(cidr)) &&
        try(cidrhost(cidr, 0) == split("/", cidr)[0], false) &&
        !strcontains(cidr, ":")
      ])
    )
    error_message = "public_subnet_cidrs must contain two distinct canonical IPv4 CIDRs."
  }
}

variable "private_subnet_cidrs" {
  description = "Private ECS subnet CIDRs in availability_zones order."
  type        = list(string)
  default     = ["10.42.10.0/24", "10.42.11.0/24"]

  validation {
    condition = (
      length(var.private_subnet_cidrs) == 2 &&
      length(distinct(var.private_subnet_cidrs)) == 2 &&
      alltrue([
        for cidr in var.private_subnet_cidrs :
        can(cidrnetmask(cidr)) &&
        try(cidrhost(cidr, 0) == split("/", cidr)[0], false) &&
        !strcontains(cidr, ":")
      ])
    )
    error_message = "private_subnet_cidrs must contain two distinct canonical IPv4 CIDRs."
  }
}

variable "alb_allowed_cidr" {
  description = "Explicit restricted canonical IPv4 CIDR for ALB ingress; world IPv4/IPv6 are forbidden."
  type        = string

  validation {
    condition = (
      can(cidrnetmask(var.alb_allowed_cidr)) &&
      try(cidrhost(var.alb_allowed_cidr, 0) == split("/", var.alb_allowed_cidr)[0], false) &&
      !strcontains(var.alb_allowed_cidr, ":") &&
      !contains(["0.0.0.0/0", "::/0"], var.alb_allowed_cidr)
    )
    error_message = "alb_allowed_cidr must be a restricted canonical IPv4 CIDR, never a world CIDR."
  }
}

variable "api_access_mode" {
  description = "Preferred HTTPS/token mode or disclosed temporary HTTP/CIDR-only synthetic fallback."
  type        = string
  default     = "http_cidr_only"

  validation {
    condition     = contains(["https_token", "http_cidr_only"], var.api_access_mode)
    error_message = "api_access_mode must be https_token or http_cidr_only."
  }
}

variable "acm_certificate_arn" {
  description = "Pre-created ACM certificate ARN required only for https_token."
  type        = string
  default     = null
  nullable    = true

  validation {
    condition     = var.acm_certificate_arn == null || can(regex("^arn:[^:]+:acm:[a-z0-9-]+:[0-9]{12}:certificate/[0-9a-f-]+$", var.acm_certificate_arn))
    error_message = "acm_certificate_arn must be a valid ACM certificate ARN when set."
  }
}

variable "prediction_token_ssm_arn" {
  description = "ARN only for a pre-created SSM SecureString under /modelguard-ai/demo/secrets; never its value."
  type        = string
  default     = null
  nullable    = true

  validation {
    condition = (
      var.prediction_token_ssm_arn == null ||
      can(regex("^arn:[^:]+:ssm:[a-z0-9-]+:[0-9]{12}:parameter/modelguard-ai/demo/secrets/[A-Za-z0-9_.\u002F-]+$", var.prediction_token_ssm_arn))
    )
    error_message = "prediction_token_ssm_arn must be an ARN under /modelguard-ai/demo/secrets/."
  }
}

variable "api_image_ref" {
  description = "Activation-only API ECR repository@sha256 reference."
  type        = string
  default     = null
  nullable    = true

  validation {
    condition     = var.api_image_ref == null || can(regex("@sha256:[0-9a-f]{64}$", var.api_image_ref))
    error_message = "api_image_ref must end in an immutable sha256 digest."
  }
}

variable "dashboard_image_ref" {
  description = "Activation-only dashboard ECR repository@sha256 reference."
  type        = string
  default     = null
  nullable    = true

  validation {
    condition     = var.dashboard_image_ref == null || can(regex("@sha256:[0-9a-f]{64}$", var.dashboard_image_ref))
    error_message = "dashboard_image_ref must end in an immutable sha256 digest."
  }
}

variable "monitor_image_ref" {
  description = "Activation-only monitor ECR repository@sha256 reference."
  type        = string
  default     = null
  nullable    = true

  validation {
    condition     = var.monitor_image_ref == null || can(regex("@sha256:[0-9a-f]{64}$", var.monitor_image_ref))
    error_message = "monitor_image_ref must end in an immutable sha256 digest."
  }
}

variable "log_retention_days" {
  description = "Finite CloudWatch Logs retention."
  type        = number
  default     = 14

  validation {
    condition     = contains([1, 3, 5, 7, 14, 30, 60, 90], var.log_retention_days)
    error_message = "log_retention_days must be an AWS-supported short retention value."
  }
}

variable "monitor_schedule_expression" {
  description = "Bounded EventBridge Scheduler rate for the one-shot monitor."
  type        = string
  default     = "rate(1 hour)"

  validation {
    condition     = contains(["rate(1 hour)", "rate(2 hours)", "rate(3 hours)", "rate(6 hours)"], var.monitor_schedule_expression)
    error_message = "Use one of the explicitly costed hourly monitor rates."
  }
}

variable "monitor_heartbeat_period_seconds" {
  description = "CloudWatch period aligned to the monitor rate."
  type        = number
  default     = 3600

  validation {
    condition     = contains([3600, 7200, 10800, 21600], var.monitor_heartbeat_period_seconds)
    error_message = "monitor_heartbeat_period_seconds must match an allowed schedule period."
  }
}

variable "minimum_monitor_records" {
  description = "Minimum accepted predictions expected in each finalized monitor run."
  type        = number
  default     = 500

  validation {
    condition = (
      var.minimum_monitor_records >= 1 &&
      var.minimum_monitor_records <= 100000 &&
      floor(var.minimum_monitor_records) == var.minimum_monitor_records
    )
    error_message = "minimum_monitor_records must be between 1 and 100000."
  }
}

variable "maximum_rejected_records" {
  description = "Alarm threshold for rejected records in one monitor heartbeat."
  type        = number
  default     = 0

  validation {
    condition = (
      var.maximum_rejected_records >= 0 &&
      floor(var.maximum_rejected_records) == var.maximum_rejected_records
    )
    error_message = "maximum_rejected_records must be a non-negative integer."
  }
}

variable "budget_limit_usd" {
  description = "Mandatory small monthly budget; SNS email endpoint enrollment is a separate human/SSO operation."
  type        = number
  default     = 25

  validation {
    condition     = var.budget_limit_usd >= 5 && var.budget_limit_usd <= 100
    error_message = "budget_limit_usd must stay between USD 5 and USD 100."
  }
}

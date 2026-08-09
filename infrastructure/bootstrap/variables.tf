variable "aws_account_id" {
  description = "Exact AWS account where the retained trust/state boundary is bootstrapped."
  type        = string

  validation {
    condition     = can(regex("^[0-9]{12}$", var.aws_account_id))
    error_message = "aws_account_id must contain exactly 12 digits."
  }
}

variable "aws_region" {
  description = "Single AWS Region for state and the temporary demo."
  type        = string
  default     = "us-east-1"

  validation {
    condition     = can(regex("^[a-z]{2}(-[a-z]+)+-[0-9]+$", var.aws_region))
    error_message = "aws_region must be a valid commercial AWS Region name."
  }
}

variable "project_name" {
  description = "Fixed project tag/name used by every guard and policy."
  type        = string
  default     = "modelguard-ai"

  validation {
    condition     = var.project_name == "modelguard-ai"
    error_message = "The Phase 08 bootstrap is pinned to project_name=modelguard-ai."
  }
}

variable "owner_tag" {
  description = "Non-sensitive team or operator label; do not use an email address."
  type        = string

  validation {
    condition     = can(regex("^[A-Za-z0-9._-]{2,64}$", var.owner_tag)) && !strcontains(var.owner_tag, "@")
    error_message = "owner_tag must be a short non-email identifier."
  }
}

variable "bootstrap_review_date" {
  description = "UTC YYYY-MM-DD reminder for reviewing retained bootstrap resources; no deletion is automated."
  type        = string

  validation {
    condition = (
      can(regex("^20[0-9]{2}-(0[1-9]|1[0-2])-([0-2][0-9]|3[01])$", var.bootstrap_review_date)) &&
      can(timecmp("${var.bootstrap_review_date}T00:00:00Z", "2000-01-01T00:00:00Z"))
    )
    error_message = "bootstrap_review_date must use UTC YYYY-MM-DD form."
  }
}

variable "github_repository" {
  description = "Exact case-sensitive GitHub owner/repository used in OIDC subject claims."
  type        = string

  validation {
    condition     = can(regex("^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$", var.github_repository))
    error_message = "github_repository must have exact owner/repository form."
  }
}

variable "github_repository_owner_id" {
  description = "Immutable numeric GitHub owner ID paired with github_repository."
  type        = string

  validation {
    condition     = can(regex("^[1-9][0-9]{0,19}$", var.github_repository_owner_id))
    error_message = "github_repository_owner_id must be a non-zero numeric GitHub owner ID."
  }
}

variable "github_repository_id" {
  description = "Immutable numeric GitHub repository ID paired with github_repository."
  type        = string

  validation {
    condition     = can(regex("^[1-9][0-9]{0,19}$", var.github_repository_id))
    error_message = "github_repository_id must be a non-zero numeric GitHub repository ID."
  }
}

variable "deployment_governance_mode" {
  description = "Explicit human-governance contract; solo mode is not separation of duties."
  type        = string
  default     = "team_protected"

  validation {
    condition     = contains(["team_protected", "solo_portfolio"], var.deployment_governance_mode)
    error_message = "deployment_governance_mode must be team_protected or solo_portfolio."
  }
}

variable "github_oidc_use_immutable_subject" {
  description = "Must exactly match the repository OIDC template use_immutable_subject setting."
  type        = bool
  default     = true
}

variable "github_allowed_ref" {
  description = "Only Git ref allowed in customized GitHub OIDC subjects."
  type        = string
  default     = "refs/heads/main"

  validation {
    condition     = var.github_allowed_ref == "refs/heads/main"
    error_message = "The Phase 09 OIDC contract permits only refs/heads/main."
  }
}

variable "github_plan_environment" {
  description = "Exact protected environment for the read-only trusted plan job."
  type        = string
  default     = "demo-plan"

  validation {
    condition     = var.github_plan_environment == "demo-plan"
    error_message = "The plan OIDC subject is pinned to the protected demo-plan environment."
  }
}

variable "github_deploy_environment" {
  description = "Exact protected GitHub environment allowed to deploy."
  type        = string
  default     = "demo"

  validation {
    condition     = var.github_deploy_environment == "demo"
    error_message = "The deploy OIDC subject is pinned to the protected demo environment."
  }
}

variable "github_destroy_environment" {
  description = "Exact separately protected GitHub environment allowed to destroy."
  type        = string
  default     = "demo-destroy"

  validation {
    condition     = var.github_destroy_environment == "demo-destroy"
    error_message = "The destroy OIDC subject is pinned to the protected demo-destroy environment."
  }
}

variable "github_plan_workflow_path" {
  description = "Exact workflow path allowed to assume the CI plan role."
  type        = string
  default     = ".github/workflows/terraform-plan.yml"

  validation {
    condition     = var.github_plan_workflow_path == ".github/workflows/terraform-plan.yml"
    error_message = "The plan role is pinned to .github/workflows/terraform-plan.yml."
  }
}

variable "github_deploy_workflow_path" {
  description = "Exact caller workflow path allowed to assume the deploy role."
  type        = string
  default     = ".github/workflows/deploy-demo.yml"

  validation {
    condition     = var.github_deploy_workflow_path == ".github/workflows/deploy-demo.yml"
    error_message = "The deploy role is pinned to .github/workflows/deploy-demo.yml."
  }
}

variable "github_publish_workflow_path" {
  description = "Exact directly dispatched image-publish workflow allowed to assume the deploy role."
  type        = string
  default     = ".github/workflows/publish-images.yml"

  validation {
    condition     = var.github_publish_workflow_path == ".github/workflows/publish-images.yml"
    error_message = "The deploy role is pinned to .github/workflows/publish-images.yml."
  }
}

variable "github_destroy_workflow_path" {
  description = "Exact protected destroy workflow path allowed to assume the deploy role."
  type        = string
  default     = ".github/workflows/destroy-demo.yml"

  validation {
    condition     = var.github_destroy_workflow_path == ".github/workflows/destroy-demo.yml"
    error_message = "The protected destroy subject is pinned to .github/workflows/destroy-demo.yml."
  }
}

variable "github_rollback_workflow_path" {
  description = "Exact protected manual rollback workflow path allowed to assume the deploy role."
  type        = string
  default     = ".github/workflows/rollback-demo.yml"

  validation {
    condition     = var.github_rollback_workflow_path == ".github/workflows/rollback-demo.yml"
    error_message = "The rollback subject is pinned to .github/workflows/rollback-demo.yml."
  }
}

variable "state_backend_key" {
  description = "Exact disposable demo backend key used in state and saved-plan guards."
  type        = string
  default     = "modelguard-ai/demo/terraform.tfstate"

  validation {
    condition     = var.state_backend_key == "modelguard-ai/demo/terraform.tfstate"
    error_message = "state_backend_key is fixed to modelguard-ai/demo/terraform.tfstate."
  }
}

variable "state_noncurrent_retention_days" {
  description = "Finite retention for noncurrent state and lock-object versions."
  type        = number
  default     = 90

  validation {
    condition     = var.state_noncurrent_retention_days >= 30 && var.state_noncurrent_retention_days <= 365
    error_message = "state_noncurrent_retention_days must be between 30 and 365."
  }
}

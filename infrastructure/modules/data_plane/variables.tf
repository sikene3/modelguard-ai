variable "buckets" {
  description = "Private demo buckets keyed by models, predictions, reports, and audit."
  type = map(object({
    name                    = string
    expiration_days         = number
    noncurrent_expiration   = number
    receives_access_logging = bool
  }))

  validation {
    condition = (
      toset(keys(var.buckets)) == toset(["models", "predictions", "reports", "audit"]) &&
      alltrue([for bucket in values(var.buckets) : can(regex("^[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$", bucket.name))]) &&
      alltrue([for bucket in values(var.buckets) : bucket.expiration_days >= 7 && bucket.expiration_days <= 90]) &&
      alltrue([for bucket in values(var.buckets) : bucket.noncurrent_expiration >= 1 && bucket.noncurrent_expiration <= bucket.expiration_days])
    )
    error_message = "buckets must define the four exact private stores with bounded lifecycle values."
  }
}

variable "ecr_repository_names" {
  description = "Immutable ECR repositories keyed by api, dashboard, and monitor."
  type        = map(string)

  validation {
    condition = (
      toset(keys(var.ecr_repository_names)) == toset(["api", "dashboard", "monitor"]) &&
      alltrue([for name in values(var.ecr_repository_names) : can(regex("^[a-z0-9][a-z0-9._/-]{1,255}$", name))])
    )
    error_message = "ecr_repository_names must define api, dashboard, and monitor."
  }
}

variable "account_id" {
  description = "Expected AWS account ID used to scope delivery policies."
  type        = string

  validation {
    condition     = can(regex("^[0-9]{12}$", var.account_id))
    error_message = "account_id must contain exactly 12 digits."
  }
}

variable "region" {
  description = "Expected AWS Region used to scope ALB log delivery."
  type        = string
}

variable "alb_log_prefix" {
  description = "Relative prefix for ALB logs in the audit bucket."
  type        = string
  default     = "alb"

  validation {
    condition     = can(regex("^[a-z0-9][a-z0-9/-]*[a-z0-9]$", var.alb_log_prefix))
    error_message = "alb_log_prefix must be a non-empty relative prefix."
  }
}

variable "tags" {
  description = "Required common resource tags."
  type        = map(string)
}

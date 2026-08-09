variable "aws_account_id" {
  description = "Exact standalone account receiving the retained audit prerequisite."
  type        = string

  validation {
    condition     = can(regex("^[0-9]{12}$", var.aws_account_id))
    error_message = "aws_account_id must contain exactly 12 digits."
  }
}

variable "aws_region" {
  description = "Single canonical ModelGuard Region."
  type        = string
  default     = "us-east-1"

  validation {
    condition     = var.aws_region == "us-east-1"
    error_message = "The retained audit prerequisite is pinned to us-east-1."
  }
}

variable "owner_tag" {
  description = "Non-sensitive operator label; never an email address."
  type        = string

  validation {
    condition     = can(regex("^[A-Za-z0-9._-]{2,64}$", var.owner_tag)) && !strcontains(var.owner_tag, "@")
    error_message = "owner_tag must be a short non-email identifier."
  }
}

variable "review_date" {
  description = "UTC YYYY-MM-DD reminder for reviewing retained audit resources."
  type        = string

  validation {
    condition = (
      can(regex("^20[0-9]{2}-(0[1-9]|1[0-2])-([0-2][0-9]|3[01])$", var.review_date)) &&
      can(timecmp("${var.review_date}T00:00:00Z", "2000-01-01T00:00:00Z"))
    )
    error_message = "review_date must use UTC YYYY-MM-DD form."
  }
}

variable "current_log_retention_days" {
  description = "Finite current CloudTrail object retention; expiration is a deliberate recovery limit."
  type        = number
  default     = 365

  validation {
    condition     = var.current_log_retention_days >= 90 && var.current_log_retention_days <= 2555
    error_message = "current_log_retention_days must be between 90 and 2555."
  }
}

variable "noncurrent_log_retention_days" {
  description = "Finite retention for superseded CloudTrail object versions."
  type        = number
  default     = 90

  validation {
    condition     = var.noncurrent_log_retention_days >= 30 && var.noncurrent_log_retention_days <= 365
    error_message = "noncurrent_log_retention_days must be between 30 and 365."
  }
}

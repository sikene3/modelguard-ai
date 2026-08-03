variable "name_prefix" {
  description = "Deterministic project/environment prefix used for names."
  type        = string

  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{2,40}$", var.name_prefix))
    error_message = "name_prefix must be a lowercase AWS-safe name."
  }
}

variable "vpc_cidr" {
  description = "Canonical private IPv4 CIDR for the demo VPC."
  type        = string

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

variable "availability_zones" {
  description = "Exactly two distinct availability zones in the selected Region."
  type        = list(string)

  validation {
    condition     = length(var.availability_zones) == 2 && length(distinct(var.availability_zones)) == 2
    error_message = "Exactly two distinct availability zones are required."
  }
}

variable "public_subnet_cidrs" {
  description = "Two public ALB subnet CIDRs, ordered like availability_zones."
  type        = list(string)

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
    error_message = "Exactly two distinct canonical public IPv4 subnet CIDRs are required."
  }
}

variable "private_subnet_cidrs" {
  description = "Two private ECS subnet CIDRs, ordered like availability_zones."
  type        = list(string)

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
    error_message = "Exactly two distinct canonical private IPv4 subnet CIDRs are required."
  }
}

variable "alb_allowed_cidr" {
  description = "Explicit restricted IPv4 source CIDR allowed to reach the public ALB."
  type        = string

  validation {
    condition = (
      can(cidrnetmask(var.alb_allowed_cidr)) &&
      try(cidrhost(var.alb_allowed_cidr, 0) == split("/", var.alb_allowed_cidr)[0], false) &&
      !strcontains(var.alb_allowed_cidr, ":") &&
      !contains(["0.0.0.0/0", "::/0"], var.alb_allowed_cidr)
    )
    error_message = "alb_allowed_cidr must be a valid restricted IPv4 CIDR; world CIDRs are forbidden."
  }
}

variable "access_mode" {
  description = "Public transport mode; HTTPS adds a restricted 443 rule while port 80 only redirects."
  type        = string

  validation {
    condition     = contains(["https_token", "http_cidr_only"], var.access_mode)
    error_message = "access_mode must be https_token or http_cidr_only."
  }
}

variable "s3_bucket_arns" {
  description = "Exact demo S3 bucket ARNs allowed through the gateway endpoint."
  type        = set(string)

  validation {
    condition     = length(var.s3_bucket_arns) >= 3 && alltrue([for arn in var.s3_bucket_arns : can(regex("^arn:[^:]+:s3:::[a-z0-9.-]+$", arn))])
    error_message = "s3_bucket_arns must contain the exact private demo bucket ARNs."
  }
}

variable "tags" {
  description = "Required common resource tags."
  type        = map(string)
}

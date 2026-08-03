module "data_plane" {
  source = "../../modules/data_plane"

  buckets              = local.bucket_definitions
  ecr_repository_names = local.ecr_repository_names
  account_id           = var.aws_account_id
  region               = var.aws_region
  alb_log_prefix       = "alb"
  alb_name             = local.name_prefix
  tags                 = local.common_tags
}

module "network" {
  source = "../../modules/network"

  name_prefix          = local.name_prefix
  vpc_cidr             = var.vpc_cidr
  availability_zones   = var.availability_zones
  public_subnet_cidrs  = var.public_subnet_cidrs
  private_subnet_cidrs = var.private_subnet_cidrs
  alb_allowed_cidr     = var.alb_allowed_cidr
  access_mode          = var.api_access_mode
  s3_bucket_arns       = toset(values(local.bucket_arns))
  tags                 = local.common_tags
}

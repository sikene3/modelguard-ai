locals {
  public_subnets = {
    for index, zone in var.availability_zones : zone => {
      cidr  = var.public_subnet_cidrs[index]
      index = index
    }
  }
  private_subnets = {
    for index, zone in var.availability_zones : zone => {
      cidr  = var.private_subnet_cidrs[index]
      index = index
    }
  }
  s3_object_arns       = toset([for arn in var.s3_bucket_arns : "${arn}/*"])
  ecr_layer_bucket_arn = "arn:${data.aws_partition.current.partition}:s3:::prod-${data.aws_region.current.region}-starport-layer-bucket"
}

resource "aws_vpc" "this" {
  # checkov:skip=CKV2_AWS_11:Short-lived synthetic demo omits paid VPC Flow Logs; ALB, application, and native service logs cover this evidence boundary.

  cidr_block           = var.vpc_cidr
  enable_dns_hostnames = true
  enable_dns_support   = true
  instance_tenancy     = "default"

  tags = merge(var.tags, { Name = "${var.name_prefix}-vpc" })
}

resource "aws_default_security_group" "restricted" {
  vpc_id = aws_vpc.this.id

  tags = merge(var.tags, { Name = "${var.name_prefix}-default-deny" })
}

resource "aws_internet_gateway" "this" {
  vpc_id = aws_vpc.this.id

  tags = merge(var.tags, { Name = "${var.name_prefix}-igw" })
}

resource "aws_subnet" "public" {
  for_each = local.public_subnets

  vpc_id                  = aws_vpc.this.id
  availability_zone       = each.key
  cidr_block              = each.value.cidr
  map_public_ip_on_launch = false

  tags = merge(var.tags, {
    Name = "${var.name_prefix}-public-${each.value.index + 1}"
    Tier = "public-alb"
  })
}

resource "aws_subnet" "private" {
  for_each = local.private_subnets

  vpc_id                  = aws_vpc.this.id
  availability_zone       = each.key
  cidr_block              = each.value.cidr
  map_public_ip_on_launch = false

  tags = merge(var.tags, {
    Name = "${var.name_prefix}-private-${each.value.index + 1}"
    Tier = "private-ecs"
  })
}

resource "aws_route_table" "public" {
  vpc_id = aws_vpc.this.id

  tags = merge(var.tags, { Name = "${var.name_prefix}-public" })
}

resource "aws_route" "public_ipv4" {
  route_table_id         = aws_route_table.public.id
  destination_cidr_block = "0.0.0.0/0"
  gateway_id             = aws_internet_gateway.this.id
}

resource "aws_route_table_association" "public" {
  for_each = aws_subnet.public

  subnet_id      = each.value.id
  route_table_id = aws_route_table.public.id
}

resource "aws_eip" "nat" {
  domain = "vpc"

  depends_on = [aws_internet_gateway.this]

  tags = merge(var.tags, { Name = "${var.name_prefix}-nat" })
}

# This single NAT is an intentional, documented non-HA and cost-saving MVP choice.
resource "aws_nat_gateway" "this" {
  allocation_id     = aws_eip.nat.id
  subnet_id         = aws_subnet.public[var.availability_zones[0]].id
  connectivity_type = "public"

  tags = merge(var.tags, { Name = "${var.name_prefix}-nat" })

  depends_on = [aws_internet_gateway.this]
}

resource "aws_route_table" "private" {
  vpc_id = aws_vpc.this.id

  tags = merge(var.tags, { Name = "${var.name_prefix}-private" })
}

resource "aws_route" "private_ipv4" {
  route_table_id         = aws_route_table.private.id
  destination_cidr_block = "0.0.0.0/0"
  nat_gateway_id         = aws_nat_gateway.this.id
}

resource "aws_route_table_association" "private" {
  for_each = aws_subnet.private

  subnet_id      = each.value.id
  route_table_id = aws_route_table.private.id
}

resource "aws_vpc_endpoint" "s3" {
  vpc_id            = aws_vpc.this.id
  service_name      = "com.amazonaws.${data.aws_region.current.region}.s3"
  vpc_endpoint_type = "Gateway"
  route_table_ids   = [aws_route_table.private.id]

  # Principal must be "*" in a gateway-endpoint policy. Exact bucket resources here and the
  # workload identity policies provide the effective least-privilege boundary.
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid       = "DemoBucketsOnly"
        Effect    = "Allow"
        Principal = "*"
        Action = [
          "s3:AbortMultipartUpload",
          "s3:GetBucketLocation",
          "s3:GetObject",
          "s3:GetObjectVersion",
          "s3:ListBucket",
          "s3:ListBucketMultipartUploads",
          "s3:ListMultipartUploadParts",
          "s3:PutObject",
        ]
        Resource = concat(tolist(var.s3_bucket_arns), tolist(local.s3_object_arns))
      },
      {
        Sid       = "EcrLayerDownloadsOnly"
        Effect    = "Allow"
        Principal = "*"
        Action    = ["s3:GetObject"]
        Resource  = ["${local.ecr_layer_bucket_arn}/*"]
      },
    ]
  })

  tags = merge(var.tags, { Name = "${var.name_prefix}-s3" })
}

data "aws_partition" "current" {}
data "aws_region" "current" {}

resource "aws_security_group" "alb" {
  name        = "${var.name_prefix}-alb"
  description = "Restricted public ingress to the demo ALB"
  vpc_id      = aws_vpc.this.id

  tags = merge(var.tags, { Name = "${var.name_prefix}-alb" })
}

resource "aws_vpc_security_group_ingress_rule" "alb_http" {
  security_group_id = aws_security_group.alb.id
  description       = "Restricted HTTP demo traffic or HTTPS redirect"
  cidr_ipv4         = var.alb_allowed_cidr
  from_port         = 80
  to_port           = 80
  ip_protocol       = "tcp"
}

resource "aws_vpc_security_group_ingress_rule" "alb_https" {
  count = var.access_mode == "https_token" ? 1 : 0

  security_group_id = aws_security_group.alb.id
  description       = "Restricted HTTPS token-mode traffic"
  cidr_ipv4         = var.alb_allowed_cidr
  from_port         = 443
  to_port           = 443
  ip_protocol       = "tcp"
}

resource "aws_security_group" "api" {
  # checkov:skip=CKV2_AWS_5:Checkov cannot trace this module output into the API ECS service network configuration; the Phase 08 static test does.

  name        = "${var.name_prefix}-api"
  description = "API task ingress only from the ALB"
  vpc_id      = aws_vpc.this.id

  tags = merge(var.tags, { Name = "${var.name_prefix}-api" })
}

resource "aws_security_group" "dashboard" {
  # checkov:skip=CKV2_AWS_5:Checkov cannot trace this module output into the dashboard ECS service network configuration; the Phase 08 static test does.

  name        = "${var.name_prefix}-dashboard"
  description = "Dashboard task ingress only from the ALB"
  vpc_id      = aws_vpc.this.id

  tags = merge(var.tags, { Name = "${var.name_prefix}-dashboard" })
}

resource "aws_security_group" "monitor" {
  # checkov:skip=CKV2_AWS_5:Checkov cannot trace this module output into the Scheduler ECS network configuration; the Phase 08 static test does.

  name        = "${var.name_prefix}-monitor"
  description = "One-shot monitor task with no inbound rules"
  vpc_id      = aws_vpc.this.id

  tags = merge(var.tags, { Name = "${var.name_prefix}-monitor" })
}

resource "aws_vpc_security_group_ingress_rule" "api_from_alb" {
  security_group_id            = aws_security_group.api.id
  description                  = "ALB to API container port only"
  referenced_security_group_id = aws_security_group.alb.id
  from_port                    = 8000
  to_port                      = 8000
  ip_protocol                  = "tcp"
}

resource "aws_vpc_security_group_ingress_rule" "dashboard_from_alb" {
  security_group_id            = aws_security_group.dashboard.id
  description                  = "ALB to dashboard container port only"
  referenced_security_group_id = aws_security_group.alb.id
  from_port                    = 8501
  to_port                      = 8501
  ip_protocol                  = "tcp"
}

resource "aws_vpc_security_group_egress_rule" "alb_to_api" {
  security_group_id            = aws_security_group.alb.id
  description                  = "ALB to API target port"
  referenced_security_group_id = aws_security_group.api.id
  from_port                    = 8000
  to_port                      = 8000
  ip_protocol                  = "tcp"
}

resource "aws_vpc_security_group_egress_rule" "alb_to_dashboard" {
  security_group_id            = aws_security_group.alb.id
  description                  = "ALB to dashboard target port"
  referenced_security_group_id = aws_security_group.dashboard.id
  from_port                    = 8501
  to_port                      = 8501
  ip_protocol                  = "tcp"
}

locals {
  task_security_groups = {
    api       = aws_security_group.api.id
    dashboard = aws_security_group.dashboard.id
    monitor   = aws_security_group.monitor.id
  }
}

# Required HTTPS access to AWS APIs and ECR traverses the single NAT. S3 routes through the gateway
# endpoint. This 443-only egress is the explicitly accepted Phase 08 MVP exception.
resource "aws_vpc_security_group_egress_rule" "task_https" {
  for_each = local.task_security_groups

  # checkov:skip=CKV_AWS_382:Required 443-only AWS/ECR egress through the documented single-NAT MVP path.

  security_group_id = each.value
  description       = "HTTPS to AWS services through S3 endpoint or single NAT"
  cidr_ipv4         = "0.0.0.0/0"
  from_port         = 443
  to_port           = 443
  ip_protocol       = "tcp"
}

resource "aws_vpc_security_group_egress_rule" "task_dns_udp" {
  for_each = local.task_security_groups

  security_group_id = each.value
  description       = "DNS resolution inside the VPC"
  cidr_ipv4         = var.vpc_cidr
  from_port         = 53
  to_port           = 53
  ip_protocol       = "udp"
}

resource "aws_vpc_security_group_egress_rule" "task_dns_tcp" {
  for_each = local.task_security_groups

  security_group_id = each.value
  description       = "TCP DNS fallback inside the VPC"
  cidr_ipv4         = var.vpc_cidr
  from_port         = 53
  to_port           = 53
  ip_protocol       = "tcp"
}

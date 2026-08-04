resource "aws_lb" "this" {
  # checkov:skip=CKV_AWS_150:Deletion protection conflicts with the explicitly temporary, saved-plan and inventory-verified destroy contract. [owner=modelguard-maintainers; expires=2026-10-31]
  # checkov:skip=CKV2_AWS_20:The conditional synthetic-only HTTP mode intentionally forwards rather than redirects; preferred https_token mode creates the HTTPS redirect. [owner=modelguard-maintainers; expires=2026-10-31]
  # checkov:skip=CKV2_AWS_28:A WAF is disproportionate for a short-lived synthetic demo already restricted to one explicit non-world source CIDR. [owner=modelguard-maintainers; expires=2026-10-31]

  name               = local.name_prefix
  internal           = false
  load_balancer_type = "application"
  security_groups    = [module.network.alb_security_group_id]
  subnets            = module.network.public_subnet_ids

  enable_deletion_protection = false
  drop_invalid_header_fields = true
  desync_mitigation_mode     = "strictest"
  enable_http2               = true
  enable_waf_fail_open       = false
  idle_timeout               = 60

  access_logs {
    bucket  = module.data_plane.audit_bucket_name
    prefix  = "alb"
    enabled = true
  }

  tags = merge(local.common_tags, { Name = local.name_prefix })

  depends_on = [module.data_plane]
}

resource "aws_lb_target_group" "api" {
  # checkov:skip=CKV_AWS_378:TLS terminates at the ALB; this private hop is restricted from the ALB security group to the exact API port. [owner=modelguard-maintainers; expires=2026-10-31]

  name        = "${local.name_prefix}-api"
  port        = 8000
  protocol    = "HTTP"
  target_type = "ip"
  vpc_id      = module.network.vpc_id

  deregistration_delay = 30

  health_check {
    enabled             = true
    path                = "/health/ready"
    protocol            = "HTTP"
    port                = "traffic-port"
    matcher             = "200"
    interval            = 30
    timeout             = 5
    healthy_threshold   = 2
    unhealthy_threshold = 2
  }

  tags = merge(local.common_tags, { Name = "${local.name_prefix}-api", Component = "api" })
}

resource "aws_lb_target_group" "dashboard" {
  # checkov:skip=CKV_AWS_378:TLS terminates at the ALB; this private hop is restricted from the ALB security group to the exact dashboard port. [owner=modelguard-maintainers; expires=2026-10-31]

  name        = "${local.name_prefix}-dashboard"
  port        = 8501
  protocol    = "HTTP"
  target_type = "ip"
  vpc_id      = module.network.vpc_id

  deregistration_delay = 30

  health_check {
    enabled             = true
    path                = "/_stcore/health"
    protocol            = "HTTP"
    port                = "traffic-port"
    matcher             = "200"
    interval            = 30
    timeout             = 5
    healthy_threshold   = 2
    unhealthy_threshold = 2
  }

  tags = merge(local.common_tags, { Name = "${local.name_prefix}-dashboard", Component = "dashboard" })
}

# The HTTP fallback is intentionally restricted and synthetic-only. It sends no reusable token.
resource "aws_lb_listener" "http_demo" {
  # checkov:skip=CKV_AWS_2:This listener exists only for the documented CIDR-only synthetic HTTP fallback; preferred mode uses HTTPS and sends no token over HTTP. [owner=modelguard-maintainers; expires=2026-10-31]
  # checkov:skip=CKV_AWS_103:TLS policy is inapplicable to the disclosed token-free HTTP fallback; the HTTPS listener enforces TLS 1.2 or newer. [owner=modelguard-maintainers; expires=2026-10-31]

  count = var.api_access_mode == "http_cidr_only" ? 1 : 0

  load_balancer_arn = aws_lb.this.arn
  port              = 80
  protocol          = "HTTP"

  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.dashboard.arn
  }

  tags = merge(local.common_tags, { Name = "${local.name_prefix}-http-demo" })
}

resource "aws_lb_listener" "http_redirect" {
  count = var.api_access_mode == "https_token" ? 1 : 0

  load_balancer_arn = aws_lb.this.arn
  port              = 80
  protocol          = "HTTP"

  default_action {
    type = "redirect"

    redirect {
      port        = "443"
      protocol    = "HTTPS"
      status_code = "HTTP_301"
    }
  }

  tags = merge(local.common_tags, { Name = "${local.name_prefix}-https-redirect" })
}

resource "aws_lb_listener" "https" {
  count = var.api_access_mode == "https_token" ? 1 : 0

  load_balancer_arn = aws_lb.this.arn
  port              = 443
  protocol          = "HTTPS"
  certificate_arn   = var.acm_certificate_arn
  ssl_policy        = "ELBSecurityPolicy-TLS13-1-2-2021-06"

  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.dashboard.arn
  }

  tags = merge(local.common_tags, { Name = "${local.name_prefix}-https" })
}

locals {
  application_listener_arn = (
    var.api_access_mode == "https_token" ?
    aws_lb_listener.https[0].arn :
    aws_lb_listener.http_demo[0].arn
  )
}

# /metrics remains a local/test Prometheus surface and is never forwarded publicly in AWS.
resource "aws_lb_listener_rule" "block_metrics" {
  listener_arn = local.application_listener_arn
  priority     = 1

  action {
    type = "fixed-response"

    fixed_response {
      content_type = "application/json"
      message_body = "{\"code\":\"not_found\"}"
      status_code  = "404"
    }
  }

  condition {
    path_pattern {
      values = ["/metrics", "/metrics/*"]
    }
  }

  tags = merge(local.common_tags, { Name = "${local.name_prefix}-block-metrics" })
}

# Health/version routes remain token-exempt at the application boundary. Only POST /v1/predict
# checks the bearer token in https_token mode.
resource "aws_lb_listener_rule" "api" {
  listener_arn = local.application_listener_arn
  priority     = 10

  action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.api.arn
  }

  condition {
    path_pattern {
      values = [
        "/health/live",
        "/health/ready",
        "/v1/predict",
        "/version",
      ]
    }
  }

  tags = merge(local.common_tags, { Name = "${local.name_prefix}-api-routes" })
}

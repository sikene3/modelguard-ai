output "vpc_id" {
  description = "Demo VPC ID."
  value       = aws_vpc.this.id
}

output "public_subnet_ids" {
  description = "Public ALB subnet IDs in the requested AZ order."
  value       = [for zone in var.availability_zones : aws_subnet.public[zone].id]
}

output "private_subnet_ids" {
  description = "Private ECS subnet IDs in the requested AZ order."
  value       = [for zone in var.availability_zones : aws_subnet.private[zone].id]
}

output "alb_security_group_id" {
  description = "ALB security group ID."
  value       = aws_security_group.alb.id
}

output "api_security_group_id" {
  description = "API task security group ID."
  value       = aws_security_group.api.id
}

output "dashboard_security_group_id" {
  description = "Dashboard task security group ID."
  value       = aws_security_group.dashboard.id
}

output "monitor_security_group_id" {
  description = "Monitor task security group ID."
  value       = aws_security_group.monitor.id
}

output "nat_gateway_id" {
  description = "The single intentionally non-HA NAT gateway ID."
  value       = aws_nat_gateway.this.id
}

output "s3_vpc_endpoint_id" {
  description = "S3 gateway endpoint ID."
  value       = aws_vpc_endpoint.s3.id
}

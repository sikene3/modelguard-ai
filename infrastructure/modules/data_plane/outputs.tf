output "bucket_names" {
  description = "Private bucket names keyed by data role."
  value       = { for key, bucket in aws_s3_bucket.this : key => bucket.id }
}

output "bucket_arns" {
  description = "Private bucket ARNs keyed by data role."
  value       = { for key, bucket in aws_s3_bucket.this : key => bucket.arn }
}

output "ecr_repository_urls" {
  description = "ECR repository URLs keyed by component."
  value       = { for key, repository in aws_ecr_repository.this : key => repository.repository_url }
}

output "ecr_repository_arns" {
  description = "ECR repository ARNs keyed by component."
  value       = { for key, repository in aws_ecr_repository.this : key => repository.arn }
}

output "audit_bucket_name" {
  description = "Audit/access-log bucket name."
  value       = aws_s3_bucket.this["audit"].id
}

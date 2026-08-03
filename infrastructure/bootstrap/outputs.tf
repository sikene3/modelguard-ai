output "state_bucket_name" {
  description = "Retained encrypted/versioned remote-state bucket."
  value       = aws_s3_bucket.state.id
}

output "state_kms_key_arn" {
  description = "Retained KMS key ARN for S3 backend configuration."
  value       = aws_kms_key.state.arn
}

output "state_backend_key" {
  description = "Exact guarded disposable-demo state key."
  value       = var.state_backend_key
}

output "permission_boundary_arn" {
  description = "Mandatory boundary for every demo workload role."
  value       = aws_iam_policy.workload_boundary.arn
}

output "ci_plan_role_arn" {
  description = "OIDC role restricted to the exact protected main ref and read-only plan operations."
  value       = aws_iam_role.ci_plan.arn
}

output "ci_deploy_role_arn" {
  description = "OIDC role restricted to the exact protected deploy/destroy environments."
  value       = aws_iam_role.ci_deploy.arn
}

output "github_oidc_subjects" {
  description = "Non-secret exact OIDC subjects for human review."
  value = {
    plan    = local.plan_subject
    deploy  = local.deploy_subjects[0]
    destroy = local.deploy_subjects[1]
  }
}

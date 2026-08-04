output "state_bucket_name" {
  description = "Retained encrypted/versioned remote-state bucket."
  value       = aws_s3_bucket.state.id
}

output "state_kms_key_arn" {
  description = "Retained KMS key ARN for S3 backend and exact-context SNS encryption."
  value       = aws_kms_key.state.arn
}

output "alert_kms_key_arn" {
  description = "Same retained key ARN, restricted by exact SNS encryption context for alerts."
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
  description = "OIDC role restricted to the exact customized plan subject and read-only operations."
  value       = aws_iam_role.ci_plan.arn
}

output "ci_deploy_role_arn" {
  description = "OIDC role restricted to exact customized deploy/publish/destroy subjects."
  value       = aws_iam_role.ci_deploy.arn
}

output "github_oidc_subjects" {
  description = "Non-secret exact OIDC subjects for human review."
  value = {
    plan    = local.plan_subject
    deploy  = local.deploy_subjects.deploy
    publish = local.deploy_subjects.publish
    destroy = local.deploy_subjects.destroy
  }
}

output "github_oidc_customization" {
  description = "Repository-level GitHub OIDC subject template that must match these IAM trusts."
  value = {
    use_default           = false
    use_immutable_subject = var.github_oidc_use_immutable_subject
    include_claim_keys    = ["repo", "ref", "environment", "workflow_ref"]
  }
}

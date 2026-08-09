output "audit_trail_contract" {
  description = "Non-secret exact retained trail and narrowly audited state prefix."
  value = {
    trail_name        = aws_cloudtrail.terraform_state_data_events.name
    region            = var.aws_region
    state_bucket_name = local.state_bucket_name
    state_object_keys = [
      "modelguard-ai/demo/terraform.tfstate",
      "modelguard-ai/demo/terraform.tfstate.tflock",
    ]
    log_bucket_name = aws_s3_bucket.audit.id
    log_kms_alias   = aws_kms_alias.audit.name
    prevent_destroy = true
  }
}

# Model promotion, not Terraform, owns pointer values after these locations are created. The initial
# sentinel cannot be mistaken for a model identity. Later values contain exact semantic version,
# manifest SHA-256, bundle prefix, and every S3 VersionId.
resource "aws_ssm_parameter" "active_model" {
  # checkov:skip=CKV2_AWS_34:This pointer is public integrity metadata, not a credential; String avoids misleading secret/decryption semantics.

  name        = "/${var.project_name}/${var.environment}/models/active"
  description = "Promotion-owned exact active model identity and versioned bundle pointer"
  type        = "String"
  value       = local.unset_pointer
  tier        = "Standard"

  tags = merge(local.common_tags, { Name = "${local.name_prefix}-active-model" })

  lifecycle {
    ignore_changes = [value]
  }
}

resource "aws_ssm_parameter" "previous_model" {
  # checkov:skip=CKV2_AWS_34:This pointer is public integrity metadata, not a credential; String avoids misleading secret/decryption semantics.

  name        = "/${var.project_name}/${var.environment}/models/previous"
  description = "Promotion-owned exact previous model identity and versioned bundle pointer"
  type        = "String"
  value       = local.unset_pointer
  tier        = "Standard"

  tags = merge(local.common_tags, { Name = "${local.name_prefix}-previous-model" })

  lifecycle {
    ignore_changes = [value]
  }
}

# Reading the non-secret active pointer only during activation makes the second plan prove that the
# sentinel was replaced. Terraform deliberately never reads the SecureString token value.
data "aws_ssm_parameter" "active_current" {
  count = var.activate_services ? 1 : 0

  name            = aws_ssm_parameter.active_model.name
  with_decryption = false
}

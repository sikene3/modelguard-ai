resource "aws_budgets_budget" "demo" {
  account_id   = var.aws_account_id
  name         = "${local.name_prefix}-monthly"
  budget_type  = "COST"
  limit_amount = tostring(var.budget_limit_usd)
  limit_unit   = "USD"
  time_unit    = "MONTHLY"

  cost_filter {
    name   = "TagKeyValue"
    values = [format("user:Project$%s", var.project_name)]
  }

  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 80
    threshold_type             = "PERCENTAGE"
    notification_type          = "ACTUAL"
    subscriber_email_addresses = [var.budget_notification_email]
  }

  tags = merge(local.common_tags, { Name = "${local.name_prefix}-monthly" })

  lifecycle {
    precondition {
      condition = (
        var.budget_notification_confirmed &&
        can(regex("^[^@[:space:]]+@[^@[:space:]]+\\.[^@[:space:]]+$", var.budget_notification_email)) &&
        !endswith(lower(var.budget_notification_email), ".invalid")
      )
      error_message = "Budget creation requires a confirmed human recipient from a Git-ignored tfvars file."
    }
  }
}

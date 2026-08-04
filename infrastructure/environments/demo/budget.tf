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

  tags = merge(local.common_tags, { Name = "${local.name_prefix}-monthly" })

  # Terraform carries only the non-secret topic ARN. The topic's email subscriber is enrolled
  # interactively outside Terraform so no address can enter state or a saved plan.
  notification {
    comparison_operator       = "GREATER_THAN"
    threshold                 = 80
    threshold_type            = "PERCENTAGE"
    notification_type         = "ACTUAL"
    subscriber_sns_topic_arns = [aws_sns_topic.alerts.arn]
  }

  depends_on = [aws_sns_topic_policy.alerts]
}

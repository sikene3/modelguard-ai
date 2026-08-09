locals {
  required_budget_name = "${local.name_prefix}-monthly"
  required_budget_alerts = [
    "50-percent-actual",
    "80-percent-actual",
    "100-percent-actual",
    "100-percent-forecast",
  ]
}

# The budget and its email notification are a manual retained account prerequisite. Keeping it out
# of this disposable saved plan prevents subscriber PII from entering Terraform state or artifacts.
check "manual_budget_prerequisite" {
  assert {
    condition     = !var.activate_services || var.budget_prerequisite_verified
    error_message = "Activation requires the value-free USD 10 budget preflight to pass."
  }
}

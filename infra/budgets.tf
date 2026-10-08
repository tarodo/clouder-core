# ── Monthly cost budget ───────────────────────────────────────────────────────
# The amount comes from the GitHub secret BUDGET_MONTHLY_LIMIT (the repo is
# public); without it, or without an alarm email, no budget is created.

variable "budget_monthly_limit" {
  description = "Monthly cost budget in USD, e.g. \"50\". Empty = no budget."
  type        = string
  default     = ""
}

resource "aws_budgets_budget" "monthly" {
  count = var.budget_monthly_limit != "" && var.alarm_email != "" ? 1 : 0

  name         = "${local.name_prefix}-monthly"
  budget_type  = "COST"
  limit_amount = var.budget_monthly_limit
  limit_unit   = "USD"
  time_unit    = "MONTHLY"

  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 80
    threshold_type             = "PERCENTAGE"
    notification_type          = "ACTUAL"
    subscriber_email_addresses = [var.alarm_email]
  }

  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 100
    threshold_type             = "PERCENTAGE"
    notification_type          = "FORECASTED"
    subscriber_email_addresses = [var.alarm_email]
  }
}

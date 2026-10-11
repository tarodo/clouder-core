# ── Lambda concurrency: the account quota and who may use it ──
# A new account gets 10 concurrent executions, shared by every function. On 2026-10-11
# a triage finalize fanned out into ~240 enrichment jobs that took all 10, and the API
# answered 5xx (docs/postmortems/2026-10-11-api-throttled-by-worker-burst.md). The
# quota is requested here; every SQS worker is capped (lambda.tf) and a test keeps the
# caps plus room for the API under it (tests/unit/test_concurrency_infra.py).
locals {
  lambda_concurrency_quota = 100
}

# Creating it files one increase request when the account is below the value. After that
# Terraform leaves it alone: an approval above the value would otherwise plan a decrease
# on every deploy, and a denial would file a new request each time. To ask for more,
# change the local and apply with -replace. Destroying it changes nothing in AWS.
resource "aws_servicequotas_service_quota" "lambda_concurrency" {
  service_code = "lambda"
  quota_code   = "L-B99A9384" # Concurrent executions
  value        = local.lambda_concurrency_quota

  lifecycle {
    ignore_changes = [value]
  }
}

# The quota the account has now (10 until the request is approved), not the requested one.
data "aws_servicequotas_service_quota" "lambda_concurrency" {
  service_code = "lambda"
  quota_code   = "L-B99A9384"
}

resource "aws_cloudwatch_metric_alarm" "lambda_account_concurrency" {
  alarm_name          = "${local.name_prefix}-lambda-account-concurrency"
  alarm_description   = "Account Lambda concurrency at 80 % of the quota for 3 minutes: workers are about to crowd out the API (docs/ops/runbook.md#api-5xx-or-lambda-throttles)"
  namespace           = "AWS/Lambda"
  metric_name         = "ConcurrentExecutions"
  statistic           = "Maximum"
  period              = 60
  evaluation_periods  = 3
  threshold           = data.aws_servicequotas_service_quota.lambda_concurrency.value * 0.8
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "notBreaching"

  alarm_actions = local.alarm_actions
  ok_actions    = local.alarm_actions
}

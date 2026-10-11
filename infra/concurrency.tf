# ── Lambda concurrency: the account quota and who may use it ──
# A new account gets 10 concurrent executions, shared by every function. On 2026-10-11
# a triage finalize fanned out into ~240 enrichment jobs that took all 10, and the API
# answered 5xx (docs/postmortems/2026-10-11-api-throttled-by-worker-burst.md). Every SQS
# worker is capped (lambda.tf), and a test keeps the caps plus room for the API under the
# quota this account is planned for (tests/unit/test_concurrency_infra.py).
#
# The increase is not requested here: the Service Quotas API refuses values below the
# AWS default (1000), and this account was lowered to 10 — a request for 100 failed the
# 2026-10-11 deploy. It goes through an AWS Support case (docs/ops/runbook.md).
locals {
  lambda_concurrency_quota = 100 # requested through AWS Support; the account has 10 until approved
}

# The quota the account has now, which the alarm below scales with.
data "aws_servicequotas_service_quota" "lambda_concurrency" {
  service_code = "lambda"
  quota_code   = "L-B99A9384" # Concurrent executions
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

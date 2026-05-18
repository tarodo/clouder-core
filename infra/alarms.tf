# ── Lambda groups ────────────────────────────────────────────────
# API-facing Lambdas sit behind API Gateway (29s hard timeout).
# A high p95 here predicts user-visible 503s.
locals {
  api_lambdas = {
    collector       = aws_lambda_function.collector.function_name
    auth_handler    = aws_lambda_function.auth_handler.function_name
    auth_authorizer = aws_lambda_function.auth_authorizer.function_name
    curation        = aws_lambda_function.curation.function_name
  }

  # Async SQS-driven workers. Long durations are expected (timeouts up to
  # 900s for canonicalization / spotify_search). Errors still matter.
  worker_lambdas = {
    canonicalization = aws_lambda_function.canonicalization_worker.function_name
    spotify_search   = aws_lambda_function.spotify_search_worker.function_name
    vendor_match     = aws_lambda_function.vendor_match_worker.function_name
    label_enricher   = aws_lambda_function.label_enricher_worker.function_name
  }

  all_lambdas = merge(local.api_lambdas, local.worker_lambdas)
}

# ── Lambda errors (all functions) ────────────────────────────────
# treat_missing_data = notBreaching keeps rarely-invoked Lambdas
# (collector, auth_*) from false-alarming on idle. Trade-off: a fully
# broken Lambda emitting zero invocations also won't fire — acceptable
# for the single-tenant phase, revisit when wiring real paging.
resource "aws_cloudwatch_metric_alarm" "lambda_errors" {
  for_each = local.all_lambdas

  alarm_name          = "${each.value}-errors"
  comparison_operator = "GreaterThanOrEqualToThreshold"
  evaluation_periods  = 1
  metric_name         = "Errors"
  namespace           = "AWS/Lambda"
  period              = 300
  statistic           = "Sum"
  threshold           = 1
  treat_missing_data  = "notBreaching"
  alarm_description   = "Lambda ${each.value} reported at least one error in 5 minutes"

  dimensions = {
    FunctionName = each.value
  }

  alarm_actions = var.alarm_sns_topic_arn != "" ? [var.alarm_sns_topic_arn] : []
  ok_actions    = var.alarm_sns_topic_arn != "" ? [var.alarm_sns_topic_arn] : []
}

# ── Lambda duration p95 (API-facing only) ────────────────────────
# 20s threshold = 9s buffer before API GW 29s timeout. Async workers
# excluded because their normal duration exceeds 20s by design.
resource "aws_cloudwatch_metric_alarm" "lambda_duration_p95" {
  for_each = local.api_lambdas

  alarm_name          = "${each.value}-duration-p95"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 2
  metric_name         = "Duration"
  namespace           = "AWS/Lambda"
  period              = 300
  extended_statistic  = "p95"
  threshold           = 20000
  treat_missing_data  = "notBreaching"
  alarm_description   = "Lambda ${each.value} p95 latency > 20s — approaching API GW 29s timeout"

  dimensions = {
    FunctionName = each.value
  }

  alarm_actions = var.alarm_sns_topic_arn != "" ? [var.alarm_sns_topic_arn] : []
  ok_actions    = var.alarm_sns_topic_arn != "" ? [var.alarm_sns_topic_arn] : []
}

# ── Lambda throttles (label_enricher) ────────────────────────────
# Only meaningful when reserved concurrency caps the function — without
# the cap, AWS won't throttle. Fires on the first throttled invocation
# within 5 minutes so saturated vendor calls don't silently drop labels.
resource "aws_cloudwatch_metric_alarm" "label_enricher_throttles" {
  count = var.enable_lambda_reserved_concurrency ? 1 : 0

  alarm_name          = "${aws_lambda_function.label_enricher_worker.function_name}-throttles"
  namespace           = "AWS/Lambda"
  metric_name         = "Throttles"
  statistic           = "Sum"
  period              = 60
  evaluation_periods  = 5
  threshold           = 1
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "notBreaching"
  alarm_description   = "label_enricher throttled — reserved concurrency saturated"

  dimensions = {
    FunctionName = aws_lambda_function.label_enricher_worker.function_name
  }

  alarm_actions = var.alarm_sns_topic_arn != "" ? [var.alarm_sns_topic_arn] : []
  ok_actions    = var.alarm_sns_topic_arn != "" ? [var.alarm_sns_topic_arn] : []
}

# ── Aurora alarms ────────────────────────────────────────────────
resource "aws_cloudwatch_metric_alarm" "aurora_acu_near_max" {
  alarm_name          = "${aws_rds_cluster.aurora.cluster_identifier}-acu-near-max"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 2
  metric_name         = "ServerlessDatabaseCapacity"
  namespace           = "AWS/RDS"
  period              = 300
  statistic           = "Average"
  threshold           = var.aurora_serverless_max_acu * 0.9
  treat_missing_data  = "notBreaching"
  alarm_description   = "Aurora ACU > 90% of max — bump max_acu or optimize queries"

  dimensions = {
    DBClusterIdentifier = aws_rds_cluster.aurora.cluster_identifier
  }

  alarm_actions = var.alarm_sns_topic_arn != "" ? [var.alarm_sns_topic_arn] : []
  ok_actions    = var.alarm_sns_topic_arn != "" ? [var.alarm_sns_topic_arn] : []
}

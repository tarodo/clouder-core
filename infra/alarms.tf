# ── Lambda alarms ────────────────────────────────────────────────
locals {
  monitored_lambdas = {
    collector        = aws_lambda_function.collector.function_name
    canonicalization = aws_lambda_function.canonicalization_worker.function_name
    ai_search        = aws_lambda_function.ai_search_worker.function_name
    spotify_search   = aws_lambda_function.spotify_search_worker.function_name
    vendor_match     = aws_lambda_function.vendor_match_worker.function_name
    auth_handler     = aws_lambda_function.auth_handler.function_name
    auth_authorizer  = aws_lambda_function.auth_authorizer.function_name
    curation         = aws_lambda_function.curation.function_name
  }
}

resource "aws_cloudwatch_metric_alarm" "lambda_errors" {
  for_each = local.monitored_lambdas

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
}

resource "aws_cloudwatch_metric_alarm" "lambda_duration_p95" {
  for_each = local.monitored_lambdas

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
}

# ── Aurora alarms ────────────────────────────────────────────────
resource "aws_cloudwatch_metric_alarm" "aurora_acu_max" {
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
}

resource "aws_cloudwatch_log_group" "collector" {
  name              = "/aws/lambda/${local.lambda_name}"
  retention_in_days = var.log_retention_days
}

resource "aws_cloudwatch_log_group" "canonicalization_worker" {
  name              = "/aws/lambda/${local.canonicalization_worker_lambda_name}"
  retention_in_days = var.log_retention_days
}

resource "aws_cloudwatch_log_group" "migration_lambda" {
  name              = "/aws/lambda/${local.migration_lambda_name}"
  retention_in_days = var.log_retention_days
}

resource "aws_cloudwatch_log_group" "ai_search_worker" {
  name              = "/aws/lambda/${local.ai_search_worker_lambda_name}"
  retention_in_days = var.log_retention_days
}

resource "aws_cloudwatch_log_group" "spotify_search_worker" {
  name              = "/aws/lambda/${local.spotify_search_worker_lambda_name}"
  retention_in_days = var.log_retention_days
}

# ── DLQ depth alarms ─────────────────────────────────────────────

locals {
  dlq_queues = {
    canonicalization = aws_sqs_queue.canonicalization_dlq.name
    ai_search        = aws_sqs_queue.ai_search_dlq.name
    spotify_search   = aws_sqs_queue.spotify_search_dlq.name
  }
}

resource "aws_cloudwatch_metric_alarm" "dlq_depth" {
  for_each = local.dlq_queues

  alarm_name          = "${each.value}-has-messages"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 1
  metric_name         = "ApproximateNumberOfMessagesVisible"
  namespace           = "AWS/SQS"
  period              = 300
  statistic           = "Maximum"
  threshold           = 0
  treat_missing_data  = "notBreaching"

  alarm_description = "DLQ ${each.value} has messages — worker failing."

  dimensions = {
    QueueName = each.value
  }

  alarm_actions = var.alarm_sns_topic_arn != "" ? [var.alarm_sns_topic_arn] : []
  ok_actions    = var.alarm_sns_topic_arn != "" ? [var.alarm_sns_topic_arn] : []
}

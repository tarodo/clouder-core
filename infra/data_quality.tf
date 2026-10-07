# ── Nightly data-quality checks (docs/data/data-quality.md) ──
# Own least-privilege role: Data API on the cluster, the cluster secret, and
# PutMetricData only into the CLOUDER/DataQuality namespace.

locals {
  data_quality_lambda_name = "${local.name_prefix}-data-quality"
  data_quality_namespace   = "CLOUDER/DataQuality"
}

resource "aws_cloudwatch_log_group" "data_quality" {
  name              = "/aws/lambda/${local.data_quality_lambda_name}"
  retention_in_days = var.log_retention_days
}

resource "aws_iam_role" "data_quality" {
  name               = "${local.name_prefix}-data-quality-role"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
}

data "aws_iam_policy_document" "data_quality" {
  statement {
    sid       = "AllowOwnLogs"
    effect    = "Allow"
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${aws_cloudwatch_log_group.data_quality.arn}:*"]
  }
  statement {
    sid       = "AllowRdsDataApiRead"
    effect    = "Allow"
    actions   = ["rds-data:ExecuteStatement"]
    resources = [aws_rds_cluster.aurora.arn]
  }
  statement {
    sid       = "AllowReadDatabaseSecret"
    effect    = "Allow"
    actions   = ["secretsmanager:GetSecretValue"]
    resources = [try(aws_rds_cluster.aurora.master_user_secret[0].secret_arn, "*")]
  }
  statement {
    sid       = "AllowPutDataQualityMetrics"
    effect    = "Allow"
    actions   = ["cloudwatch:PutMetricData"]
    resources = ["*"]
    condition {
      test     = "StringEquals"
      variable = "cloudwatch:namespace"
      values   = [local.data_quality_namespace]
    }
  }
}

resource "aws_iam_role_policy" "data_quality" {
  name   = "${local.name_prefix}-data-quality-policy"
  role   = aws_iam_role.data_quality.id
  policy = data.aws_iam_policy_document.data_quality.json
}

resource "aws_lambda_function" "data_quality" {
  function_name    = local.data_quality_lambda_name
  role             = aws_iam_role.data_quality.arn
  runtime          = "python3.12"
  handler          = "collector.data_quality_handler.lambda_handler"
  filename         = local.lambda_zip_file
  timeout          = 120
  memory_size      = 256
  source_code_hash = filebase64sha256(local.lambda_zip_file)

  environment {
    variables = {
      AURORA_CLUSTER_ARN = aws_rds_cluster.aurora.arn
      AURORA_SECRET_ARN  = try(aws_rds_cluster.aurora.master_user_secret[0].secret_arn, "")
      AURORA_DATABASE    = var.aurora_database_name
      LOG_LEVEL          = "INFO"
    }
  }

  depends_on = [aws_cloudwatch_log_group.data_quality]
}

# 00:10 UTC: ten minutes after the catalog export, which already wakes Aurora.
resource "aws_cloudwatch_event_rule" "data_quality_daily" {
  name                = "${local.name_prefix}-data-quality-daily"
  schedule_expression = "cron(10 0 * * ? *)"
}

resource "aws_cloudwatch_event_target" "data_quality_daily" {
  rule      = aws_cloudwatch_event_rule.data_quality_daily.name
  target_id = "data-quality"
  arn       = aws_lambda_function.data_quality.arn
}

resource "aws_lambda_permission" "data_quality_events" {
  statement_id  = "AllowExecutionFromEventBridgeDataQuality"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.data_quality.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.data_quality_daily.arn
}

resource "aws_cloudwatch_metric_alarm" "data_quality_failed_checks" {
  alarm_name          = "${local.name_prefix}-data-quality-failed-checks"
  alarm_description   = "At least one nightly data-quality check failed — see docs/data/data-quality.md"
  namespace           = local.data_quality_namespace
  metric_name         = "FailedChecks"
  statistic           = "Maximum"
  period              = 86400
  evaluation_periods  = 1
  threshold           = 1
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "missing"

  alarm_actions = var.alarm_sns_topic_arn != "" ? [var.alarm_sns_topic_arn] : []
  ok_actions    = var.alarm_sns_topic_arn != "" ? [var.alarm_sns_topic_arn] : []
}

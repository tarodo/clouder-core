# ── analytics-rollup Lambda (§13 write role) ─────────────────────────
# Scheduled daily at 03:00 UTC. Overwrites the last 3 dt partitions of
# mart_user_daily + fact_session via S3 delete + Athena INSERT INTO.
# Dedicated write role: Athena + Glue write + S3 read-bronze/write-marts.

resource "aws_cloudwatch_log_group" "analytics_rollup" {
  name              = "/aws/lambda/${local.name_prefix}-analytics-rollup"
  retention_in_days = 14
}

resource "aws_iam_role" "analytics_rollup" {
  name               = "${local.name_prefix}-analytics-rollup-role"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
}

data "aws_iam_policy_document" "analytics_rollup" {
  statement {
    sid       = "AllowCloudWatchLogs"
    effect    = "Allow"
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${aws_cloudwatch_log_group.analytics_rollup.arn}:*"]
  }

  statement {
    sid    = "AthenaQuery"
    effect = "Allow"
    actions = [
      "athena:StartQueryExecution",
      "athena:GetQueryExecution",
      "athena:GetQueryResults",
      "athena:GetWorkGroup",
      "athena:StopQueryExecution",
    ]
    resources = ["arn:aws:athena:${var.aws_region}:${data.aws_caller_identity.current.account_id}:workgroup/${var.athena_workgroup}"]
  }

  statement {
    sid    = "GlueReadWrite"
    effect = "Allow"
    actions = [
      "glue:GetDatabase",
      "glue:GetTable",
      "glue:GetTables",
      "glue:GetPartition",
      "glue:GetPartitions",
      "glue:BatchCreatePartition",
      "glue:CreatePartition",
      "glue:UpdateTable",
    ]
    resources = [
      "arn:aws:glue:${var.aws_region}:${data.aws_caller_identity.current.account_id}:catalog",
      "arn:aws:glue:${var.aws_region}:${data.aws_caller_identity.current.account_id}:database/${var.analytics_glue_database}",
      "arn:aws:glue:${var.aws_region}:${data.aws_caller_identity.current.account_id}:table/${var.analytics_glue_database}/*",
    ]
  }

  statement {
    sid    = "S3ReadBronzeAndResults"
    effect = "Allow"
    actions = [
      "s3:GetObject",
      "s3:ListBucket",
      "s3:GetBucketLocation",
    ]
    resources = [
      "arn:aws:s3:::${var.analytics_lake_bucket}",
      "arn:aws:s3:::${var.analytics_lake_bucket}/bronze/events/*",
      "arn:aws:s3:::${var.analytics_lake_bucket}/athena-results/*",
    ]
  }

  statement {
    sid    = "S3WriteMarts"
    effect = "Allow"
    actions = [
      "s3:GetObject",
      "s3:PutObject",
      "s3:DeleteObject",
    ]
    resources = ["arn:aws:s3:::${var.analytics_lake_bucket}/marts/*"]
  }

  statement {
    sid       = "S3WriteAthenaResults"
    effect    = "Allow"
    actions   = ["s3:PutObject"]
    resources = ["arn:aws:s3:::${var.analytics_lake_bucket}/athena-results/*"]
  }
}

resource "aws_iam_role_policy" "analytics_rollup" {
  name   = "${local.name_prefix}-analytics-rollup-policy"
  role   = aws_iam_role.analytics_rollup.id
  policy = data.aws_iam_policy_document.analytics_rollup.json
}

resource "aws_lambda_function" "analytics_rollup" {
  function_name = "${local.name_prefix}-analytics-rollup"
  role          = aws_iam_role.analytics_rollup.arn
  runtime       = "python3.12"
  handler       = "collector.analytics_rollup_runner.lambda_handler"
  filename      = local.lambda_zip_file
  timeout       = 300
  memory_size   = 256

  source_code_hash = filebase64sha256(local.lambda_zip_file)

  environment {
    variables = {
      ATHENA_DATABASE        = var.analytics_glue_database
      ATHENA_WORKGROUP       = var.athena_workgroup
      ATHENA_OUTPUT_LOCATION = "s3://${var.analytics_lake_bucket}/athena-results/"
      ANALYTICS_LAKE_BUCKET  = var.analytics_lake_bucket
      LOG_LEVEL              = "INFO"
    }
  }

  depends_on = [aws_cloudwatch_log_group.analytics_rollup]
}

resource "aws_cloudwatch_event_rule" "analytics_rollup_daily" {
  name                = "${local.name_prefix}-analytics-rollup-daily"
  schedule_expression = "cron(0 3 * * ? *)"
}

resource "aws_cloudwatch_event_target" "analytics_rollup_daily" {
  rule      = aws_cloudwatch_event_rule.analytics_rollup_daily.name
  target_id = "analytics-rollup"
  arn       = aws_lambda_function.analytics_rollup.arn
}

resource "aws_lambda_permission" "analytics_rollup_events" {
  statement_id  = "AllowExecutionFromEventBridgeRollup"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.analytics_rollup.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.analytics_rollup_daily.arn
}

locals {
  analytics_sfn_name = "${local.name_prefix}-analytics-daily"
}

# ── Step Functions Standard state machine ────────────────────────────────────

resource "aws_iam_role" "analytics_sfn" {
  name = "${local.name_prefix}-analytics-sfn-role"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "states.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

data "aws_iam_policy_document" "analytics_sfn" {
  statement {
    sid     = "InvokeLambdas"
    effect  = "Allow"
    actions = ["lambda:InvokeFunction"]
    resources = [
      aws_lambda_function.catalog_export.arn,
      aws_lambda_function.ops_log_export.arn,
      aws_lambda_function.dbt_runner.arn,
    ]
  }
}

resource "aws_iam_role_policy" "analytics_sfn" {
  name   = "${local.name_prefix}-analytics-sfn-policy"
  role   = aws_iam_role.analytics_sfn.id
  policy = data.aws_iam_policy_document.analytics_sfn.json
}

resource "aws_sfn_state_machine" "analytics_daily" {
  name     = local.analytics_sfn_name
  role_arn = aws_iam_role.analytics_sfn.arn
  type     = "STANDARD"
  definition = templatefile("${path.module}/../analytics/state_machine.asl.json", {
    catalog_export_arn = aws_lambda_function.catalog_export.arn
    ops_log_export_arn = aws_lambda_function.ops_log_export.arn
    dbt_runner_arn     = aws_lambda_function.dbt_runner.arn
  })
}

# ── EventBridge Scheduler: daily trigger at 07:00 UTC ────────────────────────

resource "aws_iam_role" "analytics_scheduler" {
  name = "${local.name_prefix}-analytics-scheduler-role"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "scheduler.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

data "aws_iam_policy_document" "analytics_scheduler" {
  statement {
    sid       = "StartStateMachine"
    effect    = "Allow"
    actions   = ["states:StartExecution"]
    resources = [aws_sfn_state_machine.analytics_daily.arn]
  }
}

resource "aws_iam_role_policy" "analytics_scheduler" {
  name   = "${local.name_prefix}-analytics-scheduler-policy"
  role   = aws_iam_role.analytics_scheduler.id
  policy = data.aws_iam_policy_document.analytics_scheduler.json
}

resource "aws_scheduler_schedule" "analytics_daily" {
  name = "${local.name_prefix}-analytics-daily"
  flexible_time_window {
    mode = "OFF"
  }
  schedule_expression          = "cron(0 7 * * ? *)"
  schedule_expression_timezone = "UTC"

  target {
    arn      = aws_sfn_state_machine.analytics_daily.arn
    role_arn = aws_iam_role.analytics_scheduler.arn
  }
}

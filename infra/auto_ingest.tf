# ── Auto-ingest (docs/data/auto-ingest.md) ──
# The Beatport credentials come from GitHub secrets through SSM (deploy.yml); the
# token is obtained on every invocation and never stored. No reserved concurrency:
# the account quota is 10 (runbook "Lambda reserved concurrency trip"); a lease on
# the settings row keeps runs from overlapping.
# A daily planner (00:05 UTC) writes one-time `run-*` schedules into the group below,
# from the settings saved in the admin.

locals {
  auto_ingest_lambda_name = "${local.name_prefix}-auto-ingest"
  beatport_username_ssm   = "/clouder/beatport/username"
  beatport_password_ssm   = "/clouder/beatport/password"
}

resource "aws_cloudwatch_log_group" "auto_ingest" {
  name              = "/aws/lambda/${local.auto_ingest_lambda_name}"
  retention_in_days = var.log_retention_days
}

resource "aws_iam_role" "auto_ingest" {
  name               = "${local.name_prefix}-auto-ingest-role"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
}

data "aws_iam_policy_document" "auto_ingest" {
  statement {
    sid       = "AllowOwnLogs"
    effect    = "Allow"
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${aws_cloudwatch_log_group.auto_ingest.arn}:*"]
  }
  statement {
    sid     = "ReadBeatportCredentials"
    effect  = "Allow"
    actions = ["ssm:GetParameter"]
    resources = [
      "arn:aws:ssm:${var.aws_region}:${data.aws_caller_identity.current.account_id}:parameter${local.beatport_username_ssm}",
      "arn:aws:ssm:${var.aws_region}:${data.aws_caller_identity.current.account_id}:parameter${local.beatport_password_ssm}",
    ]
  }
  statement {
    sid       = "DecryptSsmParameters"
    effect    = "Allow"
    actions   = ["kms:Decrypt"]
    resources = ["arn:aws:kms:${var.aws_region}:${data.aws_caller_identity.current.account_id}:alias/aws/ssm"]
  }
  statement {
    sid    = "AllowRdsDataApi"
    effect = "Allow"
    actions = [
      "rds-data:BeginTransaction",
      "rds-data:CommitTransaction",
      "rds-data:RollbackTransaction",
      "rds-data:ExecuteStatement",
      "rds-data:BatchExecuteStatement",
    ]
    resources = [aws_rds_cluster.aurora.arn]
  }
  statement {
    sid       = "AllowReadDatabaseSecret"
    effect    = "Allow"
    actions   = ["secretsmanager:GetSecretValue"]
    resources = [try(aws_rds_cluster.aurora.master_user_secret[0].secret_arn, "*")]
  }
  statement {
    sid       = "AllowWriteRawReleases"
    effect    = "Allow"
    actions   = ["s3:PutObject"]
    resources = ["${aws_s3_bucket.raw.arn}/${var.raw_prefix}/*"]
  }
  statement {
    sid       = "AllowEnqueueCanonicalization"
    effect    = "Allow"
    actions   = ["sqs:SendMessage"]
    resources = [aws_sqs_queue.canonicalization.arn]
  }
  statement {
    sid    = "AllowManageRunSchedules"
    effect = "Allow"
    actions = [
      "scheduler:CreateSchedule",
      "scheduler:DeleteSchedule",
      "scheduler:GetSchedule",
    ]
    resources = ["arn:aws:scheduler:${var.aws_region}:${data.aws_caller_identity.current.account_id}:schedule/${aws_scheduler_schedule_group.auto_ingest.name}/*"]
  }
  statement {
    # ListSchedules has no resource-level permissions.
    sid       = "AllowListSchedules"
    effect    = "Allow"
    actions   = ["scheduler:ListSchedules"]
    resources = ["*"]
  }
  statement {
    sid       = "AllowPassSchedulerRole"
    effect    = "Allow"
    actions   = ["iam:PassRole"]
    resources = [aws_iam_role.auto_ingest_scheduler.arn]
  }
}

resource "aws_iam_role_policy" "auto_ingest" {
  name   = "${local.name_prefix}-auto-ingest-policy"
  role   = aws_iam_role.auto_ingest.id
  policy = data.aws_iam_policy_document.auto_ingest.json
}

resource "aws_lambda_function" "auto_ingest" {
  function_name    = local.auto_ingest_lambda_name
  role             = aws_iam_role.auto_ingest.arn
  runtime          = "python3.12"
  handler          = "collector.auto_ingest_handler.lambda_handler"
  filename         = local.lambda_zip_file
  timeout          = 900
  memory_size      = 512
  source_code_hash = filebase64sha256(local.lambda_zip_file)

  environment {
    variables = {
      BEATPORT_USERNAME_SSM_PARAMETER = local.beatport_username_ssm
      BEATPORT_PASSWORD_SSM_PARAMETER = local.beatport_password_ssm
      RAW_BUCKET_NAME                 = aws_s3_bucket.raw.bucket
      RAW_PREFIX                      = var.raw_prefix
      BEATPORT_API_BASE_URL           = var.beatport_api_base_url
      CANONICALIZATION_ENABLED        = var.canonicalization_enabled ? "true" : "false"
      CANONICALIZATION_QUEUE_URL      = aws_sqs_queue.canonicalization.url
      AURORA_CLUSTER_ARN              = aws_rds_cluster.aurora.arn
      AURORA_SECRET_ARN               = try(aws_rds_cluster.aurora.master_user_secret[0].secret_arn, "")
      AURORA_DATABASE                 = var.aurora_database_name
      VENDORS_ENABLED                 = "beatport"
      AUTO_INGEST_SCHEDULE_GROUP      = aws_scheduler_schedule_group.auto_ingest.name
      AUTO_INGEST_SCHEDULER_ROLE_ARN  = aws_iam_role.auto_ingest_scheduler.arn
      LOG_LEVEL                       = "INFO"
    }
  }

  depends_on = [aws_cloudwatch_log_group.auto_ingest]
}

# ── Scheduling ──

resource "aws_scheduler_schedule_group" "auto_ingest" {
  name = "${local.name_prefix}-auto-ingest"
}

data "aws_iam_policy_document" "auto_ingest_scheduler_assume" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["scheduler.amazonaws.com"]
    }
    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [data.aws_caller_identity.current.account_id]
    }
  }
}

resource "aws_iam_role" "auto_ingest_scheduler" {
  name               = "${local.name_prefix}-auto-ingest-scheduler-role"
  assume_role_policy = data.aws_iam_policy_document.auto_ingest_scheduler_assume.json
}

data "aws_iam_policy_document" "auto_ingest_scheduler" {
  statement {
    effect    = "Allow"
    actions   = ["lambda:InvokeFunction"]
    resources = [aws_lambda_function.auto_ingest.arn]
  }
}

resource "aws_iam_role_policy" "auto_ingest_scheduler" {
  name   = "${local.name_prefix}-auto-ingest-scheduler-policy"
  role   = aws_iam_role.auto_ingest_scheduler.id
  policy = data.aws_iam_policy_document.auto_ingest_scheduler.json
}

resource "aws_scheduler_schedule" "auto_ingest_plan" {
  name                         = "plan-daily"
  group_name                   = aws_scheduler_schedule_group.auto_ingest.name
  schedule_expression          = "cron(5 0 * * ? *)"
  schedule_expression_timezone = "UTC"

  flexible_time_window {
    mode = "OFF"
  }

  target {
    arn      = aws_lambda_function.auto_ingest.arn
    role_arn = aws_iam_role.auto_ingest_scheduler.arn
    input    = jsonencode({ action = "plan" })
  }
}

# ── Alerting: a login failure, or a run whose every period failed ──

resource "aws_cloudwatch_log_metric_filter" "auto_ingest_run_failed" {
  name           = "${local.name_prefix}-auto-ingest-run-failed"
  log_group_name = aws_cloudwatch_log_group.auto_ingest.name
  pattern        = "{ $.message = \"auto_ingest_run_failed\" }"

  metric_transformation {
    name      = "AutoIngestRunFailed"
    namespace = "CLOUDER/AutoIngest"
    value     = "1"
  }
}

resource "aws_cloudwatch_metric_alarm" "auto_ingest_failed" {
  alarm_name          = "${local.name_prefix}-auto-ingest-failed"
  alarm_description   = "An auto-ingest run failed (login, or every period) — docs/data/auto-ingest.md"
  namespace           = "CLOUDER/AutoIngest"
  metric_name         = "AutoIngestRunFailed"
  statistic           = "Sum"
  period              = 86400
  evaluation_periods  = 1
  threshold           = 1
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "notBreaching"

  alarm_actions = var.alarm_sns_topic_arn != "" ? [var.alarm_sns_topic_arn] : []
  ok_actions    = var.alarm_sns_topic_arn != "" ? [var.alarm_sns_topic_arn] : []
}

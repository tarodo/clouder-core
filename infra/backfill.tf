# ── Backfill: replay stored raw Beatport runs through the canonicalizer ──
# Started by hand (docs/ops/backfill.md). Ingest stays outside: Step Functions
# keeps every state's input in the execution history, and the Beatport token
# must never be persisted (ADR-0024).

locals {
  backfill_lambda_name = "${local.name_prefix}-backfill"
}

resource "aws_cloudwatch_log_group" "backfill" {
  name              = "/aws/lambda/${local.backfill_lambda_name}"
  retention_in_days = var.log_retention_days
}

resource "aws_iam_role" "backfill" {
  name               = "${local.name_prefix}-backfill-role"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
}

data "aws_iam_policy_document" "backfill" {
  statement {
    sid       = "AllowOwnLogs"
    effect    = "Allow"
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${aws_cloudwatch_log_group.backfill.arn}:*"]
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
    sid       = "AllowReadRawReleases"
    effect    = "Allow"
    actions   = ["s3:GetObject"]
    resources = ["${aws_s3_bucket.raw.arn}/${var.raw_prefix}/*"]
  }
  statement {
    # A replay that applies quarantines bad records like the live worker.
    sid       = "AllowWriteQuarantine"
    effect    = "Allow"
    actions   = ["s3:PutObject"]
    resources = ["${aws_s3_bucket.raw.arn}/${var.raw_prefix}/_quarantine/*"]
  }
  statement {
    sid       = "AllowEnqueueSpotifySearch"
    effect    = "Allow"
    actions   = ["sqs:SendMessage"]
    resources = [aws_sqs_queue.spotify_search.arn]
  }
}

resource "aws_iam_role_policy" "backfill" {
  name   = "${local.name_prefix}-backfill-policy"
  role   = aws_iam_role.backfill.id
  policy = data.aws_iam_policy_document.backfill.json
}

resource "aws_lambda_function" "backfill" {
  function_name    = local.backfill_lambda_name
  role             = aws_iam_role.backfill.arn
  runtime          = "python3.12"
  handler          = "collector.backfill_handler.lambda_handler"
  filename         = local.lambda_zip_file
  timeout          = 900
  memory_size      = var.canonicalization_worker_lambda_memory_mb
  source_code_hash = filebase64sha256(local.lambda_zip_file)

  environment {
    variables = {
      RAW_BUCKET_NAME          = aws_s3_bucket.raw.bucket
      RAW_PREFIX               = var.raw_prefix
      SPOTIFY_SEARCH_QUEUE_URL = aws_sqs_queue.spotify_search.url
      AURORA_CLUSTER_ARN       = aws_rds_cluster.aurora.arn
      AURORA_SECRET_ARN        = try(aws_rds_cluster.aurora.master_user_secret[0].secret_arn, "")
      AURORA_DATABASE          = var.aurora_database_name
      LOG_LEVEL                = "INFO"
    }
  }

  depends_on = [aws_cloudwatch_log_group.backfill]
}

data "aws_iam_policy_document" "states_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["states.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "backfill_state_machine" {
  name               = "${local.name_prefix}-backfill-sfn-role"
  assume_role_policy = data.aws_iam_policy_document.states_assume.json
}

data "aws_iam_policy_document" "backfill_state_machine" {
  statement {
    sid     = "AllowInvokeTaskLambdas"
    effect  = "Allow"
    actions = ["lambda:InvokeFunction"]
    resources = [
      aws_lambda_function.backfill.arn,
      "${aws_lambda_function.backfill.arn}:*",
      aws_lambda_function.data_quality.arn,
      "${aws_lambda_function.data_quality.arn}:*",
    ]
  }
}

resource "aws_iam_role_policy" "backfill_state_machine" {
  name   = "${local.name_prefix}-backfill-sfn-policy"
  role   = aws_iam_role.backfill_state_machine.id
  policy = data.aws_iam_policy_document.backfill_state_machine.json
}

resource "aws_sfn_state_machine" "backfill" {
  name     = "${local.name_prefix}-backfill"
  role_arn = aws_iam_role.backfill_state_machine.arn
  definition = templatefile("${path.module}/backfill.asl.json", {
    backfill_function_arn     = aws_lambda_function.backfill.arn
    data_quality_function_arn = aws_lambda_function.data_quality.arn
  })
}

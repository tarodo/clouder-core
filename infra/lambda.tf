resource "aws_lambda_function" "collector" {
  function_name = local.lambda_name
  role          = aws_iam_role.collector_lambda.arn
  runtime       = "python3.12"
  handler       = "collector.handler.lambda_handler"
  filename      = local.lambda_zip_file
  timeout       = var.lambda_timeout_seconds
  memory_size   = var.lambda_memory_mb

  source_code_hash = filebase64sha256(local.lambda_zip_file)

  environment {
    variables = {
      RAW_BUCKET_NAME        = aws_s3_bucket.raw.bucket
      RAW_PREFIX             = var.raw_prefix
      BEATPORT_API_BASE_URL  = var.beatport_api_base_url
      CANONICALIZE_ENABLED   = var.canonicalize_enabled ? "true" : "false"
      CANONICALIZE_QUEUE_URL = aws_sqs_queue.canonicalize.url
      AURORA_CLUSTER_ARN     = aws_rds_cluster.aurora.arn
      AURORA_SECRET_ARN      = try(aws_rds_cluster.aurora.master_user_secret[0].secret_arn, "")
      AURORA_DATABASE        = var.aurora_database_name
      LOG_LEVEL              = "INFO"
    }
  }

  depends_on = [
    aws_cloudwatch_log_group.collector,
  ]
}

resource "aws_lambda_function" "canonicalizer_worker" {
  function_name = local.worker_lambda_name
  role          = aws_iam_role.collector_lambda.arn
  runtime       = "python3.12"
  handler       = "collector.worker_handler.lambda_handler"
  filename      = local.lambda_zip_file
  timeout       = var.worker_lambda_timeout_seconds
  memory_size   = var.worker_lambda_memory_mb

  source_code_hash = filebase64sha256(local.lambda_zip_file)

  environment {
    variables = {
      RAW_BUCKET_NAME    = aws_s3_bucket.raw.bucket
      RAW_PREFIX         = var.raw_prefix
      AURORA_CLUSTER_ARN = aws_rds_cluster.aurora.arn
      AURORA_SECRET_ARN  = try(aws_rds_cluster.aurora.master_user_secret[0].secret_arn, "")
      AURORA_DATABASE    = var.aurora_database_name
      LOG_LEVEL          = "INFO"
    }
  }

  depends_on = [
    aws_cloudwatch_log_group.canonicalizer_worker,
  ]
}

resource "aws_lambda_event_source_mapping" "canonicalizer_queue" {
  event_source_arn = aws_sqs_queue.canonicalize.arn
  function_name    = aws_lambda_function.canonicalizer_worker.arn
  batch_size       = var.canonicalizer_batch_size
}

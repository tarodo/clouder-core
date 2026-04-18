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
      RAW_BUCKET_NAME            = aws_s3_bucket.raw.bucket
      RAW_PREFIX                 = var.raw_prefix
      BEATPORT_API_BASE_URL      = var.beatport_api_base_url
      CANONICALIZATION_ENABLED   = var.canonicalization_enabled ? "true" : "false"
      CANONICALIZATION_QUEUE_URL = aws_sqs_queue.canonicalization.url
      AI_SEARCH_ENABLED          = var.ai_search_enabled ? "true" : "false"
      AI_SEARCH_QUEUE_URL        = aws_sqs_queue.ai_search.url
      SPOTIFY_SEARCH_ENABLED     = var.spotify_search_enabled ? "true" : "false"
      SPOTIFY_SEARCH_QUEUE_URL   = aws_sqs_queue.spotify_search.url
      AURORA_CLUSTER_ARN         = aws_rds_cluster.aurora.arn
      AURORA_SECRET_ARN          = try(aws_rds_cluster.aurora.master_user_secret[0].secret_arn, "")
      AURORA_DATABASE            = var.aurora_database_name
      LOG_LEVEL                  = "INFO"
    }
  }

  depends_on = [
    aws_cloudwatch_log_group.collector,
  ]
}

resource "aws_lambda_function" "canonicalization_worker" {
  function_name = local.canonicalization_worker_lambda_name
  role          = aws_iam_role.collector_lambda.arn
  runtime       = "python3.12"
  handler       = "collector.worker_handler.lambda_handler"
  filename      = local.lambda_zip_file
  timeout       = var.canonicalization_worker_lambda_timeout_seconds
  memory_size   = var.canonicalization_worker_lambda_memory_mb

  source_code_hash = filebase64sha256(local.lambda_zip_file)

  environment {
    variables = {
      RAW_BUCKET_NAME          = aws_s3_bucket.raw.bucket
      RAW_PREFIX               = var.raw_prefix
      AI_SEARCH_QUEUE_URL      = aws_sqs_queue.ai_search.url
      SPOTIFY_SEARCH_QUEUE_URL = aws_sqs_queue.spotify_search.url
      AURORA_CLUSTER_ARN       = aws_rds_cluster.aurora.arn
      AURORA_SECRET_ARN        = try(aws_rds_cluster.aurora.master_user_secret[0].secret_arn, "")
      AURORA_DATABASE          = var.aurora_database_name
      LOG_LEVEL                = "INFO"
    }
  }

  depends_on = [
    aws_cloudwatch_log_group.canonicalization_worker,
  ]
}

resource "aws_lambda_function" "db_migration" {
  function_name = local.migration_lambda_name
  role          = aws_iam_role.collector_lambda.arn
  runtime       = "python3.12"
  handler       = "collector.migration_handler.lambda_handler"
  filename      = local.lambda_zip_file
  timeout       = var.migration_lambda_timeout_seconds
  memory_size   = var.migration_lambda_memory_mb

  source_code_hash = filebase64sha256(local.lambda_zip_file)

  vpc_config {
    subnet_ids         = [aws_subnet.db_a.id, aws_subnet.db_b.id]
    security_group_ids = [aws_security_group.migration_lambda.id]
  }

  environment {
    variables = {
      AURORA_WRITER_ENDPOINT = aws_rds_cluster.aurora.endpoint
      AURORA_DATABASE        = var.aurora_database_name
      AURORA_PORT            = "5432"
      AURORA_SECRET_ARN      = try(aws_rds_cluster.aurora.master_user_secret[0].secret_arn, "")
      LOG_LEVEL              = "INFO"
    }
  }

  depends_on = [
    aws_cloudwatch_log_group.migration_lambda,
  ]
}

resource "aws_lambda_event_source_mapping" "canonicalization_queue" {
  event_source_arn = aws_sqs_queue.canonicalization.arn
  function_name    = aws_lambda_function.canonicalization_worker.arn
  batch_size       = var.canonicalization_batch_size
}

# ── AI Search worker ─────────────────────────────────────────────

resource "aws_lambda_function" "ai_search_worker" {
  function_name = local.ai_search_worker_lambda_name
  role          = aws_iam_role.collector_lambda.arn
  runtime       = "python3.12"
  handler       = "collector.search_handler.lambda_handler"
  filename      = local.lambda_zip_file
  timeout       = var.ai_search_worker_lambda_timeout_seconds
  memory_size   = var.ai_search_worker_lambda_memory_mb

  source_code_hash = filebase64sha256(local.lambda_zip_file)

  environment {
    variables = {
      PERPLEXITY_API_KEY_SECRET_ARN    = var.perplexity_api_key_secret_arn
      PERPLEXITY_API_KEY_SSM_PARAMETER = var.perplexity_api_key_ssm_parameter
      AURORA_CLUSTER_ARN               = aws_rds_cluster.aurora.arn
      AURORA_SECRET_ARN                = try(aws_rds_cluster.aurora.master_user_secret[0].secret_arn, "")
      AURORA_DATABASE                  = var.aurora_database_name
      LOG_LEVEL                        = "INFO"
    }
  }

  depends_on = [
    aws_cloudwatch_log_group.ai_search_worker,
  ]
}

resource "aws_lambda_event_source_mapping" "ai_search_queue" {
  event_source_arn = aws_sqs_queue.ai_search.arn
  function_name    = aws_lambda_function.ai_search_worker.arn
  batch_size       = var.ai_search_batch_size
}

# ── Spotify Search worker ────────────────────────────────────────

resource "aws_lambda_function" "spotify_search_worker" {
  function_name = local.spotify_search_worker_lambda_name
  role          = aws_iam_role.collector_lambda.arn
  runtime       = "python3.12"
  handler       = "collector.spotify_handler.lambda_handler"
  filename      = local.lambda_zip_file
  timeout       = var.spotify_search_worker_lambda_timeout_seconds
  memory_size   = var.spotify_search_worker_lambda_memory_mb

  source_code_hash = filebase64sha256(local.lambda_zip_file)

  environment {
    variables = {
      SPOTIFY_CREDENTIALS_SECRET_ARN      = var.spotify_credentials_secret_arn
      SPOTIFY_CLIENT_ID_SSM_PARAMETER     = var.spotify_client_id_ssm_parameter
      SPOTIFY_CLIENT_SECRET_SSM_PARAMETER = var.spotify_client_secret_ssm_parameter
      RAW_BUCKET_NAME                     = aws_s3_bucket.raw.bucket
      SPOTIFY_RAW_PREFIX                  = var.spotify_raw_prefix
      SPOTIFY_SEARCH_QUEUE_URL            = aws_sqs_queue.spotify_search.url
      AURORA_CLUSTER_ARN                  = aws_rds_cluster.aurora.arn
      AURORA_SECRET_ARN                   = try(aws_rds_cluster.aurora.master_user_secret[0].secret_arn, "")
      AURORA_DATABASE                     = var.aurora_database_name
      LOG_LEVEL                           = "INFO"
    }
  }

  depends_on = [
    aws_cloudwatch_log_group.spotify_search_worker,
  ]
}

resource "aws_lambda_event_source_mapping" "spotify_search_queue" {
  event_source_arn = aws_sqs_queue.spotify_search.arn
  function_name    = aws_lambda_function.spotify_search_worker.arn
  batch_size       = var.spotify_search_batch_size
}

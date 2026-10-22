resource "aws_lambda_function" "collector" {
  function_name = local.lambda_name
  publish       = true # versions behind the live alias (lambda_aliases.tf)
  role          = module.role_collector.arn
  runtime       = "python3.12"
  handler       = "collector.handler.lambda_handler"
  filename      = local.lambda_zip_file
  timeout       = var.lambda_timeout_seconds
  memory_size   = var.lambda_memory_mb

  source_code_hash = filebase64sha256(local.lambda_zip_file)

  environment {
    variables = {
      RAW_BUCKET_NAME             = aws_s3_bucket.raw.bucket
      RAW_PREFIX                  = var.raw_prefix
      BEATPORT_API_BASE_URL       = var.beatport_api_base_url
      CANONICALIZATION_ENABLED    = var.canonicalization_enabled ? "true" : "false"
      CANONICALIZATION_QUEUE_URL  = aws_sqs_queue.canonicalization.url
      SPOTIFY_SEARCH_ENABLED      = var.spotify_search_enabled ? "true" : "false"
      SPOTIFY_SEARCH_QUEUE_URL    = aws_sqs_queue.spotify_search.url
      YOUTUBE_SEARCH_QUEUE_URL    = aws_sqs_queue.youtube_search.url
      LABEL_ENRICHMENT_QUEUE_URL  = aws_sqs_queue.label_enrichment.url
      ARTIST_ENRICHMENT_QUEUE_URL = aws_sqs_queue.artist_enrichment.url
      AURORA_CLUSTER_ARN          = aws_rds_cluster.aurora.arn
      AURORA_SECRET_ARN           = try(aws_rds_cluster.aurora.master_user_secret[0].secret_arn, "")
      AURORA_DATABASE             = var.aurora_database_name
      LOG_LEVEL                   = "INFO"
      VENDORS_ENABLED             = "beatport"
      AUTO_INGEST_FUNCTION_NAME   = local.auto_ingest_lambda_name
      # Coverage-cell ingest logs in to Beatport itself, like auto-ingest.
      BEATPORT_USERNAME_SSM_PARAMETER = local.beatport_username_ssm
      BEATPORT_PASSWORD_SSM_PARAMETER = local.beatport_password_ssm
      BEATPORT_CLIENT_ID              = var.beatport_client_id
    }
  }

  depends_on = [
    aws_cloudwatch_log_group.collector,
  ]
}

resource "aws_lambda_function" "canonicalization_worker" {
  function_name = local.canonicalization_worker_lambda_name
  role          = module.role_canonicalization_worker.arn
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
  role          = module.role_db_migration.arn
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
      AURORA_AUTH_MODE       = var.migration_aurora_auth_mode
      AURORA_DB_USER         = var.migration_db_user
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

  # Every worker is capped so together they leave the API room in the account's
  # concurrency pool (infra/concurrency.tf, postmortem 2026-10-11).
  scaling_config {
    maximum_concurrency = var.canonicalization_max_concurrency
  }
}

# ── Spotify Search worker ────────────────────────────────────────

resource "aws_lambda_function" "spotify_search_worker" {
  function_name = local.spotify_search_worker_lambda_name
  role          = module.role_spotify_search_worker.arn
  runtime       = "python3.12"
  handler       = "collector.spotify_handler.lambda_handler"
  filename      = local.lambda_zip_file
  timeout       = var.spotify_search_worker_lambda_timeout_seconds
  memory_size   = var.spotify_search_worker_lambda_memory_mb

  reserved_concurrent_executions = var.enable_lambda_reserved_concurrency ? var.spotify_search_worker_reserved_concurrency : -1

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
      VENDORS_ENABLED                     = "spotify"
      SPOTIFY_METADATA_FALLBACK_ENABLED   = "true"
      SPOTIFY_MIN_REQUEST_INTERVAL_MS     = var.spotify_min_request_interval_ms
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

  # One queue, a bounded number of workers draining it: extra messages wait in
  # the queue instead of multiplying the request rate (Spotify ban, 2026-10-10).
  scaling_config {
    maximum_concurrency = var.spotify_search_max_concurrency
  }
}

# ── YouTube Search worker ────────────────────────────────────────

resource "aws_lambda_function" "youtube_search_worker" {
  function_name = local.youtube_search_worker_lambda_name
  role          = module.role_youtube_search_worker.arn
  runtime       = "python3.12"
  handler       = "collector.youtube_search_handler.lambda_handler"
  filename      = local.lambda_zip_file
  timeout       = 900
  memory_size   = 512

  # No reserved concurrency: AWS rejects an SQS trigger cap (minimum 2) above
  # it. The trigger cap (2) bounds the workers; the pace below is per worker.

  source_code_hash = filebase64sha256(local.lambda_zip_file)

  environment {
    variables = {
      AURORA_CLUSTER_ARN             = aws_rds_cluster.aurora.arn
      AURORA_SECRET_ARN              = try(aws_rds_cluster.aurora.master_user_secret[0].secret_arn, "")
      AURORA_DATABASE                = var.aurora_database_name
      LOG_LEVEL                      = "INFO"
      YOUTUBE_SEARCH_MIN_INTERVAL_MS = var.youtube_search_min_interval_ms
      YOUTUBE_SEARCH_BAN_SECONDS     = var.youtube_search_ban_seconds
      FUZZY_MATCH_THRESHOLD          = "0.92"
    }
  }

  depends_on = [aws_cloudwatch_log_group.youtube_search_worker]
}

resource "aws_lambda_event_source_mapping" "youtube_search_queue" {
  event_source_arn = aws_sqs_queue.youtube_search.arn
  function_name    = aws_lambda_function.youtube_search_worker.arn
  batch_size       = 1

  scaling_config {
    maximum_concurrency = var.youtube_search_max_concurrency
  }
}

# One batch an hour, newest releases first; the rule is the queue's only
# producer (no post-ingest start, no self-chaining).
resource "aws_cloudwatch_event_rule" "youtube_search_hourly" {
  name                = "${local.name_prefix}-youtube-search-hourly"
  schedule_expression = "rate(1 hour)"
}

resource "aws_cloudwatch_event_target" "youtube_search_hourly" {
  rule      = aws_cloudwatch_event_rule.youtube_search_hourly.name
  target_id = "youtube-search"
  arn       = aws_sqs_queue.youtube_search.arn
  input     = jsonencode({ batch_size = var.youtube_search_batch_size })
}

resource "aws_sqs_queue_policy" "youtube_search" {
  queue_url = aws_sqs_queue.youtube_search.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "events.amazonaws.com" }
      Action    = "sqs:SendMessage"
      Resource  = aws_sqs_queue.youtube_search.arn
      Condition = { ArnEquals = { "aws:SourceArn" = aws_cloudwatch_event_rule.youtube_search_hourly.arn } }
    }]
  })
}

# ── Vendor Match worker ──────────────────────────────────────────

resource "aws_lambda_function" "vendor_match_worker" {
  function_name = local.vendor_match_worker_lambda_name
  role          = module.role_vendor_match_worker.arn
  runtime       = "python3.12"
  handler       = "collector.vendor_match_handler.lambda_handler"
  filename      = local.lambda_zip_file
  timeout       = var.vendor_match_worker_lambda_timeout_seconds
  memory_size   = var.vendor_match_worker_lambda_memory_mb

  reserved_concurrent_executions = var.enable_lambda_reserved_concurrency ? var.vendor_match_worker_reserved_concurrency : -1

  source_code_hash = filebase64sha256(local.lambda_zip_file)

  environment {
    variables = {
      SPOTIFY_CREDENTIALS_SECRET_ARN      = var.spotify_credentials_secret_arn
      SPOTIFY_CLIENT_ID_SSM_PARAMETER     = var.spotify_client_id_ssm_parameter
      SPOTIFY_CLIENT_SECRET_SSM_PARAMETER = var.spotify_client_secret_ssm_parameter
      AURORA_CLUSTER_ARN                  = aws_rds_cluster.aurora.arn
      AURORA_SECRET_ARN                   = try(aws_rds_cluster.aurora.master_user_secret[0].secret_arn, "")
      AURORA_DATABASE                     = var.aurora_database_name
      LOG_LEVEL                           = "INFO"
      VENDORS_ENABLED                     = var.vendor_match_vendors_enabled
      FUZZY_MATCH_THRESHOLD               = tostring(var.fuzzy_match_threshold)
      FUZZY_DURATION_TOLERANCE_MS         = tostring(var.fuzzy_duration_tolerance_ms)
      COMMENT_COLLECT_QUEUE_URL           = aws_sqs_queue.comments_collect.url
    }
  }

  depends_on = [
    aws_cloudwatch_log_group.vendor_match_worker,
  ]
}

resource "aws_lambda_event_source_mapping" "vendor_match_queue" {
  event_source_arn = aws_sqs_queue.vendor_match.arn
  function_name    = aws_lambda_function.vendor_match_worker.arn
  batch_size       = var.vendor_match_batch_size
  enabled          = var.vendor_match_enabled

  scaling_config {
    maximum_concurrency = var.vendor_match_max_concurrency
  }
}

# ── Label enrichment worker ──────────────────────────────────────

resource "aws_lambda_function" "label_enricher_worker" {
  function_name = local.label_enrichment_worker_lambda_name
  role          = module.role_label_enricher_worker.arn
  runtime       = "python3.12"
  handler       = "collector.label_enrichment_handler.lambda_handler"
  filename      = local.lambda_zip_file
  timeout       = var.label_enrichment_worker_lambda_timeout_seconds
  memory_size   = var.label_enrichment_worker_lambda_memory_mb

  reserved_concurrent_executions = var.enable_lambda_reserved_concurrency ? var.label_enrichment_worker_reserved_concurrency : -1

  source_code_hash = filebase64sha256(local.lambda_zip_file)

  environment {
    variables = {
      GEMINI_API_KEY_SSM_PARAMETER   = var.gemini_api_key_ssm_parameter
      OPENAI_API_KEY_SSM_PARAMETER   = var.openai_api_key_ssm_parameter
      TAVILY_API_KEY_SSM_PARAMETER   = var.tavily_api_key_ssm_parameter
      DEEPSEEK_API_KEY_SSM_PARAMETER = var.deepseek_api_key_ssm_parameter
      LABEL_ENRICHMENT_QUEUE_URL     = aws_sqs_queue.label_enrichment.url
      OPENAI_MAX_TOOL_CALLS          = tostring(var.openai_max_tool_calls)
      AI_FLAG_CONFIDENCE_THRESHOLD   = tostring(var.ai_flag_confidence_threshold)
      AURORA_CLUSTER_ARN             = aws_rds_cluster.aurora.arn
      AURORA_SECRET_ARN              = try(aws_rds_cluster.aurora.master_user_secret[0].secret_arn, "")
      AURORA_DATABASE                = var.aurora_database_name
      LOG_LEVEL                      = "INFO"
    }
  }

  depends_on = [
    aws_cloudwatch_log_group.label_enricher_worker,
  ]
}

resource "aws_lambda_event_source_mapping" "label_enrichment_queue" {
  event_source_arn = aws_sqs_queue.label_enrichment.arn
  function_name    = aws_lambda_function.label_enricher_worker.arn
  batch_size       = var.label_enrichment_batch_size

  # Cap the worker's SQS-driven parallelism so a label batch can't monopolise
  # the account ConcurrentExecutions pool and starve interactive Lambdas
  # (auth/login). Unlike reserved_concurrent_executions, this does NOT reserve
  # from the account pool, so it works even on the low new-account quota (10).
  scaling_config {
    maximum_concurrency = var.label_enrichment_worker_max_concurrency
  }
}

# ── Artist enrichment worker ─────────────────────────────────────

resource "aws_lambda_function" "artist_enricher_worker" {
  function_name = local.artist_enrichment_worker_lambda_name
  role          = module.role_artist_enricher_worker.arn
  runtime       = "python3.12"
  handler       = "collector.artist_enrichment_handler.lambda_handler"
  filename      = local.lambda_zip_file
  timeout       = var.artist_enrichment_worker_lambda_timeout_seconds
  memory_size   = var.artist_enrichment_worker_lambda_memory_mb

  reserved_concurrent_executions = var.enable_lambda_reserved_concurrency ? var.artist_enrichment_worker_reserved_concurrency : -1

  source_code_hash = filebase64sha256(local.lambda_zip_file)

  environment {
    variables = {
      GEMINI_API_KEY_SSM_PARAMETER   = var.gemini_api_key_ssm_parameter
      OPENAI_API_KEY_SSM_PARAMETER   = var.openai_api_key_ssm_parameter
      TAVILY_API_KEY_SSM_PARAMETER   = var.tavily_api_key_ssm_parameter
      DEEPSEEK_API_KEY_SSM_PARAMETER = var.deepseek_api_key_ssm_parameter
      ARTIST_ENRICHMENT_QUEUE_URL    = aws_sqs_queue.artist_enrichment.url
      OPENAI_MAX_TOOL_CALLS          = tostring(var.openai_max_tool_calls)
      AI_FLAG_CONFIDENCE_THRESHOLD   = tostring(var.ai_flag_confidence_threshold)
      AURORA_CLUSTER_ARN             = aws_rds_cluster.aurora.arn
      AURORA_SECRET_ARN              = try(aws_rds_cluster.aurora.master_user_secret[0].secret_arn, "")
      AURORA_DATABASE                = var.aurora_database_name
      LOG_LEVEL                      = "INFO"
    }
  }

  depends_on = [
    aws_cloudwatch_log_group.artist_enricher_worker,
  ]
}

resource "aws_lambda_event_source_mapping" "artist_enrichment_queue" {
  event_source_arn = aws_sqs_queue.artist_enrichment.arn
  function_name    = aws_lambda_function.artist_enricher_worker.arn
  batch_size       = var.artist_enrichment_batch_size

  # Cap the worker's SQS-driven parallelism so an artist batch can't monopolise
  # the account ConcurrentExecutions pool and starve interactive Lambdas
  # (auth/login). Unlike reserved_concurrent_executions, this does NOT reserve
  # from the account pool, so it works even on the low new-account quota (10).
  scaling_config {
    maximum_concurrency = var.artist_enrichment_worker_max_concurrency
  }
}

# ── Auto-enrich dispatch worker ──────────────────────────────────

resource "aws_lambda_function" "auto_enrich_dispatch_worker" {
  function_name = local.auto_enrich_dispatch_worker_lambda_name
  role          = module.role_auto_enrich_dispatch_worker.arn
  runtime       = "python3.12"
  handler       = "collector.auto_enrich_dispatch_handler.lambda_handler"
  filename      = local.lambda_zip_file
  timeout       = var.auto_enrich_dispatch_worker_lambda_timeout_seconds
  memory_size   = var.auto_enrich_dispatch_worker_lambda_memory_mb

  source_code_hash = filebase64sha256(local.lambda_zip_file)

  environment {
    variables = {
      AURORA_CLUSTER_ARN          = aws_rds_cluster.aurora.arn
      AURORA_SECRET_ARN           = try(aws_rds_cluster.aurora.master_user_secret[0].secret_arn, "")
      AURORA_DATABASE             = var.aurora_database_name
      LABEL_ENRICHMENT_QUEUE_URL  = aws_sqs_queue.label_enrichment.url
      ARTIST_ENRICHMENT_QUEUE_URL = aws_sqs_queue.artist_enrichment.url
      COMMENT_COLLECT_QUEUE_URL   = aws_sqs_queue.comments_collect.url
      LOG_LEVEL                   = "INFO"
    }
  }

  depends_on = [
    aws_cloudwatch_log_group.auto_enrich_dispatch_worker,
  ]
}

resource "aws_lambda_event_source_mapping" "auto_enrich_dispatch_queue" {
  event_source_arn = aws_sqs_queue.auto_enrich_dispatch.arn
  function_name    = aws_lambda_function.auto_enrich_dispatch_worker.arn
  batch_size       = var.auto_enrich_dispatch_batch_size

  scaling_config {
    maximum_concurrency = var.auto_enrich_dispatch_worker_max_concurrency
  }
}

# ── Comments collect worker ──────────────────────────────────────

# Shared developer key for the YouTube Data API v3 comment provider.
resource "aws_lambda_function" "comments_collect_worker" {
  function_name = local.comments_collect_worker_lambda_name
  role          = module.role_comments_collect_worker.arn
  runtime       = "python3.12"
  handler       = "collector.comments_collect_handler.lambda_handler"
  filename      = local.lambda_zip_file
  timeout       = var.comments_collect_worker_lambda_timeout_seconds
  memory_size   = var.comments_collect_worker_lambda_memory_mb

  source_code_hash = filebase64sha256(local.lambda_zip_file)

  environment {
    variables = {
      AURORA_CLUSTER_ARN            = aws_rds_cluster.aurora.arn
      AURORA_SECRET_ARN             = try(aws_rds_cluster.aurora.master_user_secret[0].secret_arn, "")
      AURORA_DATABASE               = var.aurora_database_name
      COMMENT_PLATFORMS_ENABLED     = "youtube"
      YOUTUBE_API_KEY_SSM_PARAMETER = var.youtube_api_key_ssm_parameter
      LOG_LEVEL                     = "INFO"
    }
  }

  depends_on = [
    aws_cloudwatch_log_group.comments_collect_worker,
  ]
}

resource "aws_lambda_event_source_mapping" "comments_collect_queue" {
  event_source_arn = aws_sqs_queue.comments_collect.arn
  function_name    = aws_lambda_function.comments_collect_worker.arn
  batch_size       = var.comments_collect_batch_size

  # A block finalize enqueues a comment collection per track (131 on 2026-10-11);
  # uncapped, they took every slot in the account and the API answered 5xx.
  scaling_config {
    maximum_concurrency = var.comments_collect_max_concurrency
  }
}

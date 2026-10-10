# ── Execution roles: one per Lambda (least privilege) ──
# Replaces the shared collector role. Each role gets its own log group and only the
# statements its code and env use (matrix: tests/unit/test_iam_per_function_infra.py).
# Functions that already had their own role (auto-ingest, backfill, data-quality,
# catalog-export, analytics, telemetry, authorizer) are unchanged.

locals {
  ssm_parameter_arn = "arn:aws:ssm:${var.aws_region}:${data.aws_caller_identity.current.account_id}:parameter"

  st_data_api = {
    sid = "DataApi"
    actions = [
      "rds-data:BeginTransaction",
      "rds-data:CommitTransaction",
      "rds-data:RollbackTransaction",
      "rds-data:ExecuteStatement",
      "rds-data:BatchExecuteStatement",
    ]
    resources = [aws_rds_cluster.aurora.arn]
  }
  st_db_secret = {
    sid       = "DatabaseSecret"
    actions   = ["secretsmanager:GetSecretValue"]
    resources = [try(aws_rds_cluster.aurora.master_user_secret[0].secret_arn, "*")]
  }
  st_ssm_kms = {
    sid       = "SsmSecureStringDecrypt"
    actions   = ["kms:Decrypt"]
    resources = ["arn:aws:kms:${var.aws_region}:${data.aws_caller_identity.current.account_id}:alias/aws/ssm"]
  }
  st_user_tokens = {
    sid       = "UserTokensKey"
    actions   = ["kms:GenerateDataKey", "kms:Decrypt"]
    resources = [aws_kms_key.user_tokens.arn]
  }
  # What an SQS event source mapping needs on the queue it polls.
  sqs_consume = [
    "sqs:ReceiveMessage",
    "sqs:DeleteMessage",
    "sqs:ChangeMessageVisibility",
    "sqs:GetQueueAttributes",
  ]
}

module "role_collector" {
  source             = "./modules/lambda_role"
  name               = "${local.name_prefix}-collector-api-role"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
  log_group_arn      = aws_cloudwatch_log_group.collector.arn
  statements = [
    local.st_data_api,
    local.st_db_secret,
    { sid = "WriteRawReleases", actions = ["s3:PutObject"], resources = ["${aws_s3_bucket.raw.arn}/${var.raw_prefix}/*"] },
    {
      sid     = "EnqueueWork"
      actions = ["sqs:SendMessage"]
      resources = [
        aws_sqs_queue.canonicalization.arn,
        aws_sqs_queue.spotify_search.arn,
        aws_sqs_queue.label_enrichment.arn,
        aws_sqs_queue.artist_enrichment.arn,
      ]
    },
    { sid = "InvokeAutoIngest", actions = ["lambda:InvokeFunction"], resources = [aws_lambda_function.auto_ingest.arn] },
    local.st_ssm_kms,
    {
      sid     = "ReadBeatportCredentials"
      actions = ["ssm:GetParameter"]
      resources = [for p in [local.beatport_username_ssm, local.beatport_password_ssm] :
      "arn:aws:ssm:${var.aws_region}:${data.aws_caller_identity.current.account_id}:parameter${p}"]
    },
  ]
}

module "role_curation" {
  source             = "./modules/lambda_role"
  name               = "${local.name_prefix}-curation-role"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
  log_group_arn      = aws_cloudwatch_log_group.curation.arn
  statements = [
    local.st_data_api,
    local.st_db_secret,
    local.st_user_tokens,
    local.st_ssm_kms,
    # Playlist covers: presigned upload/download, head, read for publishing.
    { sid = "PlaylistCovers", actions = ["s3:PutObject", "s3:GetObject"], resources = ["${aws_s3_bucket.raw.arn}/covers/*"] },
    {
      # Kept from the old shared policy (prefix-limited): lets S3 report a missing key as such.
      sid         = "ListCovers"
      actions     = ["s3:ListBucket"]
      resources   = [aws_s3_bucket.raw.arn]
      s3_prefixes = ["covers/*"]
    },
    {
      sid     = "EnqueueWork"
      actions = ["sqs:SendMessage"]
      resources = [
        aws_sqs_queue.label_enrichment.arn,
        aws_sqs_queue.artist_enrichment.arn,
        aws_sqs_queue.vendor_match.arn,
        aws_sqs_queue.auto_enrich_dispatch.arn,
        aws_sqs_queue.comments_collect.arn,
      ]
    },
    {
      sid     = "OAuthClientParameters"
      actions = ["ssm:GetParameter"]
      resources = [for p in compact([
        var.spotify_client_id_ssm_parameter, var.spotify_client_secret_ssm_parameter,
        var.ytmusic_client_id_ssm_parameter, var.ytmusic_client_secret_ssm_parameter,
      ]) : "${local.ssm_parameter_arn}${p}"]
    },
  ]
}

module "role_auth_handler" {
  source             = "./modules/lambda_role"
  name               = "${local.name_prefix}-auth-handler-role"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
  log_group_arn      = aws_cloudwatch_log_group.auth_handler.arn
  statements = [
    local.st_data_api,
    local.st_db_secret,
    local.st_user_tokens,
    local.st_ssm_kms,
    {
      sid     = "AuthParameters"
      actions = ["ssm:GetParameter"]
      resources = [for p in compact([
        var.jwt_signing_key_ssm_parameter,
        var.spotify_client_id_ssm_parameter, var.spotify_client_secret_ssm_parameter,
        var.ytmusic_client_id_ssm_parameter, var.ytmusic_client_secret_ssm_parameter,
      ]) : "${local.ssm_parameter_arn}${p}"]
    },
  ]
}

module "role_canonicalization_worker" {
  source             = "./modules/lambda_role"
  name               = "${local.name_prefix}-canonicalization-worker-role"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
  log_group_arn      = aws_cloudwatch_log_group.canonicalization_worker.arn
  statements = [
    local.st_data_api,
    local.st_db_secret,
    # Reads raw snapshots, writes quarantined records under the same prefix.
    { sid = "RawReleases", actions = ["s3:GetObject", "s3:PutObject"], resources = ["${aws_s3_bucket.raw.arn}/${var.raw_prefix}/*"] },
    { sid = "ListRawReleases", actions = ["s3:ListBucket"], resources = [aws_s3_bucket.raw.arn], s3_prefixes = ["${var.raw_prefix}/*"] },
    { sid = "ConsumeCanonicalization", actions = local.sqs_consume, resources = [aws_sqs_queue.canonicalization.arn] },
    { sid = "EnqueueSpotifySearch", actions = ["sqs:SendMessage"], resources = [aws_sqs_queue.spotify_search.arn] },
  ]
}

module "role_spotify_search_worker" {
  source             = "./modules/lambda_role"
  name               = "${local.name_prefix}-spotify-search-worker-role"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
  log_group_arn      = aws_cloudwatch_log_group.spotify_search_worker.arn
  statements = [
    local.st_data_api,
    local.st_db_secret,
    local.st_ssm_kms,
    { sid = "WriteSpotifyResults", actions = ["s3:PutObject"], resources = ["${aws_s3_bucket.raw.arn}/${var.spotify_raw_prefix}/*"] },
    { sid = "ConsumeSpotifySearch", actions = local.sqs_consume, resources = [aws_sqs_queue.spotify_search.arn] },
    { sid = "RequeueSpotifySearch", actions = ["sqs:SendMessage"], resources = [aws_sqs_queue.spotify_search.arn] },
    {
      sid     = "SpotifyClientParameters"
      actions = ["ssm:GetParameter"]
      resources = [for p in compact([var.spotify_client_id_ssm_parameter, var.spotify_client_secret_ssm_parameter]) :
      "${local.ssm_parameter_arn}${p}"]
    },
    { sid = "SpotifyCredentialsSecret", actions = ["secretsmanager:GetSecretValue"], resources = compact([var.spotify_credentials_secret_arn]) },
  ]
}

module "role_vendor_match_worker" {
  source             = "./modules/lambda_role"
  name               = "${local.name_prefix}-vendor-match-worker-role"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
  log_group_arn      = aws_cloudwatch_log_group.vendor_match_worker.arn
  statements = [
    local.st_data_api,
    local.st_db_secret,
    local.st_ssm_kms,
    { sid = "ConsumeVendorMatch", actions = local.sqs_consume, resources = [aws_sqs_queue.vendor_match.arn] },
    { sid = "EnqueueComments", actions = ["sqs:SendMessage"], resources = [aws_sqs_queue.comments_collect.arn] },
    {
      sid     = "SpotifyClientParameters"
      actions = ["ssm:GetParameter"]
      resources = [for p in compact([var.spotify_client_id_ssm_parameter, var.spotify_client_secret_ssm_parameter]) :
      "${local.ssm_parameter_arn}${p}"]
    },
    { sid = "SpotifyCredentialsSecret", actions = ["secretsmanager:GetSecretValue"], resources = compact([var.spotify_credentials_secret_arn]) },
  ]
}

module "role_label_enricher_worker" {
  source             = "./modules/lambda_role"
  name               = "${local.name_prefix}-label-enricher-worker-role"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
  log_group_arn      = aws_cloudwatch_log_group.label_enricher_worker.arn
  statements = [
    local.st_data_api,
    local.st_db_secret,
    local.st_ssm_kms,
    { sid = "ConsumeLabelEnrichment", actions = local.sqs_consume, resources = [aws_sqs_queue.label_enrichment.arn] },
    { sid = "RequeueLabelEnrichment", actions = ["sqs:SendMessage"], resources = [aws_sqs_queue.label_enrichment.arn] },
    {
      sid     = "VendorApiKeys"
      actions = ["ssm:GetParameter"]
      resources = [for p in compact([
        var.gemini_api_key_ssm_parameter, var.openai_api_key_ssm_parameter,
        var.tavily_api_key_ssm_parameter, var.deepseek_api_key_ssm_parameter,
      ]) : "${local.ssm_parameter_arn}${p}"]
    },
  ]
}

module "role_artist_enricher_worker" {
  source             = "./modules/lambda_role"
  name               = "${local.name_prefix}-artist-enricher-worker-role"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
  log_group_arn      = aws_cloudwatch_log_group.artist_enricher_worker.arn
  statements = [
    local.st_data_api,
    local.st_db_secret,
    local.st_ssm_kms,
    { sid = "ConsumeArtistEnrichment", actions = local.sqs_consume, resources = [aws_sqs_queue.artist_enrichment.arn] },
    { sid = "RequeueArtistEnrichment", actions = ["sqs:SendMessage"], resources = [aws_sqs_queue.artist_enrichment.arn] },
    {
      sid     = "VendorApiKeys"
      actions = ["ssm:GetParameter"]
      resources = [for p in compact([
        var.gemini_api_key_ssm_parameter, var.openai_api_key_ssm_parameter,
        var.tavily_api_key_ssm_parameter, var.deepseek_api_key_ssm_parameter,
      ]) : "${local.ssm_parameter_arn}${p}"]
    },
  ]
}

module "role_auto_enrich_dispatch_worker" {
  source             = "./modules/lambda_role"
  name               = "${local.name_prefix}-auto-enrich-dispatch-worker-role"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
  log_group_arn      = aws_cloudwatch_log_group.auto_enrich_dispatch_worker.arn
  statements = [
    local.st_data_api,
    local.st_db_secret,
    { sid = "ConsumeDispatch", actions = local.sqs_consume, resources = [aws_sqs_queue.auto_enrich_dispatch.arn] },
    {
      sid     = "EnqueueEnrichment"
      actions = ["sqs:SendMessage"]
      resources = [
        aws_sqs_queue.label_enrichment.arn,
        aws_sqs_queue.artist_enrichment.arn,
        aws_sqs_queue.comments_collect.arn,
      ]
    },
  ]
}

module "role_comments_collect_worker" {
  source             = "./modules/lambda_role"
  name               = "${local.name_prefix}-comments-collect-worker-role"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
  log_group_arn      = aws_cloudwatch_log_group.comments_collect_worker.arn
  statements = [
    local.st_data_api,
    local.st_db_secret,
    local.st_ssm_kms,
    { sid = "ConsumeComments", actions = local.sqs_consume, resources = [aws_sqs_queue.comments_collect.arn] },
    {
      sid       = "YouTubeApiKey"
      actions   = ["ssm:GetParameter"]
      resources = [for p in compact([var.youtube_api_key_ssm_parameter]) : "${local.ssm_parameter_arn}${p}"]
    },
  ]
}

module "role_db_migration" {
  source             = "./modules/lambda_role"
  name               = "${local.name_prefix}-db-migration-role"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
  log_group_arn      = aws_cloudwatch_log_group.migration_lambda.arn
  statements = [
    local.st_db_secret,
    {
      sid       = "IamDbConnect"
      actions   = ["rds-db:connect"]
      resources = ["arn:aws:rds-db:${var.aws_region}:${data.aws_caller_identity.current.account_id}:dbuser:${aws_rds_cluster.aurora.cluster_resource_id}/${var.migration_db_user}"]
    },
    {
      # The only function inside the VPC (direct psycopg connection for Alembic).
      sid = "VpcNetworking"
      actions = [
        "ec2:CreateNetworkInterface",
        "ec2:DescribeNetworkInterfaces",
        "ec2:DeleteNetworkInterface",
        "ec2:AssignPrivateIpAddresses",
        "ec2:UnassignPrivateIpAddresses",
      ]
      resources = ["*"]
    },
  ]
}

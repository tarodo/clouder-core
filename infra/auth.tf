# ── KMS CMK for user_vendor_tokens envelope encryption ──────────────

resource "aws_kms_key" "user_tokens" {
  description             = "Envelope encryption for user_vendor_tokens (spec-A)"
  enable_key_rotation     = true
  deletion_window_in_days = 30
}

resource "aws_kms_alias" "user_tokens" {
  name          = "alias/${local.name_prefix}-user-tokens"
  target_key_id = aws_kms_key.user_tokens.key_id
}

# ── SSM SecureString parameters ─────────────────────────────────────

resource "random_password" "jwt_signing_key" {
  length  = 64
  special = false
}

resource "aws_ssm_parameter" "jwt_signing_key" {
  name        = var.jwt_signing_key_ssm_parameter
  description = "HS256 secret used by auth_handler and auth_authorizer (spec-A)"
  type        = "SecureString"
  value       = random_password.jwt_signing_key.result

  lifecycle {
    ignore_changes = [value]
  }
}

# Client_id and client_secret are uploaded out of band (terraform creates
# the parameter shells as empty SecureStrings; operator sets the value
# via `aws ssm put-parameter`). lifecycle.ignore_changes makes terraform
# tolerate the externally-managed value.

resource "aws_ssm_parameter" "spotify_oauth_client_id" {
  name        = var.spotify_oauth_client_id_ssm_parameter
  description = "Spotify OAuth client_id for user login (spec-A)"
  type        = "SecureString"
  value       = "REPLACE_AFTER_APPLY"

  lifecycle {
    ignore_changes = [value]
  }
}

resource "aws_ssm_parameter" "spotify_oauth_client_secret" {
  name        = var.spotify_oauth_client_secret_ssm_parameter
  description = "Spotify OAuth client_secret for user login (spec-A)"
  type        = "SecureString"
  value       = "REPLACE_AFTER_APPLY"

  lifecycle {
    ignore_changes = [value]
  }
}

# ── auth_handler Lambda (reuses collector_lambda role) ──────────────

resource "aws_lambda_function" "auth_handler" {
  function_name = local.auth_handler_lambda_name
  role          = aws_iam_role.collector_lambda.arn
  runtime       = "python3.12"
  handler       = "collector.auth_handler.lambda_handler"
  filename      = local.lambda_zip_file
  timeout       = var.auth_handler_lambda_timeout_seconds
  memory_size   = var.auth_handler_lambda_memory_mb

  source_code_hash = filebase64sha256(local.lambda_zip_file)

  environment {
    variables = {
      AURORA_CLUSTER_ARN                        = aws_rds_cluster.aurora.arn
      AURORA_SECRET_ARN                         = try(aws_rds_cluster.aurora.master_user_secret[0].secret_arn, "")
      AURORA_DATABASE                           = var.aurora_database_name
      KMS_USER_TOKENS_KEY_ARN                   = aws_kms_key.user_tokens.arn
      JWT_SIGNING_KEY_SSM_PARAMETER             = var.jwt_signing_key_ssm_parameter
      SPOTIFY_OAUTH_CLIENT_ID_SSM_PARAMETER     = var.spotify_oauth_client_id_ssm_parameter
      SPOTIFY_OAUTH_CLIENT_SECRET_SSM_PARAMETER = var.spotify_oauth_client_secret_ssm_parameter
      SPOTIFY_OAUTH_REDIRECT_URI                = var.spotify_oauth_redirect_uri
      ALLOWED_FRONTEND_REDIRECTS                = var.allowed_frontend_redirects
      ADMIN_SPOTIFY_IDS                         = var.admin_spotify_ids
      JWT_ACCESS_TOKEN_TTL_SECONDS              = tostring(var.jwt_access_token_ttl_seconds)
      JWT_REFRESH_TOKEN_TTL_SECONDS             = tostring(var.jwt_refresh_token_ttl_seconds)
      LOG_LEVEL                                 = "INFO"
    }
  }

  depends_on = [aws_cloudwatch_log_group.auth_handler]
}

# ── auth_authorizer Lambda (narrower IAM, SSM-only) ─────────────────

resource "aws_iam_role" "auth_authorizer" {
  name               = "${local.name_prefix}-auth-authorizer-role"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
}

data "aws_iam_policy_document" "auth_authorizer" {
  statement {
    sid       = "AllowCloudWatchLogs"
    effect    = "Allow"
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${aws_cloudwatch_log_group.auth_authorizer.arn}:*"]
  }

  statement {
    sid       = "ReadJwtSigningKey"
    effect    = "Allow"
    actions   = ["ssm:GetParameter"]
    resources = ["arn:aws:ssm:${var.aws_region}:${data.aws_caller_identity.current.account_id}:parameter${var.jwt_signing_key_ssm_parameter}"]
  }

  statement {
    sid       = "DecryptSsmParameters"
    effect    = "Allow"
    actions   = ["kms:Decrypt"]
    resources = ["arn:aws:kms:${var.aws_region}:${data.aws_caller_identity.current.account_id}:alias/aws/ssm"]
  }
}

resource "aws_iam_role_policy" "auth_authorizer" {
  name   = "${local.name_prefix}-auth-authorizer-policy"
  role   = aws_iam_role.auth_authorizer.id
  policy = data.aws_iam_policy_document.auth_authorizer.json
}

resource "aws_lambda_function" "auth_authorizer" {
  function_name = local.auth_authorizer_lambda_name
  role          = aws_iam_role.auth_authorizer.arn
  runtime       = "python3.12"
  handler       = "collector.auth_authorizer.lambda_handler"
  filename      = local.lambda_zip_file
  timeout       = var.auth_authorizer_lambda_timeout_seconds
  memory_size   = var.auth_authorizer_lambda_memory_mb

  source_code_hash = filebase64sha256(local.lambda_zip_file)

  environment {
    variables = {
      JWT_SIGNING_KEY_SSM_PARAMETER = var.jwt_signing_key_ssm_parameter
      LOG_LEVEL                     = "INFO"
    }
  }

  depends_on = [aws_cloudwatch_log_group.auth_authorizer]
}

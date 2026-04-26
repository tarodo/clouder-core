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

# Spotify client_id / client_secret are NOT created here.
# Per spec §8.3 a single Spotify Developer app serves both service-mode
# (existing client_credentials grant for ISRC search) and user-mode
# (authorization_code + PKCE for login). The deploy workflow pushes the
# values from GitHub environment secrets into the existing SSM params at
# `var.spotify_client_id_ssm_parameter` / `var.spotify_client_secret_ssm_parameter`,
# and the auth_handler reads from those same names.

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
      SPOTIFY_OAUTH_CLIENT_ID_SSM_PARAMETER     = var.spotify_client_id_ssm_parameter
      SPOTIFY_OAUTH_CLIENT_SECRET_SSM_PARAMETER = var.spotify_client_secret_ssm_parameter
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

resource "aws_lambda_permission" "auth_handler_apigw" {
  statement_id  = "AllowExecutionFromApiGatewayAuth"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.auth_handler.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.collector.execution_arn}/*/*"
}

resource "aws_lambda_permission" "auth_authorizer_apigw" {
  statement_id  = "AllowExecutionFromApiGatewayAuthorizer"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.auth_authorizer.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.collector.execution_arn}/*/*"
}

resource "aws_apigatewayv2_integration" "auth_lambda" {
  api_id                 = aws_apigatewayv2_api.collector.id
  integration_type       = "AWS_PROXY"
  integration_uri        = aws_lambda_function.auth_handler.invoke_arn
  payload_format_version = "2.0"
}

resource "aws_apigatewayv2_authorizer" "jwt" {
  api_id                            = aws_apigatewayv2_api.collector.id
  authorizer_type                   = "REQUEST"
  authorizer_uri                    = aws_lambda_function.auth_authorizer.invoke_arn
  authorizer_payload_format_version = "2.0"
  enable_simple_responses           = true
  identity_sources                  = ["$request.header.Authorization"]
  authorizer_result_ttl_in_seconds  = var.auth_authorizer_cache_ttl_seconds
  name                              = "${local.name_prefix}-jwt-authorizer"
}

# Public routes (no authorizer)

resource "aws_apigatewayv2_route" "auth_login" {
  api_id    = aws_apigatewayv2_api.collector.id
  route_key = "GET /auth/login"
  target    = "integrations/${aws_apigatewayv2_integration.auth_lambda.id}"
}

resource "aws_apigatewayv2_route" "auth_callback" {
  api_id    = aws_apigatewayv2_api.collector.id
  route_key = "GET /auth/callback"
  target    = "integrations/${aws_apigatewayv2_integration.auth_lambda.id}"
}

resource "aws_apigatewayv2_route" "auth_refresh" {
  api_id    = aws_apigatewayv2_api.collector.id
  route_key = "POST /auth/refresh"
  target    = "integrations/${aws_apigatewayv2_integration.auth_lambda.id}"
}

resource "aws_apigatewayv2_route" "auth_logout" {
  api_id    = aws_apigatewayv2_api.collector.id
  route_key = "POST /auth/logout"
  target    = "integrations/${aws_apigatewayv2_integration.auth_lambda.id}"
}

# Authorizer-protected routes that target auth_handler

resource "aws_apigatewayv2_route" "me" {
  api_id             = aws_apigatewayv2_api.collector.id
  route_key          = "GET /me"
  target             = "integrations/${aws_apigatewayv2_integration.auth_lambda.id}"
  authorization_type = "CUSTOM"
  authorizer_id      = aws_apigatewayv2_authorizer.jwt.id
}

resource "aws_apigatewayv2_route" "me_session_revoke" {
  api_id             = aws_apigatewayv2_api.collector.id
  route_key          = "DELETE /me/sessions/{session_id}"
  target             = "integrations/${aws_apigatewayv2_integration.auth_lambda.id}"
  authorization_type = "CUSTOM"
  authorizer_id      = aws_apigatewayv2_authorizer.jwt.id
}

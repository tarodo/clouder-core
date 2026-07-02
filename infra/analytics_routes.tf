# ── analytics-api Lambda (§10 serving) ──────────────────────────────
# Standalone function, dedicated least-privilege role (§13). Shares the one
# collector zip; entry point collector.analytics_handler.lambda_handler.
# Lake bucket / Glue DB / Athena workgroup are provisioned in Increments 2-4
# and referenced here by name. Routes are GET /v1/analytics/* (delivery wired
# in infra/frontend.tf + frontend/vite.config.ts, Task 5).

variable "analytics_lake_bucket" {
  type = string
  # Must match aws_s3_bucket.analytics_lake.bucket in telemetry.tf.
  default = "clouder-prod-analytics-lake"
}

variable "analytics_glue_database" {
  type    = string
  default = "clouder_analytics"
}

variable "athena_workgroup" {
  type    = string
  default = "beatport-prod-analytics"
}

# Dedicated Athena workgroup for the analytics-api (the var above named it but no
# resource created it, so start_query_execution failed with InvalidRequestException).
# enforce=false so the handler's explicit OutputLocation + per-query result reuse apply.
resource "aws_athena_workgroup" "analytics" {
  name          = var.athena_workgroup
  force_destroy = true

  configuration {
    enforce_workgroup_configuration = false
    result_configuration {
      output_location = "s3://${var.analytics_lake_bucket}/athena-results/"
    }
  }
}

variable "analytics_lambda_timeout_seconds" {
  type    = number
  default = 30
}

variable "analytics_lambda_memory_mb" {
  type    = number
  default = 256
}

resource "aws_cloudwatch_log_group" "analytics" {
  name              = "/aws/lambda/${local.name_prefix}-analytics-api"
  retention_in_days = 14
}

resource "aws_iam_role" "analytics_api" {
  name               = "${local.name_prefix}-analytics-api-role"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
}

data "aws_iam_policy_document" "analytics_api" {
  statement {
    sid       = "AllowCloudWatchLogs"
    effect    = "Allow"
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${aws_cloudwatch_log_group.analytics.arn}:*"]
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
    sid    = "GlueReadCatalog"
    effect = "Allow"
    actions = [
      "glue:GetDatabase",
      "glue:GetTable",
      "glue:GetTables",
      "glue:GetPartition",
      "glue:GetPartitions",
    ]
    resources = [
      "arn:aws:glue:${var.aws_region}:${data.aws_caller_identity.current.account_id}:catalog",
      "arn:aws:glue:${var.aws_region}:${data.aws_caller_identity.current.account_id}:database/${var.analytics_glue_database}",
      "arn:aws:glue:${var.aws_region}:${data.aws_caller_identity.current.account_id}:table/${var.analytics_glue_database}/*",
    ]
  }

  statement {
    sid    = "S3ReadGoldAndOps"
    effect = "Allow"
    # GetBucketLocation: Athena verifies the output bucket before writing results.
    actions = ["s3:GetObject", "s3:ListBucket", "s3:GetBucketLocation"]
    resources = [
      "arn:aws:s3:::${var.analytics_lake_bucket}",
      # dbt writes gold/silver table DATA to marts/ (s3_data_dir), not gold/.
      "arn:aws:s3:::${var.analytics_lake_bucket}/marts/*",
      "arn:aws:s3:::${var.analytics_lake_bucket}/gold/*",
      "arn:aws:s3:::${var.analytics_lake_bucket}/bronze/ops/*",
      "arn:aws:s3:::${var.analytics_lake_bucket}/bronze/events/*",
      "arn:aws:s3:::${var.analytics_lake_bucket}/athena-results/*",
    ]
  }

  statement {
    sid       = "S3WriteAthenaResults"
    effect    = "Allow"
    actions   = ["s3:PutObject"]
    resources = ["arn:aws:s3:::${var.analytics_lake_bucket}/athena-results/*"]
  }
}

resource "aws_iam_role_policy" "analytics_api" {
  name   = "${local.name_prefix}-analytics-api-policy"
  role   = aws_iam_role.analytics_api.id
  policy = data.aws_iam_policy_document.analytics_api.json
}

resource "aws_lambda_function" "analytics" {
  function_name = "${local.name_prefix}-analytics-api"
  role          = aws_iam_role.analytics_api.arn
  runtime       = "python3.12"
  handler       = "collector.analytics_handler.lambda_handler"
  filename      = local.lambda_zip_file
  timeout       = var.analytics_lambda_timeout_seconds
  memory_size   = var.analytics_lambda_memory_mb

  source_code_hash = filebase64sha256(local.lambda_zip_file)

  environment {
    variables = {
      ATHENA_DATABASE                = var.analytics_glue_database
      ATHENA_WORKGROUP               = var.athena_workgroup
      ATHENA_OUTPUT_LOCATION         = "s3://${var.analytics_lake_bucket}/athena-results/"
      ANALYTICS_RESULT_REUSE_MINUTES = "60"
      LOG_LEVEL                      = "INFO"
    }
  }

  depends_on = [aws_cloudwatch_log_group.analytics]
}

resource "aws_lambda_permission" "analytics_apigw" {
  statement_id  = "AllowExecutionFromApiGatewayAnalytics"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.analytics.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.collector.execution_arn}/*/*"
}

resource "aws_apigatewayv2_integration" "analytics" {
  api_id                 = aws_apigatewayv2_api.collector.id
  integration_type       = "AWS_PROXY"
  integration_uri        = aws_lambda_function.analytics.invoke_arn
  payload_format_version = "2.0"
}

locals {
  analytics_routes = [
    "GET /v1/analytics/user-daily",
    "GET /v1/analytics/sessions",
  ]
}

resource "aws_apigatewayv2_route" "analytics" {
  for_each = toset(local.analytics_routes)

  api_id    = aws_apigatewayv2_api.collector.id
  route_key = each.key
  target    = "integrations/${aws_apigatewayv2_integration.analytics.id}"

  authorization_type = "CUSTOM"
  authorizer_id      = aws_apigatewayv2_authorizer.jwt.id
}

# ── curation Lambda (spec-C: categories) ───────────────────────────
# Owns user-overlay routes for curation (spec-C now; spec-D/E will append).
# Reuses aws_iam_role.collector_lambda — it already has Aurora Data API +
# Secrets Manager permissions for the master cluster secret.

resource "aws_lambda_function" "curation" {
  function_name = local.curation_lambda_name
  role          = aws_iam_role.collector_lambda.arn
  runtime       = "python3.12"
  handler       = "collector.curation_handler.lambda_handler"
  filename      = local.lambda_zip_file
  timeout       = var.curation_lambda_timeout_seconds
  memory_size   = var.curation_lambda_memory_mb

  source_code_hash = filebase64sha256(local.lambda_zip_file)

  environment {
    variables = {
      AURORA_CLUSTER_ARN = aws_rds_cluster.aurora.arn
      AURORA_SECRET_ARN  = try(aws_rds_cluster.aurora.master_user_secret[0].secret_arn, "")
      AURORA_DATABASE    = var.aurora_database_name
      LOG_LEVEL          = "INFO"
    }
  }

  depends_on = [aws_cloudwatch_log_group.curation]
}

resource "aws_lambda_permission" "curation_apigw" {
  statement_id  = "AllowExecutionFromApiGatewayCuration"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.curation.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.collector.execution_arn}/*/*"
}

resource "aws_apigatewayv2_integration" "curation" {
  api_id                 = aws_apigatewayv2_api.collector.id
  integration_type       = "AWS_PROXY"
  integration_uri        = aws_lambda_function.curation.invoke_arn
  payload_format_version = "2.0"
}

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
      RAW_BUCKET_NAME       = aws_s3_bucket.raw.bucket
      RAW_PREFIX            = var.raw_prefix
      BEATPORT_API_BASE_URL = var.beatport_api_base_url
      LOG_LEVEL             = "INFO"
    }
  }

  depends_on = [
    aws_cloudwatch_log_group.collector,
  ]
}

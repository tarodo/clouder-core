resource "aws_cloudwatch_log_group" "collector" {
  name              = "/aws/lambda/${local.lambda_name}"
  retention_in_days = var.log_retention_days
}

resource "aws_cloudwatch_log_group" "canonicalizer_worker" {
  name              = "/aws/lambda/${local.worker_lambda_name}"
  retention_in_days = var.log_retention_days
}

resource "aws_cloudwatch_log_group" "migration_lambda" {
  name              = "/aws/lambda/${local.migration_lambda_name}"
  retention_in_days = var.log_retention_days
}

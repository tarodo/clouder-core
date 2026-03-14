resource "aws_cloudwatch_log_group" "collector" {
  name              = "/aws/lambda/${local.lambda_name}"
  retention_in_days = var.log_retention_days
}

resource "aws_cloudwatch_log_group" "canonicalization_worker" {
  name              = "/aws/lambda/${local.canonicalization_worker_lambda_name}"
  retention_in_days = var.log_retention_days
}

resource "aws_cloudwatch_log_group" "migration_lambda" {
  name              = "/aws/lambda/${local.migration_lambda_name}"
  retention_in_days = var.log_retention_days
}

resource "aws_cloudwatch_log_group" "ai_search_worker" {
  name              = "/aws/lambda/${local.ai_search_worker_lambda_name}"
  retention_in_days = var.log_retention_days
}

resource "aws_cloudwatch_log_group" "spotify_search_worker" {
  name              = "/aws/lambda/${local.spotify_search_worker_lambda_name}"
  retention_in_days = var.log_retention_days
}

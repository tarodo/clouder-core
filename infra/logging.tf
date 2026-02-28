resource "aws_cloudwatch_log_group" "collector" {
  name              = "/aws/lambda/${local.lambda_name}"
  retention_in_days = var.log_retention_days
}

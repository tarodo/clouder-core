output "api_endpoint" {
  description = "Base URL for API Gateway HTTP API"
  value       = aws_apigatewayv2_stage.default.invoke_url
}

output "collect_route" {
  description = "Collection endpoint"
  value       = "${aws_apigatewayv2_stage.default.invoke_url}/collect_bp_releases"
}

output "raw_bucket_name" {
  description = "S3 bucket that stores raw Beatport snapshots"
  value       = aws_s3_bucket.raw.bucket
}

output "lambda_function_name" {
  description = "Collector Lambda function name"
  value       = aws_lambda_function.collector.function_name
}

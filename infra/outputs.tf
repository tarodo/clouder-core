output "api_endpoint" {
  description = "Base URL for API Gateway HTTP API"
  value       = aws_apigatewayv2_stage.default.invoke_url
}

output "collect_route" {
  description = "Collection endpoint"
  value       = "${aws_apigatewayv2_stage.default.invoke_url}/collect_bp_releases"
}

output "run_status_route" {
  description = "Run status endpoint template"
  value       = "${aws_apigatewayv2_stage.default.invoke_url}/runs/{run_id}"
}

output "raw_bucket_name" {
  description = "S3 bucket that stores raw Beatport snapshots"
  value       = aws_s3_bucket.raw.bucket
}

output "lambda_function_name" {
  description = "Collector Lambda function name"
  value       = aws_lambda_function.collector.function_name
}

output "canonicalization_worker_lambda_function_name" {
  description = "Canonicalization worker Lambda function name"
  value       = aws_lambda_function.canonicalization_worker.function_name
}

output "migration_lambda_function_name" {
  description = "Database migration Lambda function name"
  value       = aws_lambda_function.db_migration.function_name
}

output "canonicalization_queue_url" {
  description = "SQS queue URL for canonicalization tasks"
  value       = aws_sqs_queue.canonicalization.url
}

output "aurora_cluster_arn" {
  description = "Aurora cluster ARN used by Data API"
  value       = aws_rds_cluster.aurora.arn
}

output "aurora_cluster_identifier" {
  description = "Aurora cluster identifier"
  value       = aws_rds_cluster.aurora.cluster_identifier
}

output "aurora_database_name" {
  description = "Aurora database name"
  value       = var.aurora_database_name
}

output "aurora_secret_arn" {
  description = "Secrets Manager ARN with Aurora master credentials"
  value       = try(aws_rds_cluster.aurora.master_user_secret[0].secret_arn, null)
}

output "aurora_writer_endpoint" {
  description = "Aurora writer endpoint for direct SQL migrations"
  value       = aws_rds_cluster.aurora.endpoint
}

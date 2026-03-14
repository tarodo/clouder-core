locals {
  name_prefix                         = "${var.project}-${var.environment}"
  lambda_name                         = "${local.name_prefix}-collector-api"
  canonicalization_worker_lambda_name = "${local.name_prefix}-canonicalization-worker"
  migration_lambda_name               = "${local.name_prefix}-db-migration"
  api_name                            = "${local.name_prefix}-collector-api"
  canonicalization_queue_name         = "${local.name_prefix}-canonicalization"
  canonicalization_dlq_name           = "${local.name_prefix}-canonicalization-dlq"
  ai_search_worker_lambda_name        = "${local.name_prefix}-ai-search-worker"
  ai_search_queue_name                = "${local.name_prefix}-ai-search"
  ai_search_dlq_name                  = "${local.name_prefix}-ai-search-dlq"
  spotify_search_worker_lambda_name   = "${local.name_prefix}-spotify-search-worker"
  spotify_search_queue_name           = "${local.name_prefix}-spotify-search"
  spotify_search_dlq_name             = "${local.name_prefix}-spotify-search-dlq"
  db_cluster_identifier               = "${local.name_prefix}-aurora"
  db_secret_name                      = "${local.name_prefix}-aurora-credentials"
  generated_bucket_name               = "${local.name_prefix}-raw-${data.aws_caller_identity.current.account_id}"
  bucket_name                         = var.raw_bucket_name != "" ? var.raw_bucket_name : local.generated_bucket_name
  lambda_zip_file                     = abspath("${path.module}/../${var.lambda_zip_path}")
}

data "aws_caller_identity" "current" {}

locals {
  name_prefix           = "${var.project}-${var.environment}"
  lambda_name           = "${local.name_prefix}-collector"
  api_name              = "${local.name_prefix}-collector-api"
  generated_bucket_name = "${local.name_prefix}-raw-${data.aws_caller_identity.current.account_id}"
  bucket_name           = var.raw_bucket_name != "" ? var.raw_bucket_name : local.generated_bucket_name
  lambda_zip_file       = abspath("${path.module}/../${var.lambda_zip_path}")
}

data "aws_caller_identity" "current" {}

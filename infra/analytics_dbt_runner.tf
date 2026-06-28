locals {
  dbt_runner_lambda_name = "${local.name_prefix}-dbt-runner"
}

# ── ECR repo (only container-image Lambda in the repo) ──────────────────────

resource "aws_ecr_repository" "dbt_runner" {
  name                 = "${local.name_prefix}-dbt-runner"
  image_tag_mutability = "MUTABLE"
  force_delete         = true
}

# ── CloudWatch log group ─────────────────────────────────────────────────────

resource "aws_cloudwatch_log_group" "dbt_runner" {
  name              = "/aws/lambda/${local.dbt_runner_lambda_name}"
  retention_in_days = var.log_retention_days
}

# ── IAM role: least-privilege (Athena + Glue + lake S3 read/write) ──────────

resource "aws_iam_role" "dbt_runner" {
  name               = "${local.name_prefix}-dbt-runner-role"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
}

data "aws_iam_policy_document" "dbt_runner" {
  statement {
    sid       = "AllowOwnLogs"
    effect    = "Allow"
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${aws_cloudwatch_log_group.dbt_runner.arn}:*"]
  }
  statement {
    sid    = "Athena"
    effect = "Allow"
    actions = [
      "athena:StartQueryExecution", "athena:GetQueryExecution",
      "athena:GetQueryResults", "athena:StopQueryExecution",
      "athena:GetWorkGroup", "athena:GetDataCatalog",
    ]
    resources = ["*"]
  }
  statement {
    sid    = "Glue"
    effect = "Allow"
    actions = [
      "glue:GetDatabase", "glue:GetDatabases", "glue:GetTable", "glue:GetTables",
      "glue:GetPartition", "glue:GetPartitions", "glue:BatchGetPartition",
      "glue:BatchCreatePartition", "glue:CreatePartition", "glue:UpdatePartition",
      "glue:DeletePartition", "glue:BatchDeletePartition",
      "glue:CreateTable", "glue:UpdateTable", "glue:DeleteTable",
      # dbt-athena's incremental (insert_overwrite) strategy manages table versions.
      "glue:GetTableVersion", "glue:GetTableVersions",
      "glue:DeleteTableVersion", "glue:BatchDeleteTableVersion",
    ]
    resources = ["*"]
  }
  statement {
    sid    = "LakeReadWrite"
    effect = "Allow"
    actions = [
      "s3:GetObject", "s3:PutObject", "s3:DeleteObject",
      "s3:ListBucket", "s3:GetBucketLocation",
    ]
    resources = [
      aws_s3_bucket.analytics_lake.arn,
      "${aws_s3_bucket.analytics_lake.arn}/*",
    ]
  }
}

resource "aws_iam_role_policy" "dbt_runner" {
  name   = "${local.name_prefix}-dbt-runner-policy"
  role   = aws_iam_role.dbt_runner.id
  policy = data.aws_iam_policy_document.dbt_runner.json
}

# ── Lambda function (package_type=Image; AWS_REGION auto-injected by runtime) ─
# ponytail: AWS_REGION is a reserved Lambda env key — Terraform rejects it if set.
# profiles.yml reads env_var('AWS_REGION','us-east-1') which the runtime injects.

resource "aws_lambda_function" "dbt_runner" {
  function_name = local.dbt_runner_lambda_name
  role          = aws_iam_role.dbt_runner.arn
  package_type  = "Image"
  image_uri     = "${aws_ecr_repository.dbt_runner.repository_url}:latest"
  timeout       = 900
  memory_size   = 3008

  environment {
    variables = {
      DBT_S3_STAGING_DIR = "s3://${aws_s3_bucket.analytics_lake.bucket}/athena-results/"
      DBT_S3_DATA_DIR    = "s3://${aws_s3_bucket.analytics_lake.bucket}/marts/"
      DBT_LAKE_BUCKET    = aws_s3_bucket.analytics_lake.bucket
      LOG_LEVEL          = "INFO"
    }
  }

  depends_on = [aws_cloudwatch_log_group.dbt_runner]
}

# ── Analytics lakehouse: dbt on Athena, Iceberg silver/gold (docs/data/lakehouse.md) ──
# CodeBuild clones the public repo's main and runs `dbt build`; Step Functions
# starts it nightly after the catalog export (00:00) and the DQ checks (00:10).

locals {
  dbt_project_name   = "${local.name_prefix}-dbt"
  lakehouse_prefix   = "lakehouse"
  account_region     = "${var.aws_region}:${data.aws_caller_identity.current.account_id}"
  glue_catalog_arn   = "arn:aws:glue:${local.account_region}:catalog"
  analytics_lake_arn = aws_s3_bucket.analytics_lake.arn
}

resource "aws_glue_catalog_database" "silver" {
  name = "clouder_silver"
}

resource "aws_glue_catalog_database" "gold" {
  name = "clouder_gold"
}

resource "aws_cloudwatch_log_group" "dbt" {
  name              = "/aws/codebuild/${local.dbt_project_name}"
  retention_in_days = var.log_retention_days
}

data "aws_iam_policy_document" "codebuild_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["codebuild.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "dbt" {
  name               = "${local.name_prefix}-dbt-role"
  assume_role_policy = data.aws_iam_policy_document.codebuild_assume.json
}

data "aws_iam_policy_document" "dbt" {
  statement {
    sid       = "AllowOwnLogs"
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${aws_cloudwatch_log_group.dbt.arn}:*"]
  }
  statement {
    sid = "AllowAthenaQueries"
    actions = [
      "athena:StartQueryExecution",
      "athena:GetQueryExecution",
      "athena:GetQueryResults",
      "athena:StopQueryExecution",
      "athena:GetWorkGroup",
    ]
    resources = ["arn:aws:athena:${local.account_region}:workgroup/${var.athena_workgroup}"]
  }
  statement {
    sid = "AllowReadBronzeCatalog"
    actions = [
      "glue:GetDatabase",
      "glue:GetDatabases",
      "glue:GetTable",
      "glue:GetTables",
      "glue:GetPartition",
      "glue:GetPartitions",
      "glue:BatchGetPartition",
    ]
    resources = [
      local.glue_catalog_arn,
      "arn:aws:glue:${local.account_region}:database/${aws_glue_catalog_database.analytics.name}",
      "arn:aws:glue:${local.account_region}:table/${aws_glue_catalog_database.analytics.name}/*",
    ]
  }
  statement {
    sid = "AllowWriteLakehouseCatalog"
    actions = [
      # dbt-athena runs CREATE SCHEMA IF NOT EXISTS before every build.
      "glue:CreateDatabase",
      "glue:GetDatabase",
      "glue:GetTable",
      "glue:GetTables",
      "glue:CreateTable",
      "glue:UpdateTable",
      "glue:DeleteTable",
      "glue:BatchDeleteTable",
      "glue:GetPartition",
      "glue:GetPartitions",
      "glue:BatchGetPartition",
      "glue:CreatePartition",
      "glue:BatchCreatePartition",
      "glue:UpdatePartition",
      "glue:DeletePartition",
      "glue:BatchDeletePartition",
      "glue:GetTableVersions",
      "glue:DeleteTableVersion",
      "glue:BatchDeleteTableVersion",
    ]
    resources = [
      local.glue_catalog_arn,
      aws_glue_catalog_database.silver.arn,
      aws_glue_catalog_database.gold.arn,
      "arn:aws:glue:${local.account_region}:table/${aws_glue_catalog_database.silver.name}/*",
      "arn:aws:glue:${local.account_region}:table/${aws_glue_catalog_database.gold.name}/*",
    ]
  }
  statement {
    sid       = "AllowListLake"
    actions   = ["s3:ListBucket", "s3:GetBucketLocation"]
    resources = [local.analytics_lake_arn]
  }
  statement {
    sid       = "AllowReadBronze"
    actions   = ["s3:GetObject"]
    resources = ["${local.analytics_lake_arn}/bronze/*"]
  }
  statement {
    sid = "AllowWriteLakehouseAndResults"
    actions = [
      "s3:GetObject",
      "s3:PutObject",
      "s3:DeleteObject",
      "s3:AbortMultipartUpload",
      "s3:ListMultipartUploadParts",
    ]
    resources = [
      "${local.analytics_lake_arn}/${local.lakehouse_prefix}/*",
      "${local.analytics_lake_arn}/athena-results/*",
    ]
  }
}

resource "aws_iam_role_policy" "dbt" {
  name   = "${local.name_prefix}-dbt-policy"
  role   = aws_iam_role.dbt.id
  policy = data.aws_iam_policy_document.dbt.json
}

resource "aws_codebuild_project" "dbt" {
  name          = local.dbt_project_name
  service_role  = aws_iam_role.dbt.arn
  build_timeout = 60

  artifacts {
    type = "NO_ARTIFACTS"
  }

  environment {
    compute_type = "BUILD_GENERAL1_SMALL"
    image        = "aws/codebuild/standard:7.0"
    type         = "LINUX_CONTAINER"

    environment_variable {
      name  = "DBT_TARGET"
      value = "prod"
    }
    environment_variable {
      name  = "DBT_ATHENA_WORKGROUP"
      value = var.athena_workgroup
    }
    environment_variable {
      name  = "DBT_S3_STAGING_DIR"
      value = "s3://${aws_s3_bucket.analytics_lake.bucket}/athena-results/dbt/"
    }
    environment_variable {
      name  = "DBT_S3_DATA_DIR"
      value = "s3://${aws_s3_bucket.analytics_lake.bucket}/${local.lakehouse_prefix}/"
    }
    environment_variable {
      name  = "GIT_REF"
      value = "main"
    }
  }

  logs_config {
    cloudwatch_logs {
      group_name = aws_cloudwatch_log_group.dbt.name
    }
  }

  # Unit tests run in CI on DuckDB; production builds models, data tests and
  # freshness only.
  source {
    type      = "NO_SOURCE"
    buildspec = <<-YAML
      version: 0.2
      phases:
        install:
          runtime-versions:
            python: 3.12
          commands:
            - git clone --depth 1 --branch "$GIT_REF" https://github.com/tarodo/clouder-core.git repo
            - pip install -q -r repo/dbt/requirements.txt
        build:
          # One shell for all commands: change directory once.
          commands:
            - cd repo/dbt
            - DBT_PROFILES_DIR=. dbt build --target prod --exclude-resource-type unit_test
            - DBT_PROFILES_DIR=. dbt source freshness --target prod || true
    YAML
  }
}

data "aws_iam_policy_document" "transform_states_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["states.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "transform_state_machine" {
  name               = "${local.name_prefix}-transform-sfn-role"
  assume_role_policy = data.aws_iam_policy_document.transform_states_assume.json
}

data "aws_iam_policy_document" "transform_state_machine" {
  statement {
    sid       = "AllowRunDbtBuild"
    actions   = ["codebuild:StartBuild", "codebuild:StopBuild", "codebuild:BatchGetBuilds"]
    resources = [aws_codebuild_project.dbt.arn]
  }
  statement {
    sid       = "AllowSyncIntegrationRule"
    actions   = ["events:PutTargets", "events:PutRule", "events:DescribeRule"]
    resources = ["arn:aws:events:${local.account_region}:rule/StepFunctionsGetEventForCodeBuildStartBuildRule"]
  }
}

resource "aws_iam_role_policy" "transform_state_machine" {
  name   = "${local.name_prefix}-transform-sfn-policy"
  role   = aws_iam_role.transform_state_machine.id
  policy = data.aws_iam_policy_document.transform_state_machine.json
}

resource "aws_sfn_state_machine" "transform" {
  name     = "${local.name_prefix}-transform"
  role_arn = aws_iam_role.transform_state_machine.arn
  definition = templatefile("${path.module}/transform.asl.json", {
    dbt_project_name = aws_codebuild_project.dbt.name
  })
}

data "aws_iam_policy_document" "transform_events_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["events.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "transform_events" {
  name               = "${local.name_prefix}-transform-events-role"
  assume_role_policy = data.aws_iam_policy_document.transform_events_assume.json
}

resource "aws_iam_role_policy" "transform_events" {
  name = "${local.name_prefix}-transform-events-policy"
  role = aws_iam_role.transform_events.id
  policy = jsonencode({
    Version   = "2012-10-17"
    Statement = [{ Effect = "Allow", Action = "states:StartExecution", Resource = aws_sfn_state_machine.transform.arn }]
  })
}

# 00:30 UTC: after the catalog export (00:00) and the data-quality checks (00:10).
resource "aws_cloudwatch_event_rule" "transform_nightly" {
  name                = "${local.name_prefix}-transform-nightly"
  schedule_expression = "cron(30 0 * * ? *)"
}

resource "aws_cloudwatch_event_target" "transform_nightly" {
  rule     = aws_cloudwatch_event_rule.transform_nightly.name
  arn      = aws_sfn_state_machine.transform.arn
  role_arn = aws_iam_role.transform_events.arn
}

resource "aws_cloudwatch_metric_alarm" "transform_failed" {
  alarm_name          = "${local.name_prefix}-transform-failed"
  alarm_description   = "Nightly dbt build failed — see docs/data/lakehouse.md"
  namespace           = "AWS/States"
  metric_name         = "ExecutionsFailed"
  dimensions          = { StateMachineArn = aws_sfn_state_machine.transform.arn }
  statistic           = "Sum"
  period              = 86400
  evaluation_periods  = 1
  threshold           = 1
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "notBreaching"

  alarm_actions = var.alarm_sns_topic_arn != "" ? [var.alarm_sns_topic_arn] : []
  ok_actions    = var.alarm_sns_topic_arn != "" ? [var.alarm_sns_topic_arn] : []
}

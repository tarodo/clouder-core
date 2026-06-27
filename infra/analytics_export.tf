locals {
  catalog_export_lambda_name = "${local.name_prefix}-catalog-export"
  ops_log_export_lambda_name = "${local.name_prefix}-ops-log-export"

  # Source log groups ops_log_export reads. MUST include collector-api (source_hint
  # / dispatch surface) and the auto-enrich-dispatch worker, alongside the
  # canonicalization / spotify / vendor / label / artist enricher workers.
  ops_source_log_groups = [
    aws_cloudwatch_log_group.collector.name,
    aws_cloudwatch_log_group.canonicalization_worker.name,
    aws_cloudwatch_log_group.spotify_search_worker.name,
    aws_cloudwatch_log_group.vendor_match_worker.name,
    aws_cloudwatch_log_group.label_enricher_worker.name,
    aws_cloudwatch_log_group.artist_enricher_worker.name,
    aws_cloudwatch_log_group.auto_enrich_dispatch_worker.name,
  ]
  ops_source_log_group_arns = [
    "${aws_cloudwatch_log_group.collector.arn}:*",
    "${aws_cloudwatch_log_group.canonicalization_worker.arn}:*",
    "${aws_cloudwatch_log_group.spotify_search_worker.arn}:*",
    "${aws_cloudwatch_log_group.vendor_match_worker.arn}:*",
    "${aws_cloudwatch_log_group.label_enricher_worker.arn}:*",
    "${aws_cloudwatch_log_group.artist_enricher_worker.arn}:*",
    "${aws_cloudwatch_log_group.auto_enrich_dispatch_worker.arn}:*",
  ]
}

# ── Lightweight Glue tables (types-on-read; dbt builds typed models later) ──

resource "aws_glue_catalog_table" "catalog_export" {
  database_name = aws_glue_catalog_database.analytics.name
  name          = "bronze_catalog_export"
  table_type    = "EXTERNAL_TABLE"

  # ponytail: minimal registration over the NDJSON snapshot prefix; the typed
  # per-dim models are dbt's job (Increment 4). Permissive superset columns —
  # the JSON SerDe null-fills absent keys (schema-on-read).
  parameters = {
    classification                  = "json"
    "projection.enabled"            = "true"
    "projection.snapshot_dt.type"   = "date"
    "projection.snapshot_dt.format" = "yyyy-MM-dd"
    "projection.snapshot_dt.range"  = "2026-01-01,NOW"
    "projection.tbl.type"           = "enum"
    "projection.tbl.values"         = "clouder_tracks,clouder_artists,clouder_track_artists,clouder_labels,clouder_albums,categories,category_tracks"
    "storage.location.template"     = "s3://${aws_s3_bucket.analytics_lake.bucket}/bronze/catalog_export/snapshot_dt=$${snapshot_dt}/$${tbl}"
  }

  partition_keys {
    name = "snapshot_dt"
    type = "string"
  }
  partition_keys {
    name = "tbl"
    type = "string"
  }

  storage_descriptor {
    location      = "s3://${aws_s3_bucket.analytics_lake.bucket}/bronze/catalog_export/"
    input_format  = "org.apache.hadoop.mapred.TextInputFormat"
    output_format = "org.apache.hadoop.hive.ql.io.HiveIgnoreKeyTextOutputFormat"

    ser_de_info {
      serialization_library = "org.openx.data.jsonserde.JsonSerDe"
    }

    columns {
      name = "id"
      type = "string"
    }
    columns {
      name = "title"
      type = "string"
    }
    columns {
      name = "name"
      type = "string"
    }
    columns {
      name = "deleted_at"
      type = "string"
    }
    columns {
      name = "created_at"
      type = "string"
    }
    columns {
      name = "updated_at"
      type = "string"
    }
  }
}

resource "aws_glue_catalog_table" "ops" {
  database_name = aws_glue_catalog_database.analytics.name
  name          = "bronze_ops"
  table_type    = "EXTERNAL_TABLE"

  parameters = {
    classification              = "json"
    "projection.enabled"        = "true"
    "projection.dt.type"        = "date"
    "projection.dt.format"      = "yyyy-MM-dd"
    "projection.dt.range"       = "2026-01-01,NOW"
    "storage.location.template" = "s3://${aws_s3_bucket.analytics_lake.bucket}/bronze/ops/dt=$${dt}"
  }

  partition_keys {
    name = "dt"
    type = "string"
  }

  storage_descriptor {
    location      = "s3://${aws_s3_bucket.analytics_lake.bucket}/bronze/ops/"
    input_format  = "org.apache.hadoop.mapred.TextInputFormat"
    output_format = "org.apache.hadoop.hive.ql.io.HiveIgnoreKeyTextOutputFormat"

    ser_de_info {
      serialization_library = "org.openx.data.jsonserde.JsonSerDe"
    }

    columns {
      name = "timestamp"
      type = "string"
    }
    columns {
      name = "level"
      type = "string"
    }
    columns {
      name = "message"
      type = "string"
    }
    columns {
      name = "duration_ms"
      type = "bigint"
    }
    columns {
      name = "source_hint"
      type = "string"
    }
    columns {
      name = "completed_phases"
      type = "string"
    }
    columns {
      name = "failed_after"
      type = "string"
    }
    columns {
      name = "vendor"
      type = "string"
    }
    columns {
      name = "status_code"
      type = "bigint"
    }
  }
}

# ── Log groups for the two export Lambdas ──

resource "aws_cloudwatch_log_group" "catalog_export" {
  name              = "/aws/lambda/${local.catalog_export_lambda_name}"
  retention_in_days = var.log_retention_days
}

resource "aws_cloudwatch_log_group" "ops_log_export" {
  name              = "/aws/lambda/${local.ops_log_export_lambda_name}"
  retention_in_days = var.log_retention_days
}

# ── catalog_export: own least-privilege role ──
# NOTE: this is a DELIBERATE least-privilege choice. The existing enrichment
# workers reuse the shared collector role (iam.tf, aws_iam_role.collector_lambda);
# these exporters do NOT — each gets its own role so the analytics contour never
# widens the collector's blast radius (spec section 13).

resource "aws_iam_role" "catalog_export" {
  name               = "${local.name_prefix}-catalog-export-role"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
}

data "aws_iam_policy_document" "catalog_export" {
  statement {
    sid       = "AllowOwnLogs"
    effect    = "Allow"
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${aws_cloudwatch_log_group.catalog_export.arn}:*"]
  }
  statement {
    sid    = "AllowRdsDataApiRead"
    effect = "Allow"
    actions = [
      "rds-data:ExecuteStatement",
      "rds-data:BatchExecuteStatement",
    ]
    resources = [aws_rds_cluster.aurora.arn]
  }
  statement {
    sid       = "AllowReadDatabaseSecret"
    effect    = "Allow"
    actions   = ["secretsmanager:GetSecretValue"]
    resources = [try(aws_rds_cluster.aurora.master_user_secret[0].secret_arn, "*")]
  }
  statement {
    sid       = "AllowS3WriteCatalogExport"
    effect    = "Allow"
    actions   = ["s3:PutObject"]
    resources = ["${aws_s3_bucket.analytics_lake.arn}/bronze/catalog_export/*"]
  }
}

resource "aws_iam_role_policy" "catalog_export" {
  name   = "${local.name_prefix}-catalog-export-policy"
  role   = aws_iam_role.catalog_export.id
  policy = data.aws_iam_policy_document.catalog_export.json
}

resource "aws_lambda_function" "catalog_export" {
  function_name    = local.catalog_export_lambda_name
  role             = aws_iam_role.catalog_export.arn
  runtime          = "python3.12"
  handler          = "collector.catalog_export_handler.lambda_handler"
  filename         = local.lambda_zip_file
  timeout          = 300
  memory_size      = 256
  source_code_hash = filebase64sha256(local.lambda_zip_file)

  environment {
    variables = {
      ANALYTICS_LAKE_BUCKET = aws_s3_bucket.analytics_lake.bucket
      AURORA_CLUSTER_ARN    = aws_rds_cluster.aurora.arn
      AURORA_SECRET_ARN     = try(aws_rds_cluster.aurora.master_user_secret[0].secret_arn, "")
      AURORA_DATABASE       = var.aurora_database_name
      LOG_LEVEL             = "INFO"
    }
  }

  depends_on = [aws_cloudwatch_log_group.catalog_export]
}

# ── ops_log_export: own least-privilege role ──

resource "aws_iam_role" "ops_log_export" {
  name               = "${local.name_prefix}-ops-log-export-role"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
}

data "aws_iam_policy_document" "ops_log_export" {
  statement {
    sid       = "AllowOwnLogs"
    effect    = "Allow"
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${aws_cloudwatch_log_group.ops_log_export.arn}:*"]
  }
  statement {
    sid       = "AllowReadSourceLogGroups"
    effect    = "Allow"
    actions   = ["logs:FilterLogEvents"]
    resources = local.ops_source_log_group_arns
  }
  statement {
    sid       = "AllowS3WriteOps"
    effect    = "Allow"
    actions   = ["s3:PutObject"]
    resources = ["${aws_s3_bucket.analytics_lake.arn}/bronze/ops/*"]
  }
}

resource "aws_iam_role_policy" "ops_log_export" {
  name   = "${local.name_prefix}-ops-log-export-policy"
  role   = aws_iam_role.ops_log_export.id
  policy = data.aws_iam_policy_document.ops_log_export.json
}

resource "aws_lambda_function" "ops_log_export" {
  function_name    = local.ops_log_export_lambda_name
  role             = aws_iam_role.ops_log_export.arn
  runtime          = "python3.12"
  handler          = "collector.ops_log_export_handler.lambda_handler"
  filename         = local.lambda_zip_file
  timeout          = 120
  memory_size      = 256
  source_code_hash = filebase64sha256(local.lambda_zip_file)

  environment {
    variables = {
      ANALYTICS_LAKE_BUCKET = aws_s3_bucket.analytics_lake.bucket
      OPS_LOG_GROUPS        = join(",", local.ops_source_log_groups)
      LOG_LEVEL             = "INFO"
    }
  }

  depends_on = [aws_cloudwatch_log_group.ops_log_export]
}

locals {
  catalog_export_lambda_name = "${local.name_prefix}-catalog-export"
}

# ── Lightweight Glue table (types-on-read; Athena casts on read) ──

resource "aws_glue_catalog_table" "catalog_export" {
  database_name = aws_glue_catalog_database.analytics.name
  name          = "bronze_catalog_export"
  table_type    = "EXTERNAL_TABLE"

  # ponytail: minimal registration over the NDJSON snapshot prefix. Permissive
  # superset columns — the JSON SerDe null-fills absent keys (schema-on-read).
  # Analytics joins bronze_events.track_id -> tbl='clouder_tracks' for style_id.
  parameters = {
    classification                  = "json"
    "projection.enabled"            = "true"
    "projection.snapshot_dt.type"   = "date"
    "projection.snapshot_dt.format" = "yyyy-MM-dd"
    "projection.snapshot_dt.range"  = "2026-01-01,NOW"
    "projection.tbl.type"           = "enum"
    "projection.tbl.values"         = "clouder_tracks,clouder_artists,clouder_track_artists,clouder_labels,clouder_albums,categories,category_tracks,clouder_styles"
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
    # --- dim column union so Athena can read per-tbl fields (schema-on-read) ---
    columns {
      name = "bpm"
      type = "string"
    }
    columns {
      name = "key_name"
      type = "string"
    }
    columns {
      name = "key_camelot"
      type = "string"
    }
    columns {
      name = "spotify_release_date"
      type = "string"
    }
    columns {
      name = "publish_date"
      type = "string"
    }
    columns {
      name = "album_id"
      type = "string"
    }
    columns {
      name = "style_id"
      type = "string"
    }
    columns {
      name = "isrc"
      type = "string"
    }
    columns {
      name = "release_type"
      type = "string"
    }
    columns {
      name = "release_date"
      type = "string"
    }
    columns {
      name = "is_ai_suspected"
      type = "string"
    }
    columns {
      name = "origin"
      type = "string"
    }
    columns {
      name = "normalized_name"
      type = "string"
    }
    columns {
      name = "label_id"
      type = "string"
    }
    columns {
      name = "user_id"
      type = "string"
    }
    columns {
      name = "position"
      type = "string"
    }
    columns {
      name = "role"
      type = "string"
    }
    columns {
      name = "track_id"
      type = "string"
    }
    columns {
      name = "artist_id"
      type = "string"
    }
    columns {
      name = "category_id"
      type = "string"
    }
    columns {
      name = "added_at"
      type = "string"
    }
  }
}

# ── Log group for the export Lambda ──

resource "aws_cloudwatch_log_group" "catalog_export" {
  name              = "/aws/lambda/${local.catalog_export_lambda_name}"
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

# ── Nightly snapshot at 00:00 UTC ──
# Track -> style (and the other dims) land in bronze/catalog_export/ so Athena
# can break listening stats down by style. Aurora may be paused at midnight;
# the Data API retry rides out DatabaseResumingException.
resource "aws_cloudwatch_event_rule" "catalog_export_daily" {
  name                = "${local.name_prefix}-catalog-export-daily"
  schedule_expression = "cron(0 0 * * ? *)"
}

resource "aws_cloudwatch_event_target" "catalog_export_daily" {
  rule      = aws_cloudwatch_event_rule.catalog_export_daily.name
  target_id = "catalog-export"
  arn       = aws_lambda_function.catalog_export.arn
}

resource "aws_lambda_permission" "catalog_export_events" {
  statement_id  = "AllowExecutionFromEventBridgeCatalogExport"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.catalog_export.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.catalog_export_daily.arn
}

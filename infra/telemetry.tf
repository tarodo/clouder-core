# ── Analytics lake bucket (medallion: bronze / silver / gold) ────────────────

resource "aws_s3_bucket" "analytics_lake" {
  # PHASE A: set force_destroy on the existing beatport bucket in-place (data is
  # disposable — old bronze unreadable, marts empty). Phase B renames to clouder;
  # the force-replace destroy needs force_destroy already in state. Keep this
  # literal == var.analytics_lake_bucket default.
  bucket        = "beatport-prod-analytics-lake"
  force_destroy = true
}

resource "aws_s3_bucket_public_access_block" "analytics_lake" {
  bucket                  = aws_s3_bucket.analytics_lake.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "analytics_lake" {
  bucket = aws_s3_bucket.analytics_lake.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "analytics_lake" {
  bucket = aws_s3_bucket.analytics_lake.id

  rule {
    id     = "expire-athena-results"
    status = "Enabled"
    filter { prefix = "athena-results/" }
    expiration { days = 7 }
  }

  rule {
    id     = "bronze-to-ia"
    status = "Enabled"
    filter { prefix = "bronze/" }
    transition {
      days          = 90
      storage_class = "STANDARD_IA"
    }
  }
}

# ── Glue Data Catalog: db + bronze events table (partition projection) ────────

resource "aws_glue_catalog_database" "analytics" {
  name = "clouder_analytics"
}

# bronze/events: Firehose format-conversion target. Columns are the JSON->Parquet
# source schema. `dt` + `event_name` are partition keys (NOT data columns), filled
# by Firehose dynamic partitioning. Out of scope here: lightweight Glue tables for
# bronze/catalog_export and bronze/ops — they ship with their producers in
# Increment 3 (no producer exists yet, so no table yet).
resource "aws_glue_catalog_table" "bronze_events" {
  # ponytail: table name = "bronze_events" per locked contract (not "events").
  name          = "bronze_events"
  database_name = aws_glue_catalog_database.analytics.name
  table_type    = "EXTERNAL_TABLE"

  parameters = {
    classification                 = "parquet"
    "projection.enabled"           = "true"
    "projection.dt.type"           = "date"
    "projection.dt.format"         = "yyyy-MM-dd"
    "projection.dt.range"          = "2026-01-01,NOW"
    "projection.dt.interval"       = "1"
    "projection.dt.interval.unit"  = "DAYS"
    "projection.event_name.type"   = "enum"
    "projection.event_name.values" = "triage_session_start,triage_session_end,track_view,track_categorized,playback_play,playback_pause,playback_seek,playback_ended,playback_skip,hotkey_used,playlist_add,playlist_reorder,playlist_publish"
    "storage.location.template"    = "s3://${aws_s3_bucket.analytics_lake.bucket}/bronze/events/dt=$${dt}/event_name=$${event_name}"
  }

  partition_keys {
    name = "dt"
    type = "string"
  }
  partition_keys {
    name = "event_name"
    type = "string"
  }

  storage_descriptor {
    location      = "s3://${aws_s3_bucket.analytics_lake.bucket}/bronze/events/"
    input_format  = "org.apache.hadoop.hive.ql.io.parquet.MapredParquetInputFormat"
    output_format = "org.apache.hadoop.hive.ql.io.parquet.MapredParquetOutputFormat"

    ser_de_info {
      serialization_library = "org.apache.hadoop.hive.ql.io.parquet.serde.ParquetHiveSerDe"
    }

    columns {
      name = "event_id"
      type = "string"
    }
    columns {
      name = "session_id"
      type = "string"
    }
    columns {
      name = "ts_client"
      type = "string"
    }
    columns {
      name = "ts_server"
      type = "string"
    }
    # flattened context (user_id server-stamped)
    columns {
      name = "user_id"
      type = "string"
    }
    columns {
      name = "device"
      type = "string"
    }
    columns {
      name = "route"
      type = "string"
    }
    columns {
      name = "app_version"
      type = "string"
    }
    # hot props: typed, nullable. Absent keys deserialize to null.
    columns {
      name = "track_id"
      type = "string"
    }
    columns {
      name = "source"
      type = "string"
    }
    columns {
      name = "action"
      type = "string"
    }
    columns {
      name = "category_key"
      type = "string"
    }
    columns {
      name = "surface"
      type = "string"
    }
    columns {
      name = "decision_ms"
      type = "bigint"
    }
    columns {
      name = "dwell_ms"
      type = "bigint"
    }
    columns {
      name = "position_ms"
      type = "bigint"
    }
    columns {
      name = "duration_ms"
      type = "bigint"
    }
    columns {
      name = "listen_through_ratio"
      type = "double"
    }
    columns {
      name = "seek_count"
      type = "int"
    }
    columns {
      name = "playlist_id"
      type = "string"
    }
    columns {
      name = "track_count"
      type = "int"
    }
    columns {
      name = "source_category_id"
      type = "string"
    }
    columns {
      name = "session_ms"
      type = "bigint"
    }
    # ponytail: props_extra is the only JSON-string column. Rare/per-event
    # props live here so adding one needs no Glue migration.
    columns {
      name = "props_extra"
      type = "string"
    }
  }
}

# ── Firehose delivery role (S3 write + Glue read for format conversion) ───────

data "aws_iam_policy_document" "firehose_telemetry_assume" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["firehose.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "firehose_telemetry" {
  name               = "${local.name_prefix}-telemetry-firehose-role"
  assume_role_policy = data.aws_iam_policy_document.firehose_telemetry_assume.json
}

data "aws_iam_policy_document" "firehose_telemetry" {
  statement {
    sid    = "WriteLake"
    effect = "Allow"
    actions = [
      "s3:AbortMultipartUpload",
      "s3:GetBucketLocation",
      "s3:GetObject",
      "s3:ListBucket",
      "s3:ListBucketMultipartUploads",
      "s3:PutObject",
    ]
    resources = [
      aws_s3_bucket.analytics_lake.arn,
      "${aws_s3_bucket.analytics_lake.arn}/*",
    ]
  }
  statement {
    sid       = "GlueReadForConversion"
    effect    = "Allow"
    actions   = ["glue:GetTable", "glue:GetTableVersion", "glue:GetTableVersions"]
    resources = ["*"]
  }
  statement {
    sid       = "FirehoseLogs"
    effect    = "Allow"
    actions   = ["logs:PutLogEvents"]
    resources = ["${aws_cloudwatch_log_group.firehose_telemetry.arn}:*"]
  }
}

resource "aws_iam_role_policy" "firehose_telemetry" {
  name   = "${local.name_prefix}-telemetry-firehose-policy"
  role   = aws_iam_role.firehose_telemetry.id
  policy = data.aws_iam_policy_document.firehose_telemetry.json
}

resource "aws_cloudwatch_log_group" "firehose_telemetry" {
  name              = "/aws/kinesisfirehose/${local.name_prefix}-telemetry"
  retention_in_days = var.log_retention_days
}

# ── Firehose Direct PUT: JSON→Parquet, dynamic-partition dt + event_name ──────

resource "aws_kinesis_firehose_delivery_stream" "telemetry" {
  name        = "${local.name_prefix}-telemetry"
  destination = "extended_s3"

  extended_s3_configuration {
    role_arn   = aws_iam_role.firehose_telemetry.arn
    bucket_arn = aws_s3_bucket.analytics_lake.arn

    prefix              = "bronze/events/dt=!{partitionKeyFromQuery:dt}/event_name=!{partitionKeyFromQuery:event_name}/"
    error_output_prefix = "bronze/_errors/!{firehose:error-output-type}/dt=!{timestamp:yyyy-MM-dd}/"

    # ponytail: spec §5.3 INTENT is 5min/5MB to amortise the 5KB-per-record floor.
    # CONSTRAINT: AWS enforces a 64MB buffer FLOOR when BOTH data-format-conversion
    # and dynamic-partitioning are enabled, so 5MB is rejected at apply. 300s/64MB
    # is the smallest legal config; at portfolio volume the 300s timer fires first,
    # so the 5-minute intent is preserved.
    buffering_interval = 300
    buffering_size     = 64

    dynamic_partitioning_configuration {
      enabled = true
    }

    processing_configuration {
      enabled = true
      processors {
        type = "MetadataExtraction"
        parameters {
          parameter_name  = "MetadataExtractionQuery"
          parameter_value = "{dt: .ts_server[0:10], event_name: .event_name}"
        }
        parameters {
          parameter_name  = "JsonParsingEngine"
          parameter_value = "JQ-1.6"
        }
      }
    }

    data_format_conversion_configuration {
      input_format_configuration {
        deserializer {
          open_x_json_ser_de {}
        }
      }
      output_format_configuration {
        serializer {
          parquet_ser_de {}
        }
      }
      schema_configuration {
        database_name = aws_glue_catalog_database.analytics.name
        table_name    = aws_glue_catalog_table.bronze_events.name
        role_arn      = aws_iam_role.firehose_telemetry.arn
        region        = var.aws_region
      }
    }

    cloudwatch_logging_options {
      enabled         = true
      log_group_name  = aws_cloudwatch_log_group.firehose_telemetry.name
      log_stream_name = "S3Delivery"
    }
  }
}

# ── Telemetry Lambda: own least-privilege role (Firehose PutRecordBatch only) ─

resource "aws_iam_role" "telemetry_lambda" {
  name               = "${local.name_prefix}-telemetry-lambda-role"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
}

data "aws_iam_policy_document" "telemetry_lambda" {
  statement {
    sid       = "AllowCloudWatchLogs"
    effect    = "Allow"
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${aws_cloudwatch_log_group.telemetry.arn}:*"]
  }
  statement {
    sid       = "AllowFirehosePut"
    effect    = "Allow"
    actions   = ["firehose:PutRecordBatch"]
    resources = [aws_kinesis_firehose_delivery_stream.telemetry.arn]
  }
}

resource "aws_iam_role_policy" "telemetry_lambda" {
  name   = "${local.name_prefix}-telemetry-lambda-policy"
  role   = aws_iam_role.telemetry_lambda.id
  policy = data.aws_iam_policy_document.telemetry_lambda.json
}

resource "aws_cloudwatch_log_group" "telemetry" {
  name              = "/aws/lambda/${local.telemetry_lambda_name}"
  retention_in_days = var.log_retention_days
}

resource "aws_lambda_function" "telemetry" {
  function_name = local.telemetry_lambda_name
  role          = aws_iam_role.telemetry_lambda.arn
  runtime       = "python3.12"
  handler       = "collector.telemetry_handler.lambda_handler"
  filename      = local.lambda_zip_file
  timeout       = 10
  memory_size   = 256

  source_code_hash = filebase64sha256(local.lambda_zip_file)

  environment {
    variables = {
      TELEMETRY_FIREHOSE_STREAM_NAME = aws_kinesis_firehose_delivery_stream.telemetry.name
      LOG_LEVEL                      = "INFO"
    }
  }

  depends_on = [aws_cloudwatch_log_group.telemetry]
}

# ── API Gateway wiring: own integration + route (CUSTOM authorizer) ───────────

resource "aws_lambda_permission" "telemetry_apigw" {
  statement_id  = "AllowExecutionFromApiGatewayTelemetry"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.telemetry.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.collector.execution_arn}/*/*"
}

resource "aws_apigatewayv2_integration" "telemetry_lambda" {
  api_id                 = aws_apigatewayv2_api.collector.id
  integration_type       = "AWS_PROXY"
  integration_uri        = aws_lambda_function.telemetry.invoke_arn
  payload_format_version = "2.0"
}

resource "aws_apigatewayv2_route" "telemetry_post" {
  api_id             = aws_apigatewayv2_api.collector.id
  route_key          = "POST /v1/telemetry"
  target             = "integrations/${aws_apigatewayv2_integration.telemetry_lambda.id}"
  authorization_type = "CUSTOM"
  authorizer_id      = aws_apigatewayv2_authorizer.jwt.id
}

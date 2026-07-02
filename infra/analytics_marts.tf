resource "aws_glue_catalog_table" "fact_session" {
  name          = "fact_session"
  database_name = aws_glue_catalog_database.analytics.name
  table_type    = "EXTERNAL_TABLE"

  parameters = {
    classification                = "parquet"
    "projection.enabled"          = "true"
    "projection.dt.type"          = "date"
    "projection.dt.format"        = "yyyy-MM-dd"
    "projection.dt.range"         = "2026-01-01,NOW"
    "projection.dt.interval"      = "1"
    "projection.dt.interval.unit" = "DAYS"
    "storage.location.template"   = "s3://${aws_s3_bucket.analytics_lake.bucket}/marts/fact_session/dt=$${dt}"
  }

  partition_keys {
    name = "dt"
    # string, not date: matches bronze_events + the serving layer's string-literal
    # filters; the rollup emits dt as varchar. projection.dt.type stays "date".
    type = "string"
  }

  storage_descriptor {
    location      = "s3://${aws_s3_bucket.analytics_lake.bucket}/marts/fact_session/"
    input_format  = "org.apache.hadoop.hive.ql.io.parquet.MapredParquetInputFormat"
    output_format = "org.apache.hadoop.hive.ql.io.parquet.MapredParquetOutputFormat"

    ser_de_info {
      serialization_library = "org.apache.hadoop.hive.ql.io.parquet.serde.ParquetHiveSerDe"
    }

    columns {
      name = "user_id"
      type = "string"
    }
    columns {
      name = "activity_type"
      type = "string"
    }
    columns {
      name = "session_seq"
      type = "bigint"
    }
    columns {
      name = "ts_start"
      type = "string"
    }
    columns {
      name = "ts_end"
      type = "string"
    }
    columns {
      name = "duration_ms"
      type = "bigint"
    }
    columns {
      name = "tracks_listened"
      type = "bigint"
    }
    columns {
      name = "tracks_promoted"
      type = "bigint"
    }
    columns {
      name = "tracks_deleted"
      type = "bigint"
    }
  }
}

resource "aws_glue_catalog_table" "mart_user_daily" {
  name          = "mart_user_daily"
  database_name = aws_glue_catalog_database.analytics.name
  table_type    = "EXTERNAL_TABLE"

  parameters = {
    classification                = "parquet"
    "projection.enabled"          = "true"
    "projection.dt.type"          = "date"
    "projection.dt.format"        = "yyyy-MM-dd"
    "projection.dt.range"         = "2026-01-01,NOW"
    "projection.dt.interval"      = "1"
    "projection.dt.interval.unit" = "DAYS"
    "storage.location.template"   = "s3://${aws_s3_bucket.analytics_lake.bucket}/marts/mart_user_daily/dt=$${dt}"
  }

  partition_keys {
    name = "dt"
    # string, not date: matches bronze_events + the serving layer's string-literal
    # filters; the rollup emits dt as varchar. projection.dt.type stays "date".
    type = "string"
  }

  storage_descriptor {
    location      = "s3://${aws_s3_bucket.analytics_lake.bucket}/marts/mart_user_daily/"
    input_format  = "org.apache.hadoop.hive.ql.io.parquet.MapredParquetInputFormat"
    output_format = "org.apache.hadoop.hive.ql.io.parquet.MapredParquetOutputFormat"

    ser_de_info {
      serialization_library = "org.apache.hadoop.hive.ql.io.parquet.serde.ParquetHiveSerDe"
    }

    columns {
      name = "user_id"
      type = "string"
    }
    columns {
      name = "activity_type"
      type = "string"
    }
    columns {
      name = "sessions"
      type = "bigint"
    }
    columns {
      name = "avg_tracks_listened"
      type = "double"
    }
    columns {
      name = "avg_tracks_promoted"
      type = "double"
    }
    columns {
      name = "avg_tracks_deleted"
      type = "double"
    }
    columns {
      name = "p50_duration_ms"
      type = "double"
    }
    columns {
      name = "p90_duration_ms"
      type = "double"
    }
    columns {
      name = "p50_time_per_track_ms"
      type = "double"
    }
    columns {
      name = "p90_time_per_track_ms"
      type = "double"
    }
  }
}

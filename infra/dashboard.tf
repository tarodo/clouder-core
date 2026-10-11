# ── Overview dashboard: every signal an alarm watches, on one page ────────────
# Snapshots for the README: scripts/dashboard_snapshots.py.

locals {
  work_queues = {
    canonicalization     = aws_sqs_queue.canonicalization.name
    spotify_search       = aws_sqs_queue.spotify_search.name
    vendor_match         = aws_sqs_queue.vendor_match.name
    label_enrichment     = aws_sqs_queue.label_enrichment.name
    artist_enrichment    = aws_sqs_queue.artist_enrichment.name
    auto_enrich_dispatch = aws_sqs_queue.auto_enrich_dispatch.name
    comments_collect     = aws_sqs_queue.comments_collect.name
  }
  api_dims = ["ApiId", aws_apigatewayv2_api.collector.id, "Stage", aws_apigatewayv2_stage.default.name]

  dashboard_widgets = [
    {
      title   = "Lambda errors"
      stat    = "Sum"
      metrics = [for fn in local.all_lambdas : ["AWS/Lambda", "Errors", "FunctionName", fn]]
    },
    {
      title   = "API 4xx / 5xx"
      stat    = "Sum"
      metrics = [concat(["AWS/ApiGateway", "5xx"], local.api_dims), concat(["AWS/ApiGateway", "4xx"], local.api_dims)]
    },
    {
      title   = "API latency p95 (ms)"
      stat    = "p95"
      metrics = [concat(["AWS/ApiGateway", "Latency"], local.api_dims)]
    },
    {
      title   = "Oldest message age (s)"
      stat    = "Maximum"
      metrics = [for q in local.work_queues : ["AWS/SQS", "ApproximateAgeOfOldestMessage", "QueueName", q]]
    },
    {
      title   = "DLQ depth"
      stat    = "Maximum"
      metrics = [for q in local.dlq_queues : ["AWS/SQS", "ApproximateNumberOfMessagesVisible", "QueueName", q]]
    },
    {
      title   = "Aurora capacity (ACU)"
      stat    = "Maximum"
      metrics = [["AWS/RDS", "ServerlessDatabaseCapacity", "DBClusterIdentifier", aws_rds_cluster.aurora.cluster_identifier]]
    },
    {
      title   = "Failed checks: data quality / auto-ingest"
      stat    = "Maximum"
      metrics = [[local.data_quality_namespace, "FailedChecks"], ["CLOUDER/AutoIngest", "AutoIngestRunFailed"]]
    },
    {
      title   = "Telemetry delivery freshness (s)"
      stat    = "Maximum"
      metrics = [["AWS/Firehose", "DeliveryToS3.DataFreshness", "DeliveryStreamName", aws_kinesis_firehose_delivery_stream.telemetry.name]]
    },
    # Data-quality checks run once a day: a daily period shows one point per run.
    {
      title   = "Data quality: freshness and volume"
      stat    = "Maximum"
      period  = 86400
      metrics = [for m in ["styles_behind", "stuck_ingest_runs", "weekly_volume_anomalies", "spotify_unsearched_stale"] : [local.data_quality_namespace, m]]
    },
    {
      title   = "Data quality: completeness (%)"
      stat    = "Minimum"
      period  = 86400
      metrics = [[local.data_quality_namespace, "isrc_coverage_pct"], [local.data_quality_namespace, "spotify_match_pct"]]
      annotations = { horizontal = [
        { label = "ISRC SLO", value = 99 },
        { label = "Spotify match SLO", value = 95 },
      ] }
    },
    {
      title   = "Data quality: integrity"
      stat    = "Maximum"
      period  = 86400
      metrics = [for m in ["orphan_identities", "bpm_out_of_range", "length_out_of_range"] : [local.data_quality_namespace, m]]
    },
  ]
}

resource "aws_cloudwatch_dashboard" "overview" {
  dashboard_name = "${local.name_prefix}-overview"
  dashboard_body = jsonencode({
    widgets = [
      for i, w in local.dashboard_widgets : {
        type   = "metric"
        x      = (i % 2) * 12
        y      = floor(i / 2) * 6
        width  = 12
        height = 6
        properties = merge({
          title   = w.title
          region  = var.aws_region
          stat    = w.stat
          period  = try(w.period, 300)
          view    = "timeSeries"
          stacked = false
          metrics = w.metrics
        }, try({ annotations = w.annotations }, {}))
      }
    ]
  })
}

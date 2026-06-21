resource "aws_sqs_queue" "canonicalization_dlq" {
  name                      = local.canonicalization_dlq_name
  message_retention_seconds = var.canonicalization_queue_retention_seconds
}

resource "aws_sqs_queue" "canonicalization" {
  name = local.canonicalization_queue_name
  visibility_timeout_seconds = max(
    var.canonicalization_queue_visibility_timeout_seconds,
    var.canonicalization_worker_lambda_timeout_seconds
  )
  message_retention_seconds = var.canonicalization_queue_retention_seconds

  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.canonicalization_dlq.arn
    maxReceiveCount     = 5
  })
}

# ── Spotify Search queue ─────────────────────────────────────────

resource "aws_sqs_queue" "spotify_search_dlq" {
  name                      = local.spotify_search_dlq_name
  message_retention_seconds = var.spotify_search_queue_retention_seconds
}

resource "aws_sqs_queue" "spotify_search" {
  name = local.spotify_search_queue_name
  visibility_timeout_seconds = max(
    var.spotify_search_queue_visibility_timeout_seconds,
    var.spotify_search_worker_lambda_timeout_seconds
  )
  message_retention_seconds = var.spotify_search_queue_retention_seconds

  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.spotify_search_dlq.arn
    maxReceiveCount     = 3
  })
}

# ── Vendor Match queue ───────────────────────────────────────────

resource "aws_sqs_queue" "vendor_match_dlq" {
  name                      = local.vendor_match_dlq_name
  message_retention_seconds = var.vendor_match_queue_retention_seconds
}

resource "aws_sqs_queue" "vendor_match" {
  name = local.vendor_match_queue_name
  visibility_timeout_seconds = max(
    var.vendor_match_queue_visibility_timeout_seconds,
    var.vendor_match_worker_lambda_timeout_seconds
  )
  message_retention_seconds = var.vendor_match_queue_retention_seconds

  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.vendor_match_dlq.arn
    maxReceiveCount     = var.vendor_match_max_receive_count
  })
}

# ── Label Enrichment queue ───────────────────────────────────────

resource "aws_sqs_queue" "label_enrichment_dlq" {
  name                      = local.label_enrichment_dlq_name
  message_retention_seconds = var.label_enrichment_queue_retention_seconds
}

resource "aws_sqs_queue" "label_enrichment" {
  name = local.label_enrichment_queue_name
  visibility_timeout_seconds = max(
    var.label_enrichment_queue_visibility_timeout_seconds,
    var.label_enrichment_worker_lambda_timeout_seconds
  )
  message_retention_seconds = var.label_enrichment_queue_retention_seconds

  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.label_enrichment_dlq.arn
    maxReceiveCount     = var.label_enrichment_queue_max_receive_count
  })
}

# ── Artist Enrichment queue ──────────────────────────────────────

resource "aws_sqs_queue" "artist_enrichment_dlq" {
  name                      = local.artist_enrichment_dlq_name
  message_retention_seconds = var.artist_enrichment_queue_retention_seconds
}

resource "aws_sqs_queue" "artist_enrichment" {
  name = local.artist_enrichment_queue_name
  visibility_timeout_seconds = max(
    var.artist_enrichment_queue_visibility_timeout_seconds,
    var.artist_enrichment_worker_lambda_timeout_seconds
  )
  message_retention_seconds = var.artist_enrichment_queue_retention_seconds

  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.artist_enrichment_dlq.arn
    maxReceiveCount     = var.artist_enrichment_queue_max_receive_count
  })
}

# ── Comments Collect queue ───────────────────────────────────────

resource "aws_sqs_queue" "comments_collect_dlq" {
  name                      = local.comments_collect_dlq_name
  message_retention_seconds = var.comments_collect_queue_retention_seconds
}

resource "aws_sqs_queue" "comments_collect" {
  name = local.comments_collect_queue_name
  visibility_timeout_seconds = max(
    var.comments_collect_queue_visibility_timeout_seconds,
    var.comments_collect_worker_lambda_timeout_seconds
  )
  message_retention_seconds = var.comments_collect_queue_retention_seconds

  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.comments_collect_dlq.arn
    maxReceiveCount     = var.comments_collect_queue_max_receive_count
  })
}

# ── Auto-enrich dispatch queue ───────────────────────────────────

resource "aws_sqs_queue" "auto_enrich_dispatch_dlq" {
  name                      = local.auto_enrich_dispatch_dlq_name
  message_retention_seconds = var.auto_enrich_dispatch_queue_retention_seconds
}

resource "aws_sqs_queue" "auto_enrich_dispatch" {
  name = local.auto_enrich_dispatch_queue_name
  visibility_timeout_seconds = max(
    var.auto_enrich_dispatch_queue_visibility_timeout_seconds,
    var.auto_enrich_dispatch_worker_lambda_timeout_seconds
  )
  message_retention_seconds = var.auto_enrich_dispatch_queue_retention_seconds

  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.auto_enrich_dispatch_dlq.arn
    maxReceiveCount     = var.auto_enrich_dispatch_queue_max_receive_count
  })
}

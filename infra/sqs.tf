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

# ── AI Search queue ──────────────────────────────────────────────

resource "aws_sqs_queue" "ai_search_dlq" {
  name                      = local.ai_search_dlq_name
  message_retention_seconds = var.ai_search_queue_retention_seconds
}

resource "aws_sqs_queue" "ai_search" {
  name = local.ai_search_queue_name
  visibility_timeout_seconds = max(
    var.ai_search_queue_visibility_timeout_seconds,
    var.ai_search_worker_lambda_timeout_seconds
  )
  message_retention_seconds = var.ai_search_queue_retention_seconds

  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.ai_search_dlq.arn
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

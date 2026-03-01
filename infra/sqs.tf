resource "aws_sqs_queue" "canonicalize_dlq" {
  name                      = local.dlq_name
  message_retention_seconds = var.canonicalize_queue_retention_seconds
}

resource "aws_sqs_queue" "canonicalize" {
  name = local.queue_name
  visibility_timeout_seconds = max(
    var.canonicalize_queue_visibility_timeout_seconds,
    var.worker_lambda_timeout_seconds
  )
  message_retention_seconds = var.canonicalize_queue_retention_seconds

  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.canonicalize_dlq.arn
    maxReceiveCount     = 5
  })
}

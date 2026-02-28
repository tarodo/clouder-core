data "aws_iam_policy_document" "lambda_assume" {
  statement {
    sid     = "AllowLambdaServiceAssumeRole"
    effect  = "Allow"
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "collector_lambda" {
  name               = "${local.name_prefix}-collector-lambda-role"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
}

data "aws_iam_policy_document" "collector_lambda" {
  statement {
    sid    = "AllowCloudWatchLogs"
    effect = "Allow"
    actions = [
      "logs:CreateLogStream",
      "logs:PutLogEvents",
    ]
    resources = ["${aws_cloudwatch_log_group.collector.arn}:*"]
  }

  statement {
    sid    = "AllowS3PutObjects"
    effect = "Allow"
    actions = [
      "s3:PutObject",
    ]
    resources = [
      "${aws_s3_bucket.raw.arn}/${var.raw_prefix}/*",
    ]
  }

  statement {
    sid     = "AllowS3ListBucket"
    effect  = "Allow"
    actions = ["s3:ListBucket"]
    resources = [
      aws_s3_bucket.raw.arn,
    ]
    condition {
      test     = "StringLike"
      variable = "s3:prefix"
      values   = ["${var.raw_prefix}/*"]
    }
  }
}

resource "aws_iam_role_policy" "collector_lambda" {
  name   = "${local.name_prefix}-collector-lambda-policy"
  role   = aws_iam_role.collector_lambda.id
  policy = data.aws_iam_policy_document.collector_lambda.json
}

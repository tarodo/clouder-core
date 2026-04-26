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
    resources = [
      "${aws_cloudwatch_log_group.collector.arn}:*",
      "${aws_cloudwatch_log_group.canonicalization_worker.arn}:*",
      "${aws_cloudwatch_log_group.migration_lambda.arn}:*",
      "${aws_cloudwatch_log_group.ai_search_worker.arn}:*",
      "${aws_cloudwatch_log_group.spotify_search_worker.arn}:*",
      "${aws_cloudwatch_log_group.vendor_match_worker.arn}:*",
      "${aws_cloudwatch_log_group.auth_handler.arn}:*",
    ]
  }

  statement {
    sid    = "AllowS3WriteObjects"
    effect = "Allow"
    actions = [
      "s3:PutObject",
    ]
    resources = [
      "${aws_s3_bucket.raw.arn}/${var.raw_prefix}/*",
      "${aws_s3_bucket.raw.arn}/${var.spotify_raw_prefix}/*",
    ]
  }

  statement {
    sid    = "AllowS3ReadObjects"
    effect = "Allow"
    actions = [
      "s3:GetObject",
    ]
    resources = [
      "${aws_s3_bucket.raw.arn}/${var.raw_prefix}/*",
      "${aws_s3_bucket.raw.arn}/${var.spotify_raw_prefix}/*",
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
      values   = ["${var.raw_prefix}/*", "${var.spotify_raw_prefix}/*"]
    }
  }

  statement {
    sid    = "AllowSQSSend"
    effect = "Allow"
    actions = [
      "sqs:SendMessage",
      "sqs:GetQueueAttributes",
      "sqs:GetQueueUrl",
    ]
    resources = [
      aws_sqs_queue.canonicalization.arn,
      aws_sqs_queue.ai_search.arn,
      aws_sqs_queue.spotify_search.arn,
      aws_sqs_queue.vendor_match.arn,
    ]
  }

  statement {
    sid    = "AllowSQSConsume"
    effect = "Allow"
    actions = [
      "sqs:ReceiveMessage",
      "sqs:DeleteMessage",
      "sqs:ChangeMessageVisibility",
      "sqs:GetQueueAttributes",
      "sqs:GetQueueUrl",
    ]
    resources = [
      aws_sqs_queue.canonicalization.arn,
      aws_sqs_queue.ai_search.arn,
      aws_sqs_queue.spotify_search.arn,
      aws_sqs_queue.vendor_match.arn,
    ]
  }

  statement {
    sid    = "AllowRdsDataApi"
    effect = "Allow"
    actions = [
      "rds-data:BeginTransaction",
      "rds-data:CommitTransaction",
      "rds-data:RollbackTransaction",
      "rds-data:ExecuteStatement",
      "rds-data:BatchExecuteStatement",
    ]
    resources = [aws_rds_cluster.aurora.arn]
  }

  statement {
    sid    = "AllowReadDatabaseSecret"
    effect = "Allow"
    actions = [
      "secretsmanager:GetSecretValue",
    ]
    resources = [try(aws_rds_cluster.aurora.master_user_secret[0].secret_arn, "*")]
  }

  dynamic "statement" {
    for_each = length(compact([var.perplexity_api_key_secret_arn, var.spotify_credentials_secret_arn])) > 0 ? [1] : []
    content {
      sid     = "ReadExternalApiSecrets"
      effect  = "Allow"
      actions = ["secretsmanager:GetSecretValue"]
      resources = compact([
        var.perplexity_api_key_secret_arn,
        var.spotify_credentials_secret_arn,
      ])
    }
  }

  dynamic "statement" {
    for_each = length(compact([var.perplexity_api_key_ssm_parameter, var.spotify_client_id_ssm_parameter, var.spotify_client_secret_ssm_parameter])) > 0 ? [1] : []
    content {
      sid     = "AllowReadWorkerSsmParameters"
      effect  = "Allow"
      actions = ["ssm:GetParameter"]
      resources = compact([
        var.perplexity_api_key_ssm_parameter != "" ? "arn:aws:ssm:${var.aws_region}:${data.aws_caller_identity.current.account_id}:parameter${var.perplexity_api_key_ssm_parameter}" : "",
        var.spotify_client_id_ssm_parameter != "" ? "arn:aws:ssm:${var.aws_region}:${data.aws_caller_identity.current.account_id}:parameter${var.spotify_client_id_ssm_parameter}" : "",
        var.spotify_client_secret_ssm_parameter != "" ? "arn:aws:ssm:${var.aws_region}:${data.aws_caller_identity.current.account_id}:parameter${var.spotify_client_secret_ssm_parameter}" : "",
      ])
    }
  }

  dynamic "statement" {
    for_each = length(compact([var.perplexity_api_key_ssm_parameter, var.spotify_client_id_ssm_parameter, var.spotify_client_secret_ssm_parameter])) > 0 ? [1] : []
    content {
      sid       = "AllowWorkerSsmKmsDecrypt"
      effect    = "Allow"
      actions   = ["kms:Decrypt"]
      resources = ["arn:aws:kms:${var.aws_region}:${data.aws_caller_identity.current.account_id}:alias/aws/ssm"]
    }
  }

  statement {
    sid    = "AllowKmsUserTokens"
    effect = "Allow"
    actions = [
      "kms:GenerateDataKey",
      "kms:Decrypt",
    ]
    resources = [aws_kms_key.user_tokens.arn]
  }

  statement {
    sid     = "AllowReadAuthSsmParameters"
    effect  = "Allow"
    actions = ["ssm:GetParameter"]
    resources = [
      "arn:aws:ssm:${var.aws_region}:${data.aws_caller_identity.current.account_id}:parameter${var.jwt_signing_key_ssm_parameter}",
    ]
  }

  statement {
    sid     = "AllowRdsDbConnectForMigration"
    effect  = "Allow"
    actions = ["rds-db:connect"]
    resources = [
      "arn:aws:rds-db:${var.aws_region}:${data.aws_caller_identity.current.account_id}:dbuser:${aws_rds_cluster.aurora.cluster_resource_id}/${var.migration_db_user}"
    ]
  }

  statement {
    sid    = "AllowLambdaVpcNetworking"
    effect = "Allow"
    actions = [
      "ec2:CreateNetworkInterface",
      "ec2:DescribeNetworkInterfaces",
      "ec2:DeleteNetworkInterface",
      "ec2:AssignPrivateIpAddresses",
      "ec2:UnassignPrivateIpAddresses",
    ]
    resources = ["*"]
  }
}

resource "aws_iam_role_policy" "collector_lambda" {
  name   = "${local.name_prefix}-collector-lambda-policy"
  role   = aws_iam_role.collector_lambda.id
  policy = data.aws_iam_policy_document.collector_lambda.json
}

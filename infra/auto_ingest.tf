# ── Auto-ingest (docs/data/auto-ingest.md) ──
# The Beatport credentials come from GitHub secrets through SSM (deploy.yml); the
# token is obtained on every invocation and never stored. No reserved concurrency:
# the account quota is 10 (runbook "Lambda reserved concurrency trip").

locals {
  auto_ingest_lambda_name = "${local.name_prefix}-auto-ingest"
  beatport_username_ssm   = "/clouder/beatport/username"
  beatport_password_ssm   = "/clouder/beatport/password"
}

resource "aws_cloudwatch_log_group" "auto_ingest" {
  name              = "/aws/lambda/${local.auto_ingest_lambda_name}"
  retention_in_days = var.log_retention_days
}

resource "aws_iam_role" "auto_ingest" {
  name               = "${local.name_prefix}-auto-ingest-role"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
}

data "aws_iam_policy_document" "auto_ingest" {
  statement {
    sid       = "AllowOwnLogs"
    effect    = "Allow"
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${aws_cloudwatch_log_group.auto_ingest.arn}:*"]
  }
  statement {
    sid     = "ReadBeatportCredentials"
    effect  = "Allow"
    actions = ["ssm:GetParameter"]
    resources = [
      "arn:aws:ssm:${var.aws_region}:${data.aws_caller_identity.current.account_id}:parameter${local.beatport_username_ssm}",
      "arn:aws:ssm:${var.aws_region}:${data.aws_caller_identity.current.account_id}:parameter${local.beatport_password_ssm}",
    ]
  }
  statement {
    sid       = "DecryptSsmParameters"
    effect    = "Allow"
    actions   = ["kms:Decrypt"]
    resources = ["arn:aws:kms:${var.aws_region}:${data.aws_caller_identity.current.account_id}:alias/aws/ssm"]
  }
}

resource "aws_iam_role_policy" "auto_ingest" {
  name   = "${local.name_prefix}-auto-ingest-policy"
  role   = aws_iam_role.auto_ingest.id
  policy = data.aws_iam_policy_document.auto_ingest.json
}

resource "aws_lambda_function" "auto_ingest" {
  function_name    = local.auto_ingest_lambda_name
  role             = aws_iam_role.auto_ingest.arn
  runtime          = "python3.12"
  handler          = "collector.auto_ingest_handler.lambda_handler"
  filename         = local.lambda_zip_file
  timeout          = 900
  memory_size      = 512
  source_code_hash = filebase64sha256(local.lambda_zip_file)

  environment {
    variables = {
      BEATPORT_USERNAME_SSM_PARAMETER = local.beatport_username_ssm
      BEATPORT_PASSWORD_SSM_PARAMETER = local.beatport_password_ssm
      LOG_LEVEL                       = "INFO"
    }
  }

  depends_on = [aws_cloudwatch_log_group.auto_ingest]
}

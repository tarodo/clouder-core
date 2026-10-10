# ── CI roles (ADR-0028) ──
# Pull requests run `terraform plan` under this read-only role; only pull-request
# jobs of this repository can assume it. The deploy role (admin, created by hand at
# bootstrap, outside this configuration) is trusted only by the `production`
# environment — see docs/ops/deploy.md.

data "aws_iam_policy_document" "gha_plan_assume" {
  statement {
    actions = ["sts:AssumeRoleWithWebIdentity"]

    principals {
      type        = "Federated"
      identifiers = ["arn:aws:iam::${data.aws_caller_identity.current.account_id}:oidc-provider/token.actions.githubusercontent.com"]
    }

    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:aud"
      values   = ["sts.amazonaws.com"]
    }

    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:sub"
      values   = ["repo:${var.github_repository}:pull_request"]
    }
  }
}

resource "aws_iam_role" "gha_plan" {
  name               = "${local.name_prefix}-gha-plan"
  description        = "Read-only terraform plan for pull requests (ADR-0028)"
  assume_role_policy = data.aws_iam_policy_document.gha_plan_assume.json
}

# Planning reads every managed resource and the state (which holds the JWT signing
# key); it never needs to write. The SSM SecureString read works through the
# aws/ssm managed key's own policy.
resource "aws_iam_role_policy_attachment" "gha_plan_read_only" {
  role       = aws_iam_role.gha_plan.name
  policy_arn = "arn:aws:iam::aws:policy/ReadOnlyAccess"
}

# ReadOnlyAccess also reads data: every SecureString (the aws/ssm key lets any principal
# in the account decrypt), S3 objects, logs, queue messages, query results. A plan needs
# none of it — the one secret it reads is the JWT signing key parameter, which
# Terraform manages and the state already holds.
data "aws_iam_policy_document" "gha_plan_no_data" {
  statement {
    sid     = "NoVendorSecrets"
    effect  = "Deny"
    actions = ["ssm:GetParameter", "ssm:GetParameters", "ssm:GetParameterHistory"]
    resources = [
      "${local.ssm_parameter_arn}/clouder/gemini/*",
      "${local.ssm_parameter_arn}/clouder/openai/*",
      "${local.ssm_parameter_arn}/clouder/tavily/*",
      "${local.ssm_parameter_arn}/clouder/deepseek/*",
      "${local.ssm_parameter_arn}/clouder/spotify/*",
      "${local.ssm_parameter_arn}/clouder/ytmusic/*",
      "${local.ssm_parameter_arn}/clouder/youtube/*",
      "${local.ssm_parameter_arn}/clouder/beatport/*",
    ]
  }

  statement {
    sid       = "NoParameterTreeReads"
    effect    = "Deny"
    actions   = ["ssm:GetParametersByPath"]
    resources = ["*"]
  }

  statement {
    sid       = "NoDataObjects"
    effect    = "Deny"
    actions   = ["s3:GetObject", "s3:GetObjectVersion"]
    resources = ["${aws_s3_bucket.raw.arn}/*", "${aws_s3_bucket.analytics_lake.arn}/*"]
  }

  statement {
    sid    = "NoLogsMessagesOrResults"
    effect = "Deny"
    actions = [
      "logs:GetLogEvents",
      "logs:FilterLogEvents",
      "logs:StartQuery",
      "logs:GetQueryResults",
      "logs:StartLiveTail",
      "secretsmanager:GetSecretValue",
      "sqs:ReceiveMessage",
      "athena:GetQueryResults",
    ]
    resources = ["*"]
  }
}

resource "aws_iam_role_policy" "gha_plan_no_data" {
  name   = "${local.name_prefix}-gha-plan-no-data"
  role   = aws_iam_role.gha_plan.id
  policy = data.aws_iam_policy_document.gha_plan_no_data.json
}

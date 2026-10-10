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

# ── Permissions boundary for every role Terraform creates ──
# A ceiling, not a grant: whatever a role's own policy says, it cannot touch IAM (except
# reading it and passing project roles to services), Organizations, the account, or assume
# another role (none of the code does; the account is shared). The
# deploy role may create roles and write their policies only with this boundary on them,
# and cannot change it (infra/bootstrap/deploy-role-policy.json), so it cannot hand itself
# or a Lambda more than this through a project role.
locals {
  role_boundary_name = "clouder-role-boundary"
  # Through the resource, so every role waits for the policy to exist.
  role_boundary_arn = aws_iam_policy.role_boundary.arn
}

data "aws_iam_policy_document" "role_boundary" {
  statement {
    sid         = "EverythingButIdentityAndAccount"
    effect      = "Allow"
    not_actions = ["iam:*", "organizations:*", "account:*", "sts:AssumeRole"]
    resources   = ["*"]
  }
  statement {
    sid       = "ReadIam"
    effect    = "Allow"
    actions   = ["iam:Get*", "iam:List*"]
    resources = ["*"]
  }
  statement {
    sid       = "PassProjectRoles"
    effect    = "Allow"
    actions   = ["iam:PassRole"]
    resources = ["arn:aws:iam::${data.aws_caller_identity.current.account_id}:role/${local.name_prefix}-*"]
  }
}

resource "aws_iam_policy" "role_boundary" {
  name        = local.role_boundary_name
  description = "Permissions boundary of every CLOUDER role: no IAM writes, Organizations or account"
  policy      = data.aws_iam_policy_document.role_boundary.json
}

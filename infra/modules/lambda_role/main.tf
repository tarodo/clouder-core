# One least-privilege execution role per Lambda: its own log group plus the
# statements the caller passes. Statements with no resources (an optional secret
# that is not configured) are dropped.

variable "name" {
  type = string
}

variable "assume_role_policy" {
  type = string
}

variable "log_group_arn" {
  type = string
}

variable "statements" {
  type = list(object({
    sid       = string
    actions   = list(string)
    resources = list(string)
    # Optional s3:prefix limit for s3:ListBucket.
    s3_prefixes = optional(list(string), [])
  }))
}

resource "aws_iam_role" "this" {
  name               = var.name
  assume_role_policy = var.assume_role_policy
}

data "aws_iam_policy_document" "this" {
  statement {
    sid       = "OwnLogs"
    effect    = "Allow"
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${var.log_group_arn}:*"]
  }

  dynamic "statement" {
    for_each = { for s in var.statements : s.sid => s if length(s.resources) > 0 }
    content {
      sid       = statement.value.sid
      effect    = "Allow"
      actions   = statement.value.actions
      resources = statement.value.resources

      dynamic "condition" {
        for_each = length(statement.value.s3_prefixes) > 0 ? [1] : []
        content {
          test     = "StringLike"
          variable = "s3:prefix"
          values   = statement.value.s3_prefixes
        }
      }
    }
  }
}

resource "aws_iam_role_policy" "this" {
  name   = "${var.name}-policy"
  role   = aws_iam_role.this.id
  policy = data.aws_iam_policy_document.this.json
}

output "arn" {
  value = aws_iam_role.this.arn
}

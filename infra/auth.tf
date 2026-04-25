# ── KMS CMK for user_vendor_tokens envelope encryption ──────────────

resource "aws_kms_key" "user_tokens" {
  description             = "Envelope encryption for user_vendor_tokens (spec-A)"
  enable_key_rotation     = true
  deletion_window_in_days = 30
}

resource "aws_kms_alias" "user_tokens" {
  name          = "alias/${local.name_prefix}-user-tokens"
  target_key_id = aws_kms_key.user_tokens.key_id
}

# ── SSM SecureString parameters ─────────────────────────────────────

resource "random_password" "jwt_signing_key" {
  length  = 64
  special = false
}

resource "aws_ssm_parameter" "jwt_signing_key" {
  name        = var.jwt_signing_key_ssm_parameter
  description = "HS256 secret used by auth_handler and auth_authorizer (spec-A)"
  type        = "SecureString"
  value       = random_password.jwt_signing_key.result

  lifecycle {
    ignore_changes = [value]
  }
}

# Client_id and client_secret are uploaded out of band (terraform creates
# the parameter shells as empty SecureStrings; operator sets the value
# via `aws ssm put-parameter`). lifecycle.ignore_changes makes terraform
# tolerate the externally-managed value.

resource "aws_ssm_parameter" "spotify_oauth_client_id" {
  name        = var.spotify_oauth_client_id_ssm_parameter
  description = "Spotify OAuth client_id for user login (spec-A)"
  type        = "SecureString"
  value       = "REPLACE_AFTER_APPLY"

  lifecycle {
    ignore_changes = [value]
  }
}

resource "aws_ssm_parameter" "spotify_oauth_client_secret" {
  name        = var.spotify_oauth_client_secret_ssm_parameter
  description = "Spotify OAuth client_secret for user login (spec-A)"
  type        = "SecureString"
  value       = "REPLACE_AFTER_APPLY"

  lifecycle {
    ignore_changes = [value]
  }
}

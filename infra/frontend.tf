# CLOUDER SPA static host: private S3 bucket fronted by CloudFront via OAC.
# Spec: docs/superpowers/specs/2026-05-06-staging-frontend-host-design.md

resource "aws_s3_bucket" "frontend" {
  bucket = "${local.name_prefix}-frontend"
}

resource "aws_s3_bucket_public_access_block" "frontend" {
  bucket                  = aws_s3_bucket.frontend.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket" "raw" {
  bucket = local.bucket_name
}

resource "aws_s3_bucket_versioning" "raw" {
  bucket = aws_s3_bucket.raw.id

  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "raw" {
  bucket = aws_s3_bucket.raw.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_public_access_block" "raw" {
  bucket = aws_s3_bucket.raw.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# CORS rule for browser-direct cover uploads via presigned PUT.
# The SPA POSTs /playlists/{id}/cover/upload-url to get a presigned S3
# URL, then PUTs the file to S3 directly. Without this rule Chrome's
# CORS preflight fails before the PUT ever reaches S3.
resource "aws_s3_bucket_cors_configuration" "raw" {
  bucket = aws_s3_bucket.raw.id

  cors_rule {
    allowed_origins = [
      "https://${aws_cloudfront_distribution.frontend.domain_name}",
      "http://localhost:5173",
      "http://127.0.0.1:5173",
    ]
    allowed_methods = ["PUT", "GET", "HEAD"]
    allowed_headers = ["*"]
    expose_headers  = ["ETag"]
    max_age_seconds = 3000
  }
}

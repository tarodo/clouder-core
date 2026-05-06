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

resource "aws_cloudfront_origin_access_control" "frontend" {
  name                              = "${local.name_prefix}-frontend-oac"
  origin_access_control_origin_type = "s3"
  signing_behavior                  = "always"
  signing_protocol                  = "sigv4"
}

# SPA-fallback router on the S3 default behavior only. Rewrites any path
# that is not the document root, /index.html, or under /assets/ to
# /index.html so client-side routing works for deep links / F5.
# Attached only to the default behavior — API GW behaviors are unaffected.
resource "aws_cloudfront_function" "spa_router" {
  name    = "${local.name_prefix}-spa-router"
  runtime = "cloudfront-js-2.0"
  publish = true
  code    = <<-EOT
    function handler(event) {
      var req = event.request;
      if (req.uri !== '/' && req.uri !== '/index.html' && !req.uri.startsWith('/assets/')) {
        req.uri = '/index.html';
      }
      return req;
    }
  EOT
}

resource "aws_s3_bucket_policy" "frontend" {
  bucket = aws_s3_bucket.frontend.id
  policy = data.aws_iam_policy_document.frontend_bucket.json
}

data "aws_iam_policy_document" "frontend_bucket" {
  statement {
    actions   = ["s3:GetObject"]
    resources = ["${aws_s3_bucket.frontend.arn}/*"]
    principals {
      type        = "Service"
      identifiers = ["cloudfront.amazonaws.com"]
    }
    condition {
      test     = "StringEquals"
      variable = "AWS:SourceArn"
      values   = [aws_cloudfront_distribution.frontend.arn]
    }
  }
}

locals {
  # Order matters: CloudFront evaluates ordered_cache_behavior top-down on first match.
  # `/auth/return` is an SPA route — must NOT be in this list (falls through to S3 default).
  # Mirror of frontend/vite.config.ts BACKEND_ONLY_PREFIXES + SPA_AWARE_PREFIXES (14 patterns).
  api_gw_path_patterns = [
    "/auth/login",
    "/auth/callback",
    "/auth/refresh",
    "/auth/logout",
    "/me",
    "/styles*",
    "/tracks*",
    "/artists*",
    "/labels*",
    "/albums*",
    "/runs*",
    "/collect_bp_releases",
    "/categories*",
    "/triage*",
  ]
  # API GW $default stage has no URL path prefix — strip the protocol only.
  api_gw_host = replace(aws_apigatewayv2_api.collector.api_endpoint, "https://", "")
}

resource "aws_cloudfront_distribution" "frontend" {
  enabled             = true
  is_ipv6_enabled     = true
  comment             = "${local.name_prefix} SPA"
  default_root_object = "index.html"
  price_class         = "PriceClass_100"

  origin {
    origin_id                = "s3-frontend"
    domain_name              = aws_s3_bucket.frontend.bucket_regional_domain_name
    origin_access_control_id = aws_cloudfront_origin_access_control.frontend.id
  }

  origin {
    origin_id   = "api-gw"
    domain_name = local.api_gw_host
    # No origin_path: $default stage = no URL path prefix.
    custom_origin_config {
      http_port              = 80
      https_port             = 443
      origin_protocol_policy = "https-only"
      origin_ssl_protocols   = ["TLSv1.2"]
    }
  }

  default_cache_behavior {
    target_origin_id       = "s3-frontend"
    viewer_protocol_policy = "redirect-to-https"
    allowed_methods        = ["GET", "HEAD"]
    cached_methods         = ["GET", "HEAD"]
    compress               = true
    cache_policy_id        = "658327ea-f89d-4fab-a63d-7e88639e58f6" # CachingOptimized

    function_association {
      event_type   = "viewer-request"
      function_arn = aws_cloudfront_function.spa_router.arn
    }
  }

  dynamic "ordered_cache_behavior" {
    for_each = local.api_gw_path_patterns
    content {
      path_pattern             = ordered_cache_behavior.value
      target_origin_id         = "api-gw"
      viewer_protocol_policy   = "redirect-to-https"
      allowed_methods          = ["GET", "HEAD", "OPTIONS", "PUT", "POST", "PATCH", "DELETE"]
      cached_methods           = ["GET", "HEAD"]
      compress                 = true
      cache_policy_id          = "4135ea2d-6df8-44a3-9df3-4b5a84be39ad" # CachingDisabled
      origin_request_policy_id = "b689b0a8-53d0-40ab-baf2-68738e2966ac" # AllViewerExceptHostHeader
    }
  }

  # SPA fallback handled by aws_cloudfront_function.spa_router on the
  # default behavior — it rewrites unknown paths to /index.html before
  # the request hits S3, so 4xx never bubbles up. Distribution-level
  # custom_error_response would also intercept API GW errors (e.g.
  # /me 404 → HTML), so it is intentionally absent.

  viewer_certificate {
    cloudfront_default_certificate = true
    minimum_protocol_version       = "TLSv1.2_2021"
  }

  restrictions {
    geo_restriction {
      restriction_type = "none"
    }
  }
}

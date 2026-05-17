# Staging Frontend Host (S3 + CloudFront) — Design

**Date:** 2026-05-06
**Topic:** Deploy frontend SPA to AWS for phone testing
**Status:** Approved
**Implementation plan:** _pending_

## Goal

Make the CLOUDER SPA reachable from a phone over HTTPS so the small DJ-circle audience can dogfood F1–F6 (categories, triage, curate, playback) outside the dev laptop. This is a *staging* deploy — not a productionised launch — so we deliberately skip custom domain, WAF, signed URLs, and CI automation. Manual `terraform apply` + `scripts/deploy_frontend.sh` is enough to flip the bit.

## Non-goals

- Custom domain / Route53 / ACM certificate
- GitHub Actions auto-deploy on push to `main`
- Lambda@Edge or CloudFront Functions for SPA-aware path resolution
- WAF / rate limiting / IP allowlist
- S3 versioning, lifecycle, or replication
- Multi-environment (dev/stage/prod) split — the existing `prod` AWS account doubles as staging

## Constraints

- **No backend code changes.** Same-origin via CloudFront keeps `SameSite=Strict` refresh cookies + existing API contract intact.
- **HTTPS-only.** Spotify Web Playback SDK refuses to load over HTTP outside `localhost`.
- **`apiClient` already uses `window.location.origin`** (`frontend/src/api/client.ts:6`) — no `VITE_API_BASE_URL` needed at build time for the prod bundle.
- **Cost ceiling:** $0/month under CloudFront's always-free tier (1 TB egress + 10 M HTTP req).

## Architecture

```
Phone / Desktop browser
       │ HTTPS
       ▼
┌──────────────────────────────────────┐
│   CloudFront distribution            │
│   PriceClass_100 (US + EU + CA)      │
│                                      │
│   Behaviors (path-pattern → origin): │
│     default               → S3       │  static + SPA fallback
│     /auth/login           → API GW   │
│     /auth/callback        → API GW   │
│     /auth/refresh         → API GW   │
│     /auth/logout          → API GW   │
│     /me                   → API GW   │
│     /styles*              → API GW   │
│     /tracks*              → API GW   │
│     /artists*             → API GW   │
│     /labels*              → API GW   │
│     /albums*              → API GW   │
│     /runs*                → API GW   │
│     /collect_bp_releases  → API GW   │
│     /categories*          → API GW   │  (deep-link broken — TD-13)
│     /triage*              → API GW   │  (deep-link broken — TD-13)
│                                      │
│   custom_error_response:             │
│     403 → 200 /index.html            │
│     404 → 200 /index.html            │
└──────────────────────────────────────┘
       │                          │
       ▼                          ▼
┌──────────────────┐    ┌────────────────────────┐
│ S3 bucket        │    │ API Gateway HTTP API   │
│ beatport-prod-   │    │ beatport-prod-collector│
│ frontend         │    │ -api (existing)        │
│ (private, OAC)   │    └────────────────────────┘
└──────────────────┘
```

### Origin selection rules

- **S3 origin** for everything not explicitly listed → serves the SPA bundle, falls back to `/index.html` on 403/404.
- **API GW origin** for the 14 path patterns above. Pattern list is the authoritative duplicate of `BACKEND_ONLY_PREFIXES + SPA_AWARE_PREFIXES` in `frontend/vite.config.ts:14-30`. When that list changes, this one must follow (manual sync gate — same drift class as `scripts/generate_openapi.py:ROUTES`).
- **`/auth/*` is NOT a single pattern** — `/auth/return` is an SPA route (per existing CLAUDE.md gotcha and roadmap constraint). Each backend `/auth/{login,callback,refresh,logout}` is listed individually so `/auth/return` falls through to the S3 default behavior.

### CloudFront behavior policies

- **S3 default behavior:** managed `CachingOptimized` (`658327ea-f89d-4fab-a63d-7e88639e58f6`), managed `CORS-S3Origin` (`88a5eaf4-2fd4-4709-b370-b4c650ea3fcf`).
- **API GW behaviors:** managed `CachingDisabled` (`4135ea2d-6df8-44a3-9df3-4b5a84be39ad`), managed `AllViewer` origin-request (`216adef6-5c7f-47e4-b989-5492eafa07d3`) — forwards all headers, cookies, query strings.
- **TLS:** `ViewerProtocolPolicy = redirect-to-https`, `MinimumProtocolVersion = TLSv1.2_2021`.
- **Compression:** `Compress = true` on default behavior.

## Components

### 1. `infra/frontend.tf` (new file)

```hcl
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

# bucket policy: only this CloudFront distribution can s3:GetObject
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
    # No origin_path: $default stage = no URL path prefix
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
      origin_request_policy_id = "216adef6-5c7f-47e4-b989-5492eafa07d3" # AllViewer
    }
  }

  custom_error_response {
    error_code            = 403
    response_code         = 200
    response_page_path    = "/index.html"
    error_caching_min_ttl = 0
  }

  custom_error_response {
    error_code            = 404
    response_code         = 200
    response_page_path    = "/index.html"
    error_caching_min_ttl = 0
  }

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
```

### 2. `infra/outputs.tf` (additions)

```hcl
output "frontend_url" {
  description = "CloudFront URL for the SPA"
  value       = "https://${aws_cloudfront_distribution.frontend.domain_name}"
}

output "frontend_bucket" {
  description = "S3 bucket holding the SPA bundle"
  value       = aws_s3_bucket.frontend.bucket
}

output "frontend_distribution_id" {
  description = "CloudFront distribution ID for invalidation"
  value       = aws_cloudfront_distribution.frontend.id
}
```

### 3. `scripts/deploy_frontend.sh` (new file)

```bash
#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT/frontend"

pnpm install --frozen-lockfile
pnpm build

BUCKET=$(cd "$ROOT/infra" && terraform output -raw frontend_bucket)
DIST_ID=$(cd "$ROOT/infra" && terraform output -raw frontend_distribution_id)

# Hashed assets (`assets/*.{js,css,svg,...}`) — long TTL, immutable
aws s3 sync dist/ "s3://$BUCKET/" --delete \
  --cache-control "public,max-age=31536000,immutable" \
  --exclude "index.html"

# index.html — never cached at edge OR browser
aws s3 cp dist/index.html "s3://$BUCKET/index.html" \
  --cache-control "no-cache,no-store,must-revalidate" \
  --content-type "text/html; charset=utf-8"

# Invalidate index.html so the next viewer pulls a fresh copy
aws cloudfront create-invalidation \
  --distribution-id "$DIST_ID" \
  --paths "/index.html" >/dev/null

echo "Deployed. URL: $(cd "$ROOT/infra" && terraform output -raw frontend_url)"
```

Make executable: `chmod +x scripts/deploy_frontend.sh`.

### 4. Backend env updates (via `terraform.tfvars` or `-var=`)

After CloudFront URL is known (from `terraform output -raw frontend_url`):

- `spotify_oauth_redirect_uri = "https://<cf-domain>/auth/return"`

Re-run `terraform apply` to push to the auth Lambda env.

**Note:** `allowed_frontend_redirects` is unrelated — it's the exact-match allow-list of relative SPA paths accepted as the optional `?redirect_uri=` query param on `/auth/login` (see `src/collector/auth/auth_settings.py:23`). It does NOT contain the OAuth callback URL and does not need updating for this deploy.

### 5. Spotify Developer Dashboard (manual)

Add `https://<cf-domain>/auth/return` to **Redirect URIs** for the Spotify app. Keep `http://127.0.0.1:5173/auth/return` for dev.

## Data flow

### Cold-load SPA
1. Phone navigates to `https://xyz.cloudfront.net/`
2. CloudFront default behavior → S3 origin → `index.html` (no-cache headers honoured)
3. SPA bundle (`assets/*.{js,css}`) loads from same origin — long-TTL cached at edge
4. SPA boots, AuthProvider mounts, fires `/auth/refresh`
5. CF `/auth/*` behavior → API GW → Lambda → `Set-Cookie: refresh_token=…; SameSite=Strict; Path=/auth/refresh`. Same-origin → cookie sticks.

### Login (Spotify OAuth)
1. SPA `/auth/login` → CF → API GW → Lambda → 302 to `accounts.spotify.com/authorize?redirect_uri=https://xyz.cloudfront.net/auth/callback`
2. User authenticates on Spotify → 302 to `https://xyz.cloudfront.net/auth/callback?code=…`
3. CF `/auth/*` behavior → API GW → Lambda exchanges code → 302 to `https://xyz.cloudfront.net/auth/return?…`
4. CF default behavior → S3 → `index.html` (404 fallback) → SPA router renders `AuthReturnPage`

### Deep-link to `/categories/<id>` (TD-13)
1. Browser GET → CF `/categories*` behavior → API GW
2. API GW route is for `GET /categories/{id}` returning JSON → returns JSON instead of HTML
3. Browser displays raw JSON. **Known limitation.** In-app navigation (react-router push) bypasses HTTP fetch and works.

### F-deploy bundle deploy
1. `scripts/deploy_frontend.sh` runs `pnpm build` → `frontend/dist/`
2. `aws s3 sync` uploads hashed assets with immutable cache-control
3. `aws s3 cp` uploads `index.html` with no-cache
4. `aws cloudfront create-invalidation` flushes only `/index.html`
5. New viewers pull fresh `index.html`, which references newly-hashed asset names → no cache poisoning

## Testing

### Pre-deploy
- `cd infra && terraform validate && terraform plan` — confirms the new resources, no drift on existing infra
- `cd frontend && pnpm typecheck && pnpm test && pnpm build` — confirms the SPA still builds clean

### Post-deploy (manual smoke, ~10 minutes)
1. **HTTPS reachable:** `curl -I https://<cf-domain>/` → 200, `content-type: text/html`
2. **SPA fallback:** `curl -I https://<cf-domain>/curate/some/random/path` → 200, returns `index.html`
3. **Login:** open in laptop browser → login button → Spotify OAuth → returns → `/me` populated
4. **Phone smoke:**
   - Open `https://<cf-domain>` on iPhone Safari
   - Login flow completes
   - Categories load, triage block opens, drag/tap a track
   - Curate session: PlayerCard plays via Spotify SDK (premium account required)
   - J/K/Space hotkeys irrelevant on phone — verify tap-to-assign + Play button work
5. **Refresh-cookie persistence:** close tab, reopen, identity restored from `/auth/refresh`
6. **Cold-start tolerance:** if first request 503s through API GW (Aurora min_acu=0 + 300s idle), retry — known existing limitation

### Regression on dev environment
- `pnpm dev` from `frontend/` still works on `127.0.0.1:5173` (Vite proxy unchanged)
- Spotify Dashboard still has `127.0.0.1:5173/auth/return` whitelisted
- Lambda env `SPOTIFY_OAUTH_REDIRECT_URI` is the prod value now, so dev OAuth would 302 to CloudFront. **Workaround:** ad-hoc flip env var via `aws lambda update-function-configuration` for dev sessions (same approach the existing TD-8 row tracks). Long-term fix = per-environment redirect resolver, out of scope here.

## Error handling

- **First `terraform apply` takes 5–15 min** for CloudFront propagation. `terraform apply` blocks until the distribution is `Deployed`. Don't ctrl-C.
- **Stale `index.html` after deploy:** if a viewer opens before `create-invalidation` completes (~30s), they get the previous bundle. Acceptable for testing — for prod we'd add a cache-busting query string or `vary` header.
- **403 from CloudFront on first asset request:** indicates OAC bucket-policy not yet propagated. Wait 1–2 min and retry. If persistent, check `aws s3 cp` actually uploaded files and bucket policy `aws:SourceArn` matches the distribution ARN.
- **`csrf_state_mismatch` on `/auth/callback`:** Lambda env `SPOTIFY_OAUTH_REDIRECT_URI` does not match where CloudFront sent the OAuth request. Re-verify `terraform apply` flushed the new value.

## Open items / TD tickets

- **TD-13 (new):** Deep-link to `/categories/<id>` and `/triage/<id>` in prod returns API JSON instead of rendering the SPA route. Needs path namespace cleanup (move backend to `/api/categories`, `/api/triage`) OR Lambda@Edge origin-switch by `Accept` header.
- **TD-8 (existing):** `SPOTIFY_OAUTH_REDIRECT_URI` Lambda env now permanently in tfvars (no longer ad-hoc-patched), but dev sessions need a way to override without `terraform apply`. Either env-specific tfvars, or a runtime override read from request `Origin`. Out of scope here.
- **CC (existing):** GitHub Actions deploy of frontend (Plan C continuation). Pre-req: this manual flow proven stable.

## Cost

CloudFront free tier (always-on, not 12-month):
- 1 TB egress / month
- 10 M HTTP/HTTPS requests / month
- 2 M CloudFront Function invocations / month

S3 storage: bundle ~3 MB → <$0.001/month.

S3 GET requests: cached at CF edge, almost no cache misses → <$0.01/month.

**Total marginal cost over current bill: $0.**

## Implementation order (for the plan)

1. Add `infra/frontend.tf` + outputs → `terraform plan` clean → `terraform apply` (15 min wait)
2. Add `scripts/deploy_frontend.sh` → first run → confirm CloudFront URL serves `index.html`
3. Update Spotify Dashboard with new redirect URI
4. Update `terraform.tfvars` with `spotify_oauth_redirect_uri` + `allowed_frontend_redirects` → `terraform apply`
5. Phone smoke test
6. Add TD-13 row to `docs/superpowers/plans/2026-05-01-frontend-iter-2a-roadmap.md`
7. Append "what bit me" lessons to roadmap

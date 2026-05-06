# Staging Frontend Host (S3 + CloudFront) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deploy the CLOUDER SPA to AWS via S3 + CloudFront so the small DJ-circle audience can dogfood F1–F6 from a phone over HTTPS.

**Architecture:** A single CloudFront distribution fronts two origins: an OAC-protected S3 bucket for the SPA bundle (default behavior, with `403`/`404 → 200 /index.html` fallback for SPA routing) and the existing API Gateway HTTP API for 14 explicit path patterns. Same-origin keeps `SameSite=Strict` refresh cookies + the existing API contract intact — zero backend code changes.

**Tech Stack:** Terraform, AWS S3 + CloudFront + API Gateway v2 (existing), Vite + pnpm + React 19 (existing), bash/AWS CLI for the deploy script.

**Spec:** `docs/superpowers/specs/2026-05-06-staging-frontend-host-design.md` (committed in `d6b9a28`)

## Pre-flight checks (read once, before Task 1)

- This plan assumes you can run `terraform apply` locally against the existing prod state (per `CLAUDE.md` "Migrations" command — user runs terraform locally, has AWS creds + `infra/backend.hcl` set up). If `terraform init` is not yet primed in `infra/`, run `terraform init -backend-config=backend.hcl` (or whatever local file mirrors `vars.TF_STATE_BUCKET` / `vars.TF_LOCK_TABLE` from `.github/workflows/deploy.yml:37-43`) before Task 1's `terraform validate`.
- Branch already isolated in worktree `worktree-deploy_try`. All commits land here; merge to `main` after smoke test passes.
- One CloudFront distribution propagation = 5-15 min. Don't ctrl-C `terraform apply` or `aws cloudfront update-distribution`.

## File map

- **Create:** `infra/frontend.tf` — S3 bucket + bucket-policy data + OAC + CloudFront distribution
- **Modify:** `infra/outputs.tf` — add `frontend_url`, `frontend_bucket`, `frontend_distribution_id`
- **Modify:** `infra/terraform.tfvars` (gitignored, local-only) — change `spotify_oauth_redirect_uri` to CloudFront URL after first apply
- **Create:** `scripts/deploy_frontend.sh` — `pnpm build` → `aws s3 sync` → `aws cloudfront create-invalidation`
- **Modify:** `docs/superpowers/plans/2026-05-01-frontend-iter-2a-roadmap.md` — append "what bit me" lessons under existing post-F-deploy section

No frontend code changes. No backend code changes. No new pytest / vitest tests — verification is `terraform plan` + `terraform validate` + `curl` smoke against the deployed CloudFront.

---

## Task 1: Scaffold `infra/frontend.tf` with S3 bucket + access block

**Files:**
- Create: `infra/frontend.tf`

- [ ] **Step 1: Create `infra/frontend.tf` with the S3 bucket + public-access block**

```hcl
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
```

- [ ] **Step 2: Validate Terraform syntax**

Run: `cd infra && terraform validate`
Expected: `Success! The configuration is valid.`

- [ ] **Step 3: Plan to confirm only the new bucket appears**

Run: `cd infra && terraform plan -no-color | head -60`
Expected: `Plan: 2 to add, 0 to change, 0 to destroy.` for `aws_s3_bucket.frontend` and `aws_s3_bucket_public_access_block.frontend`. If you see modifications to unrelated resources, abort and investigate before continuing.

- [ ] **Step 4: Commit**

```bash
git add infra/frontend.tf
git commit -m "$(cat <<'EOF'
feat(infra): add private S3 bucket for SPA static host

Bucket name beatport-prod-frontend, no public access. CloudFront
+ OAC come in the next commits.
EOF
)"
```

---

## Task 2: Add OAC + bucket policy

**Files:**
- Modify: `infra/frontend.tf`

- [ ] **Step 1: Append OAC + bucket policy to `infra/frontend.tf`**

```hcl
resource "aws_cloudfront_origin_access_control" "frontend" {
  name                              = "${local.name_prefix}-frontend-oac"
  origin_access_control_origin_type = "s3"
  signing_behavior                  = "always"
  signing_protocol                  = "sigv4"
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
```

- [ ] **Step 2: Validate**

Run: `cd infra && terraform validate`
Expected: `Success! The configuration is valid.` (the forward reference to `aws_cloudfront_distribution.frontend` resolves once Task 3 lands; Terraform validate is OK with forward refs because it only checks resource graph wiring, not values.)

If validate fails because the distribution resource is genuinely undefined at this point, skip the explicit validate here and rely on Task 3's combined validate + plan.

- [ ] **Step 3: Commit**

```bash
git add infra/frontend.tf
git commit -m "$(cat <<'EOF'
feat(infra): add OAC + bucket policy for SPA bucket

Bucket policy condition pins access to a single CloudFront
distribution by source ARN.
EOF
)"
```

---

## Task 3: Add CloudFront distribution

**Files:**
- Modify: `infra/frontend.tf`

- [ ] **Step 1: Append the CloudFront distribution block + `locals` for the API GW path patterns**

```hcl
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

- [ ] **Step 2: Validate + format**

Run: `cd infra && terraform fmt && terraform validate`
Expected: `Success! The configuration is valid.`

- [ ] **Step 3: Plan and confirm the distribution + 14 ordered behaviors**

Run: `cd infra && terraform plan -no-color > /tmp/frontend_plan.txt && grep -E "^Plan:|cloudfront|frontend" /tmp/frontend_plan.txt | head -30`
Expected: A `Plan: N to add, 0 to change, 0 to destroy.` line (N = 5: bucket, public-access-block, OAC, bucket-policy, distribution) and the distribution shown with `+ ordered_cache_behavior` repeated 14 times.

If `change` count > 0 against any non-`frontend.tf` resource, abort: something else drifted. Investigate before applying.

- [ ] **Step 4: Commit**

```bash
git add infra/frontend.tf
git commit -m "$(cat <<'EOF'
feat(infra): add CloudFront distribution for SPA

Two origins (S3 + existing API GW), 14 explicit behaviors for
backend paths, default to S3 with 403/404 → /index.html fallback
for SPA client-side routing. PriceClass_100 (US/EU/CA) keeps cost
inside the always-free 1 TB / 10 M req tier.
EOF
)"
```

---

## Task 4: Add Terraform outputs

**Files:**
- Modify: `infra/outputs.tf`

- [ ] **Step 1: Append three outputs to the bottom of `infra/outputs.tf`**

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

- [ ] **Step 2: Validate**

Run: `cd infra && terraform validate`
Expected: `Success! The configuration is valid.`

- [ ] **Step 3: Commit**

```bash
git add infra/outputs.tf
git commit -m "$(cat <<'EOF'
feat(infra): expose frontend_url + bucket + distribution_id

Deploy script reads these via terraform output -raw.
EOF
)"
```

---

## Task 5: First `terraform apply` — provision S3 + CloudFront

**Files:** none modified (state change only).

- [ ] **Step 1: Confirm plan one last time**

Run: `cd infra && terraform plan`
Expected: `Plan: 5 to add, 0 to change, 0 to destroy.` exactly. Anything else = stop and ask.

- [ ] **Step 2: Apply**

Run: `cd infra && terraform apply -auto-approve`
Expected: Runs ~10 minutes. The bucket + policy + OAC complete fast (~30s); the `aws_cloudfront_distribution.frontend: Still creating...` lines repeat for ~5-15 min until `Apply complete!`.

If the apply errors midway, do NOT re-run blindly: investigate, fix, then `terraform apply` again (Terraform tracks partial state).

- [ ] **Step 3: Capture the CloudFront URL**

Run:
```bash
cd infra
terraform output -raw frontend_url
echo
terraform output -raw frontend_bucket
echo
terraform output -raw frontend_distribution_id
```
Expected: three lines — a CloudFront URL like `https://d123abc.cloudfront.net`, the bucket name `beatport-prod-frontend`, and a distribution ID like `E1A2B3C4D5E6F7`.

Save the CloudFront URL to a scratchpad — you need it for Tasks 8, 9, 10.

- [ ] **Step 4: No commit (state-only change)**

Note: Terraform state lives in S3, not in the repo. There is nothing to commit here.

---

## Task 6: Author the deploy script

**Files:**
- Create: `scripts/deploy_frontend.sh`

- [ ] **Step 1: Create the script**

```bash
#!/usr/bin/env bash
# Build the SPA, sync to S3, invalidate CloudFront's index.html.
# Spec: docs/superpowers/specs/2026-05-06-staging-frontend-host-design.md

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT/frontend"

pnpm install --frozen-lockfile
pnpm build

BUCKET=$(cd "$ROOT/infra" && terraform output -raw frontend_bucket)
DIST_ID=$(cd "$ROOT/infra" && terraform output -raw frontend_distribution_id)

# Hashed assets (assets/*.{js,css,svg,...}) — long TTL, immutable.
aws s3 sync dist/ "s3://$BUCKET/" --delete \
  --cache-control "public,max-age=31536000,immutable" \
  --exclude "index.html"

# index.html — never cached at edge OR browser.
aws s3 cp dist/index.html "s3://$BUCKET/index.html" \
  --cache-control "no-cache,no-store,must-revalidate" \
  --content-type "text/html; charset=utf-8"

# Invalidate index.html so the next viewer pulls a fresh copy.
aws cloudfront create-invalidation \
  --distribution-id "$DIST_ID" \
  --paths "/index.html" >/dev/null

echo "Deployed. URL: $(cd "$ROOT/infra" && terraform output -raw frontend_url)"
```

- [ ] **Step 2: Make executable**

Run: `chmod +x scripts/deploy_frontend.sh`

- [ ] **Step 3: Lint with shellcheck (if installed) or manual `bash -n` syntax check**

Run: `command -v shellcheck >/dev/null && shellcheck scripts/deploy_frontend.sh || bash -n scripts/deploy_frontend.sh`
Expected: silent (zero stdout, zero stderr, exit 0). If shellcheck is installed and warns about anything non-trivial, fix before continuing.

- [ ] **Step 4: Commit**

```bash
git add scripts/deploy_frontend.sh
git commit -m "$(cat <<'EOF'
feat(scripts): add manual frontend deploy script

Build → sync hashed assets with immutable cache-control → upload
index.html with no-cache → invalidate /index.html only. Reads
bucket + distribution-id from terraform output to stay in sync
with infra changes.
EOF
)"
```

---

## Task 7: First frontend deploy + reachability smoke

**Files:** none.

- [ ] **Step 1: Run the deploy script**

Run: `./scripts/deploy_frontend.sh`
Expected: ends with `Deployed. URL: https://...cloudfront.net`. `pnpm build` step takes ~30-60s. The `aws s3 sync` uploads 5-30 files. The invalidation completes in <30s.

If `pnpm install --frozen-lockfile` fails because the lockfile drifted, run `pnpm install` once to update it, then re-run the script. If `aws` commands fail with `ExpiredToken` / `Unable to locate credentials`, refresh AWS creds and retry.

- [ ] **Step 2: Verify HTTPS reachable**

Run: `curl -sI "$(cd infra && terraform output -raw frontend_url)/" | head -5`
Expected: `HTTP/2 200`, `content-type: text/html; charset=utf-8`, plus `cache-control: no-cache,no-store,must-revalidate`.

If you get `403` or `404`: bucket policy may not be propagated yet (wait 1-2 min and retry); or `index.html` was not uploaded (re-run the script).

- [ ] **Step 3: Verify SPA fallback for an SPA-only deep route**

Run: `curl -sI "$(cd infra && terraform output -raw frontend_url)/curate/foo/bar/baz" | head -5`
Expected: `HTTP/2 200`, `content-type: text/html; charset=utf-8`. CloudFront's `404 → 200 /index.html` custom-error-response should fire.

- [ ] **Step 4: Verify an API path proxies to API Gateway**

Run: `curl -sI "$(cd infra && terraform output -raw frontend_url)/me"`
Expected: `HTTP/2 401` (or another non-2xx auth error). `401` here is success — it confirms the request reached API GW + Lambda and returned the expected unauthenticated response. If you get `200`, `403`, or anything HTML-shaped, the path was incorrectly served from S3 instead — re-check the `ordered_cache_behavior` for `/me` in `infra/frontend.tf`.

- [ ] **Step 5: No commit (deploy is non-source state).**

---

## Task 8: Register CloudFront URL in Spotify Developer Dashboard

This is a **manual user step** — there is no API automation in this plan.

- [ ] **Step 1: Open the Spotify Developer Dashboard**

URL: https://developer.spotify.com/dashboard

- [ ] **Step 2: Open the CLOUDER app, click "Edit settings", scroll to "Redirect URIs"**

- [ ] **Step 3: Add the new URI**

Add: `https://<cf-domain>/auth/return` (substitute the CloudFront domain from Task 5 Step 3)

Keep `http://127.0.0.1:5173/auth/return` so dev OAuth still works (it WILL break temporarily after Task 9 lands the env-var change — see Task 9 notes — but that's a Lambda env issue, not a Spotify Dashboard issue).

- [ ] **Step 4: Click "Save" at the bottom of the form**

Verify both URIs appear in the Redirect URIs list.

---

## Task 9: Update `spotify_oauth_redirect_uri` and re-apply

**Files:**
- Modify: `infra/terraform.tfvars` (gitignored, local-only)

- [ ] **Step 1: Find the current value**

Run: `grep spotify_oauth_redirect_uri infra/terraform.tfvars`
Expected: a line like `spotify_oauth_redirect_uri = "http://127.0.0.1:5173/auth/return"` or similar. If the file does not exist or the line is missing, this deploy was previously running off `-var=` flags from CI; in that case, create / append the line.

- [ ] **Step 2: Edit the value**

Replace the existing line (or append) so it reads:
```hcl
spotify_oauth_redirect_uri = "https://<cf-domain>/auth/return"
```
(Substitute the actual CloudFront domain.) Save the file.

- [ ] **Step 3: Plan to confirm only the auth Lambda environment changes**

Run:
```bash
cd infra
terraform plan -no-color > /tmp/redirect_plan.txt
grep -E "^Plan:|will be (created|updated|destroyed)" /tmp/redirect_plan.txt
grep -E "SPOTIFY_OAUTH_REDIRECT_URI" /tmp/redirect_plan.txt | head -5
```
Expected: `Plan: 0 to add, 1 to change, 0 to destroy.` and exactly one `~ ... will be updated in-place` line for the auth handler Lambda. The `SPOTIFY_OAUTH_REDIRECT_URI` grep should show two lines: the old dev value and the new CF value. If you see ANY other resource being created / updated / destroyed, abort and investigate before applying — something else has drifted.

To confirm the resource name in `infra/auth.tf`: `grep -n "aws_lambda_function" infra/auth.tf | head -3`.

- [ ] **Step 4: Apply**

Run: `cd infra && terraform apply -auto-approve`
Expected: completes in <30s (Lambda env update is fast).

- [ ] **Step 5: Note known dev-flow regression**

Once this lands, dev OAuth on `127.0.0.1:5173` will redirect to CloudFront because the Lambda env is the prod URL. To run dev OAuth temporarily, ad-hoc flip via:
```bash
aws lambda update-function-configuration \
  --function-name beatport-prod-auth-handler \
  --environment "Variables={SPOTIFY_OAUTH_REDIRECT_URI=http://127.0.0.1:5173/auth/return,...}"
```
This is the same drift cycle that TD-8 tracks. No fix in this plan; long-term solution = per-environment redirect resolver, out of scope.

- [ ] **Step 6: No commit (tfvars is gitignored).**

---

## Task 10: End-to-end manual smoke test on phone

**Files:** none.

This is the entire reason the plan exists. The previous tasks all need to come together on a real phone before declaring success.

- [ ] **Step 1: Open the CloudFront URL on a desktop browser**

Verify the SPA loads. Open DevTools Network tab to confirm:
- `/` returns `index.html`
- `assets/*.js` and `assets/*.css` return 200 with `cache-control: public,max-age=31536000,immutable`
- The `/auth/refresh` POST that AuthProvider fires on mount returns 401 (expected — no session yet) without CORS errors

- [ ] **Step 2: Click "Login with Spotify"**

OAuth flow:
- Browser navigates to `accounts.spotify.com/authorize?...&redirect_uri=https://<cf-domain>/auth/return`
- After consent, Spotify 302s to your `/auth/return` (or via `/auth/callback`, depending on the existing flow shape — both are now same-origin)
- AuthProvider stores tokens, `/me` returns the user payload
- The home page renders with the user's name

If you get `csrf_state_mismatch` on `/auth/callback`: the Lambda env did not flush — re-run Task 9's `terraform apply` and verify with `aws lambda get-function-configuration --function-name beatport-prod-auth-handler --query 'Environment.Variables.SPOTIFY_OAUTH_REDIRECT_URI'`.

- [ ] **Step 3: Refresh the page (F5)**

AuthProvider should rebuild identity from the refresh cookie within 1-2s. If you get logged out, the refresh cookie did not survive the cross-origin barrier — verify the page is on the CloudFront domain (not the API GW domain by accident) and that `/auth/refresh` is hitting `<cf-domain>/auth/refresh` (same-origin).

- [ ] **Step 4: Open the same URL on your phone**

Spotify Premium account required for SDK playback (see CLAUDE.md F6 gotchas).

- [ ] **Step 5: Phone smoke checklist**

Tap through the full F1-F6 flow:
- [ ] Login completes
- [ ] Home loads
- [ ] Categories → triage block opens
- [ ] Curate session opens; tracks queue rendered
- [ ] PlayerCard appears, tap Play → audio comes out the phone
- [ ] Tap a destination button → optimistic shrink works, next track renders
- [ ] Slider scrub works (jsdom-untestable in F6, this is the first real verification)
- [ ] MiniBar appears when navigating away from a Curate route

If the SDK fails to load: Spotify Web Playback SDK requires HTTPS — confirm the URL bar shows `https://`.

- [ ] **Step 6: Cold-start tolerance**

If you opened the app for the first time after >5 min of idle backend, the first request may 503 through the API GW 29s timeout (Aurora `min_acu=0`). Retry once. Document the latency in lessons (Task 11).

- [ ] **Step 7: No commit (manual verification).**

---

## Task 11: Append "what bit me" lessons to roadmap

**Files:**
- Modify: `docs/superpowers/plans/2026-05-01-frontend-iter-2a-roadmap.md`

- [ ] **Step 1: Find the existing "Lessons learned" section bottom**

Run: `grep -n "^## Lessons" docs/superpowers/plans/2026-05-01-frontend-iter-2a-roadmap.md | tail -1`
Expected: a line number for the last `## Lessons learned (post-Fn, ...)` heading. The new section appends below the last numbered lesson under that heading (or starts a new `## Lessons learned (post-F-deploy-1, 2026-05-06)` section if you prefer the chronological structure the file already uses).

- [ ] **Step 2: Append a new lessons section with concrete surprises encountered during Tasks 1-10**

Use this template — fill in only items that actually bit you. Do NOT invent surprises that didn't happen. If a task went smoothly, say so by silence (omit). 3-line items max.

```markdown
## Lessons learned (post-F-deploy-1, 2026-05-06)

NN. **<Lesson title>.** <What happened, what fixed it, what to remember next time.> <Where the fix lives, e.g., `infra/frontend.tf:XX` or `scripts/deploy_frontend.sh:YY`.>

NN+1. **<Lesson title>.** ...
```

Candidate prompts (delete the ones that didn't bite):
- Did `terraform plan` show drift you didn't expect?
- Did the bucket policy `aws:SourceArn` condition take >1 propagation cycle?
- Did `pnpm install --frozen-lockfile` fail because the lockfile drifted from a previous F6 PR?
- Did `csrf_state_mismatch` fire because the Lambda env didn't flush immediately after `terraform apply`?
- Did the phone OAuth flow have a Spotify-Premium gotcha you forgot?
- Did `curl -sI` for `/me` return HTML (= behavior misrouted to S3 instead of API GW)?

If literally nothing surprised you, write a single line: `NN. **F-deploy-1 ran clean.** No deviations from the plan. Default cost estimate held; CloudFront propagation = ~12 min.`

- [ ] **Step 3: Commit**

Generate the commit subject via the `caveman:caveman-commit` skill, then commit with the heredoc form:

```bash
git add docs/superpowers/plans/2026-05-01-frontend-iter-2a-roadmap.md
# Subject suggestion: docs(roadmap): record F-deploy-1 lessons
git commit -m "$(cat <<'EOF'
docs(roadmap): record F-deploy-1 lessons

Append surprises from the staging frontend host deploy so the
next CI-automation ticket (CC continuation) doesn't re-discover
them.
EOF
)"
```

---

## Task 12: Cleanup + handoff

**Files:** none modified.

- [ ] **Step 1: Verify all expected files committed**

Run: `git log --oneline main..HEAD`
Expected: at minimum:
- `feat(infra): add private S3 bucket for SPA static host`
- `feat(infra): add OAC + bucket policy for SPA bucket`
- `feat(infra): add CloudFront distribution for SPA`
- `feat(infra): expose frontend_url + bucket + distribution_id`
- `feat(scripts): add manual frontend deploy script`
- `docs(roadmap): record F-deploy-1 lessons`

(The `docs(specs):` commit `d6b9a28` already exists from the design phase.)

- [ ] **Step 2: Check `git status` is clean**

Run: `git status`
Expected: `nothing to commit, working tree clean`. If there are uncommitted changes, decide whether they belong in a follow-up commit or should be discarded.

- [ ] **Step 3: Hand off to user**

Tell the user:
- Branch is ready to merge to `main` (manual decision — don't auto-merge).
- The CloudFront URL is at `cd infra && terraform output -raw frontend_url`.
- TD-13 (deep-link collision on `/categories/*` and `/triage/*`) is the next ticket if external sharing matters.
- CI automation of the deploy script is the natural follow-up (Plan C continuation referenced in spec § "Implementation order").

---

## What is explicitly NOT in this plan

- GitHub Actions automation of `scripts/deploy_frontend.sh` — followup ticket (Plan C continuation)
- Custom domain / Route53 / ACM — followup ticket
- Lambda@Edge or namespace fix for TD-13 — followup ticket
- WAF / rate limiting / IP allowlist — followup ticket
- Per-environment OAuth redirect resolver (TD-8 long-term fix) — followup ticket
- Any frontend code changes — there are none required

## Cost reminder

CloudFront free tier (always-on): 1 TB egress + 10 M HTTPS req/month. S3 storage <$0.001/month for ~3 MB bundle. Marginal cost over the existing prod bill = $0/month while staying inside free-tier traffic.

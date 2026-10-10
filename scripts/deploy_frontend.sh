#!/usr/bin/env bash
# Build the SPA, sync to S3, invalidate CloudFront's index.html.
# Spec: docs/superpowers/specs/2026-05-06-staging-frontend-host-design.md
#
# Usage: deploy_frontend.sh [build|publish]   (no argument: both)
# The deploy workflow builds before AWS credentials exist — pnpm runs dependencies'
# install scripts — and publishes after the apply (ADR-0028).

set -euo pipefail

MODE="${1:-all}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT/frontend"

if [ "$MODE" != publish ]; then
  pnpm install --frozen-lockfile
  # Telemetry SDK is behind VITE_TELEMETRY_ENABLED (default off in code). The prod
  # build turns it on so the analytics pipeline actually receives events. Export
  # VITE_TELEMETRY_ENABLED=false before this script to ship the frontend dark.
  VITE_TELEMETRY_ENABLED="${VITE_TELEMETRY_ENABLED:-true}" pnpm build
fi
[ "$MODE" = build ] && exit 0

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

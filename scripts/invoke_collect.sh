#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<USAGE
Usage:
  scripts/invoke_collect.sh \
    --api-url https://<api-id>.execute-api.<region>.amazonaws.com \
    --style-id 5 \
    --iso-year 2026 \
    --iso-week 9 \
    --bp-token <token> \
    [--correlation-id <id>] \
    [--region us-east-1]
USAGE
}

require_bin() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "Missing required command: $1" >&2
    exit 1
  fi
}

API_URL=""
STYLE_ID=""
ISO_YEAR=""
ISO_WEEK=""
BP_TOKEN=""
CORRELATION_ID=""
AWS_REGION="us-east-1"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --api-url)
      API_URL="$2"
      shift 2
      ;;
    --style-id)
      STYLE_ID="$2"
      shift 2
      ;;
    --iso-year)
      ISO_YEAR="$2"
      shift 2
      ;;
    --iso-week)
      ISO_WEEK="$2"
      shift 2
      ;;
    --bp-token)
      BP_TOKEN="$2"
      shift 2
      ;;
    --correlation-id)
      CORRELATION_ID="$2"
      shift 2
      ;;
    --region)
      AWS_REGION="$2"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage
      exit 1
      ;;
  esac
done

if [[ -z "$API_URL" || -z "$STYLE_ID" || -z "$ISO_YEAR" || -z "$ISO_WEEK" ]]; then
  usage
  exit 1
fi

if [[ -z "$BP_TOKEN" ]]; then
  read -r -s -p "Enter bp_token: " BP_TOKEN
  echo
fi

if [[ -z "$CORRELATION_ID" ]]; then
  require_bin uuidgen
  CORRELATION_ID="$(uuidgen)"
fi

require_bin awscurl
require_bin python3

PAYLOAD="$({
  STYLE_ID="$STYLE_ID" ISO_YEAR="$ISO_YEAR" ISO_WEEK="$ISO_WEEK" BP_TOKEN="$BP_TOKEN" python3 - <<'PY'
import json
import os

print(json.dumps({
    "bp_token": os.environ["BP_TOKEN"],
    "style_id": int(os.environ["STYLE_ID"]),
    "iso_year": int(os.environ["ISO_YEAR"]),
    "iso_week": int(os.environ["ISO_WEEK"]),
}))
PY
})"

awscurl \
  --service execute-api \
  --region "$AWS_REGION" \
  -X POST \
  -H "Content-Type: application/json" \
  -H "x-correlation-id: $CORRELATION_ID" \
  -d "$PAYLOAD" \
  "$API_URL/collect_bp_releases"

#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BUILD_DIR="$ROOT_DIR/dist/lambda_build"
OUTPUT_ZIP="$ROOT_DIR/dist/collector.zip"

python -m pip install --upgrade pip

rm -rf "$BUILD_DIR"
mkdir -p "$BUILD_DIR"
mkdir -p "$ROOT_DIR/dist"

pip install -r "$ROOT_DIR/requirements-lambda.txt" -t "$BUILD_DIR"

cp -R "$ROOT_DIR/src/collector" "$BUILD_DIR/collector"
cp "$ROOT_DIR/alembic.ini" "$BUILD_DIR/alembic.ini"
cp -R "$ROOT_DIR/alembic" "$BUILD_DIR/db_migrations"

find "$BUILD_DIR" -type d -name "__pycache__" -prune -exec rm -rf {} +
find "$BUILD_DIR" -type f -name "*.pyc" -delete

rm -f "$OUTPUT_ZIP"
(
  cd "$BUILD_DIR"
  zip -qr "$OUTPUT_ZIP" .
)

echo "Packaged Lambda artifact: $OUTPUT_ZIP"

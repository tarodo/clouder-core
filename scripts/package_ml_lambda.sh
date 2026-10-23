#!/usr/bin/env bash
# dist/ml_worker.zip: the ML worker's own zip (numpy, scikit-learn), so collector.zip stays small.
# Linux wheels whatever the host; Terraform uploads it through S3 (infra/lambda.tf).
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BUILD_DIR="$ROOT_DIR/dist/ml_worker_build"
OUTPUT_ZIP="$ROOT_DIR/dist/ml_worker.zip"
MAX_MB=240 # Lambda refuses more than 250 MB unzipped

rm -rf "$BUILD_DIR" "$OUTPUT_ZIP"
mkdir -p "$BUILD_DIR"

# numpy >= 2.3 ships manylinux_2_28 wheels only; the python3.12 runtime (AL2023, glibc 2.34) runs both.
python -m pip install --quiet --disable-pip-version-check \
  --platform manylinux2014_x86_64 --platform manylinux_2_28_x86_64 \
  --implementation cp --python-version 3.12 --only-binary=:all: \
  -r "$ROOT_DIR/requirements-ml.txt" -t "$BUILD_DIR"

cp -R "$ROOT_DIR/src/collector" "$BUILD_DIR/collector"

find "$BUILD_DIR" -type d \( -name tests -o -name __pycache__ \) -prune -exec rm -rf {} +
find "$BUILD_DIR" -type f -name "*.pyc" -delete

size_mb=$(python - "$BUILD_DIR" <<'PY'
import sys
from pathlib import Path

print(sum(p.stat().st_size for p in Path(sys.argv[1]).rglob("*") if p.is_file()) // 2**20)
PY
)
echo "ML worker unzipped: ${size_mb} MB (limit ${MAX_MB} MB)"
if [ "$size_mb" -ge "$MAX_MB" ]; then
  echo "ML worker package is too big for a zip Lambda" >&2
  exit 1
fi

# Byte-reproducible: same files, same zip, so Terraform uploads and publishes only on change.
python "$ROOT_DIR/scripts/deterministic_zip.py" "$BUILD_DIR" "$OUTPUT_ZIP"
echo "Packaged ML worker artifact: $OUTPUT_ZIP ($(du -h "$OUTPUT_ZIP" | cut -f1) zipped)"

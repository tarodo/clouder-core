#!/usr/bin/env python3
"""Download one raw releases.json.gz from S3, print fields relevant to release_type.

Usage:
    python scripts/inspect_raw_sample.py <s3_key>
    # e.g. raw/bp/releases/style_id=5/year=2026/week=9/releases.json.gz
"""
from __future__ import annotations

import gzip
import json
import os
import sys
from collections import Counter

import boto3


def main(s3_key: str) -> None:
    bucket = os.environ["RAW_BUCKET_NAME"]
    s3 = boto3.client("s3")
    body = s3.get_object(Bucket=bucket, Key=s3_key)["Body"].read()
    payload = json.loads(gzip.decompress(body))

    if isinstance(payload, list):
        releases = payload
    elif isinstance(payload, dict):
        releases = (
            payload.get("releases")
            or payload.get("data")
            or payload.get("results")
            or []
        )
    else:
        releases = []
    print(f"Total releases: {len(releases)}")

    type_counter: Counter[str] = Counter()
    keys_seen: Counter[str] = Counter()
    va_flags = 0

    for release in releases[:50]:
        keys_seen.update(release.keys())
        for field in ("type", "release_type", "is_compilation", "various_artists"):
            if field in release:
                val = release[field]
                type_counter[f"{field}={val}"] += 1
        artists = release.get("artists") or []
        if isinstance(artists, list) and len(artists) >= 4:
            va_flags += 1

    print("\nTop-level keys frequency (first 50):")
    for k, v in keys_seen.most_common():
        print(f"  {k}: {v}")

    print("\nType-related field values:")
    for k, v in type_counter.most_common():
        print(f"  {k}: {v}")

    print(f"\nReleases with >=4 artists (VA heuristic hit): {va_flags}")

    print("\nFirst release (pretty):")
    print(json.dumps(releases[0], indent=2, ensure_ascii=False))


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("Usage: inspect_raw_sample.py <s3_key>")
    main(sys.argv[1])

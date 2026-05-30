"""Enqueue YT Music match jobs for tracks already in playlists.

Usage:
    PYTHONPATH=src VENDOR_MATCH_QUEUE_URL=<url> .venv/bin/python \
        scripts/backfill_vendor_match.py

Idempotent: tracks already matched or already attempted (in match_review_queue)
are skipped by fetch_unmatched_match_inputs.
"""

from __future__ import annotations

import os
import sys

import boto3

from collector.curation.playlists_repository import create_default_playlists_repository
from collector.vendor_match.enqueue import YTMUSIC_VENDOR, enqueue_vendor_matches


def main() -> int:
    queue_url = os.environ.get("VENDOR_MATCH_QUEUE_URL", "").strip()
    if not queue_url:
        print("VENDOR_MATCH_QUEUE_URL is required", file=sys.stderr)
        return 2

    repo = create_default_playlists_repository()
    if repo is None:
        print("Data API not configured", file=sys.stderr)
        return 2

    track_ids = [
        r["track_id"]
        for r in repo.data_api.execute(
            "SELECT DISTINCT track_id FROM playlist_tracks", {}
        )
    ]
    if not track_ids:
        print("No playlist tracks found.")
        return 0

    sqs = boto3.client("sqs")
    total = 0
    batch = 100
    for start in range(0, len(track_ids), batch):
        chunk = track_ids[start : start + batch]
        inputs = repo.fetch_unmatched_match_inputs(track_ids=chunk, vendor=YTMUSIC_VENDOR)
        total += enqueue_vendor_matches(
            track_inputs=inputs, vendor=YTMUSIC_VENDOR,
            queue_url=queue_url, sqs=sqs, correlation_id="backfill",
        )
    print(f"Enqueued {total} ytmusic match jobs from {len(track_ids)} playlist tracks.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

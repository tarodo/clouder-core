"""One-off: backfill artists for Spotify-imported tracks missing them, then
re-enqueue YT Music matching.

Tracks imported before the artist-persistence fix have no clouder_track_artists
rows, so the ytmusic vendor-match dropped them (empty artist). This finds those
tracks, fetches artists from Spotify (client-credentials catalog read), writes
them, and re-enqueues the match.

Usage:
    PYTHONPATH=src .venv/bin/python scripts/backfill_spotify_import_artists.py --dry-run
    PYTHONPATH=src .venv/bin/python scripts/backfill_spotify_import_artists.py --apply
"""
from __future__ import annotations

import argparse
import uuid
from datetime import datetime, timezone

import boto3

from collector.data_api import create_default_data_api_client
from collector.models import normalize_text
from collector.settings import (
    get_data_api_settings,
    get_api_settings,
    get_spotify_worker_settings,
)
from collector.spotify_client import SpotifyClient
from collector.vendor_match.enqueue import YTMUSIC_VENDOR, enqueue_vendor_matches
from collector.curation.playlists_repository import MatchInput


def _find_artistless(data_api) -> list[dict]:
    return data_api.execute(
        """
        SELECT t.id, t.spotify_id, t.title, t.isrc, t.length_ms
        FROM clouder_tracks t
        LEFT JOIN clouder_track_artists cta ON cta.track_id = t.id
        WHERE t.origin = 'spotify_user_import'
          AND t.spotify_id IS NOT NULL
          AND cta.track_id IS NULL
        """,
        {},
    )


def _upsert_artist(data_api, name: str, now: datetime, tx_id: str) -> str:
    norm = normalize_text(name)
    found = data_api.execute(
        "SELECT id FROM clouder_artists WHERE normalized_name = :n LIMIT 1",
        {"n": norm}, transaction_id=tx_id,
    )
    if found:
        return found[0]["id"]
    aid = str(uuid.uuid4())
    data_api.execute(
        """
        INSERT INTO clouder_artists (id, name, normalized_name, created_at, updated_at)
        VALUES (:id, :name, :n, :now, :now)
        """,
        {"id": aid, "name": name.strip(), "n": norm, "now": now},
        transaction_id=tx_id,
    )
    return aid


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="write changes (default: dry-run)")
    parser.add_argument(
        "--dry-run", action="store_true",
        help="preview only (default; explicit for clarity)",
    )
    args = parser.parse_args()
    now = datetime.now(timezone.utc)

    db = get_data_api_settings()
    data_api = create_default_data_api_client(
        resource_arn=str(db.aurora_cluster_arn),
        secret_arn=str(db.aurora_secret_arn),
        database=db.aurora_database,
    )
    rows = _find_artistless(data_api)
    print(f"found {len(rows)} artist-less imported tracks")
    if not rows:
        return

    sp = get_spotify_worker_settings()
    client = SpotifyClient(client_id=sp.spotify_client_id, client_secret=sp.spotify_client_secret)
    sids = [r["spotify_id"] for r in rows]
    artists_by_sid = client.get_tracks(sids, correlation_id="backfill")

    healed: list[str] = []
    for r in rows:
        names = artists_by_sid.get(r["spotify_id"], [])
        if not names:
            print(f"  skip {r['id']} ({r['spotify_id']}): no artists from Spotify")
            continue
        print(f"  {r['id']} <- {names}" + ("" if args.apply else " (dry-run)"))
        if not args.apply:
            continue
        with data_api.transaction() as tx_id:
            for name in names:
                aid = _upsert_artist(data_api, name, now, tx_id)
                data_api.execute(
                    """
                    INSERT INTO clouder_track_artists (track_id, artist_id, role)
                    VALUES (:tid, :aid, 'main')
                    ON CONFLICT DO NOTHING
                    """,
                    {"tid": r["id"], "aid": aid}, transaction_id=tx_id,
                )
        healed.append(r["id"])

    if args.apply and healed:
        queue_url = get_api_settings().vendor_match_queue_url
        if queue_url:
            inputs = [
                MatchInput(
                    track_id=r["id"],
                    artist=", ".join(artists_by_sid.get(r["spotify_id"], [])),
                    title=r["title"], isrc=r.get("isrc"),
                    duration_ms=r.get("length_ms"), album=None,
                )
                for r in rows if r["id"] in healed
            ]
            n = enqueue_vendor_matches(
                track_inputs=inputs, vendor=YTMUSIC_VENDOR,
                queue_url=queue_url, sqs=boto3.client("sqs"),
                correlation_id="backfill",
            )
            print(f"re-enqueued {n} ytmusic matches")
        else:
            print("VENDOR_MATCH_QUEUE_URL not set — skipped re-enqueue")

    print(f"done. healed={len(healed)}")


if __name__ == "__main__":
    main()

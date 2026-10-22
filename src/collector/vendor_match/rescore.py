"""Close open YT Music reviews the version rule accepts, from stored candidates.

Reviews queued before the version rule (#349) hold candidates the search would
now accept by itself. This replays the rule on each open review's top stored
candidate (no YouTube request) and, for an accepted one, links the track as
`fuzzy_version` and resolves the review, the way a manual accept does.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from datetime import datetime
from decimal import Decimal
from typing import Any

from ..data_api import DataAPIClient
from ..repositories import ClouderRepository, UpsertVendorMatchCmd
from .scorer import FuzzyScore, version_rule_accepts


def open_reviews(client: DataAPIClient, *, after: str, limit: int) -> list[dict[str, Any]]:
    """Open YT Music reviews after review id *after*, with our title and mix and
    the top candidate by stored score (one, so a page stays far under 1 MB)."""
    rows = client.execute(
        """
        SELECT q.id AS review_id, q.clouder_track_id AS track_id, t.title, t.mix_name,
               t.length_ms, c.candidate,
               (SELECT string_agg(a.name, ', ' ORDER BY a.name)
                FROM clouder_track_artists ta JOIN clouder_artists a ON a.id = ta.artist_id
                WHERE ta.track_id = t.id) AS artists
        FROM match_review_queue q
        JOIN clouder_tracks t ON t.id = q.clouder_track_id
        CROSS JOIN LATERAL (
            SELECT e AS candidate FROM jsonb_array_elements(q.candidates) e
            ORDER BY (e->>'score')::numeric DESC NULLS LAST LIMIT 1
        ) c
        WHERE q.vendor = 'ytmusic' AND q.status = 'pending' AND q.id > :after
          AND NOT EXISTS (SELECT 1 FROM vendor_track_map v
                          WHERE v.clouder_track_id = q.clouder_track_id AND v.vendor = 'ytmusic')
        ORDER BY q.id
        LIMIT :limit
        """,
        {"after": after, "limit": limit},
    )
    for row in rows:
        if isinstance(row["candidate"], str):
            row["candidate"] = json.loads(row["candidate"])
    return rows


def decide(row: Mapping[str, Any]) -> bool:
    cand = row["candidate"] or {}
    ref = cand.get("ref") or {}
    if not ref.get("videoId") or cand.get("score") is None:
        return False
    score = FuzzyScore(
        title_sim=float(cand.get("title_sim") or 0.0),
        artist_sim=float(cand.get("artist_sim") or 0.0),
        duration_ok=bool(cand.get("duration_ok")),
        album_bonus=float(cand.get("album_bonus") or 0.0),
        total=float(cand["score"]),
    )
    return version_rule_accepts(
        candidate_title=str(ref.get("title") or ""),
        title=str(row["title"] or ""),
        mix_name=row.get("mix_name"),
        score=score,
    )


def accept(client: DataAPIClient, rows: Iterable[Mapping[str, Any]], now: datetime) -> int:
    """Link and resolve *rows* in one transaction; returns how many."""
    rows = list(rows)
    if not rows:
        return 0
    repository = ClouderRepository(client)
    with client.transaction() as tx:
        for row in rows:
            cand = row["candidate"]
            repository.upsert_vendor_match(
                UpsertVendorMatchCmd(
                    clouder_track_id=row["track_id"],
                    vendor="ytmusic",
                    vendor_track_id=cand["ref"]["videoId"],
                    match_type="fuzzy_version",
                    confidence=Decimal(str(cand["score"])),
                    matched_at=now,
                    payload=cand["ref"],
                ),
                transaction_id=tx,
            )
            client.execute(
                "UPDATE match_review_queue SET status = 'resolved', resolved_at = :now"
                " WHERE id = :id AND status = 'pending'",
                {"id": row["review_id"], "now": now},
                transaction_id=tx,
            )
    return len(rows)

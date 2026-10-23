"""Close open YT Music reviews the version rule accepts, from stored candidates.

Reviews queued before the version rule (#349), or while it only looked at the
best candidate, hold candidates the search would now accept by itself. This
replays the rule on each open review's stored candidates, best first (no
YouTube request), and links the first it accepts as `fuzzy_version`, resolving
the review the way a manual accept does.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from datetime import datetime
from decimal import Decimal
from typing import Any

from ..data_api import DataAPIClient
from ..providers.ytmusic.normalize import result_to_ref
from ..repositories import ClouderRepository, UpsertVendorMatchCmd
from ..repositories.youtube_search import SECOND_CHANCE_DAYS
from ..settings import get_vendor_match_settings
from .scorer import candidate_names_track, same_version, score_candidate, version_rule_accepts


def open_reviews(client: DataAPIClient, *, after: str, limit: int) -> list[dict[str, Any]]:
    """Open YT Music reviews after review id *after*, with our title and mix and
    the stored candidates best first (full payloads: about 10 KB a review, so
    keep *limit* near 50 to stay under the Data API's 1 MB)."""
    rows = client.execute(
        """
        SELECT q.id AS review_id, q.clouder_track_id AS track_id, t.title, t.mix_name,
               t.length_ms, alb.title AS album_title,
               (SELECT jsonb_agg(e ORDER BY (e->>'score')::numeric DESC NULLS LAST)
                FROM jsonb_array_elements(q.candidates) e) AS candidates,
               COALESCE(q.created_at < t.publish_date + :days * interval '1 day', FALSE) AS early,
               (SELECT string_agg(a.name, ', ' ORDER BY a.name)
                FROM clouder_track_artists ta JOIN clouder_artists a ON a.id = ta.artist_id
                WHERE ta.track_id = t.id) AS artists
        FROM match_review_queue q
        JOIN clouder_tracks t ON t.id = q.clouder_track_id
        LEFT JOIN clouder_albums alb ON alb.id = t.album_id
        WHERE q.vendor = 'ytmusic' AND q.status = 'pending' AND q.id > :after
          AND NOT EXISTS (SELECT 1 FROM vendor_track_map v
                          WHERE v.clouder_track_id = q.clouder_track_id AND v.vendor = 'ytmusic')
        ORDER BY q.id
        LIMIT :limit
        """,
        {"after": after, "limit": limit, "days": SECOND_CHANCE_DAYS},
    )
    for row in rows:
        if isinstance(row["candidates"], str):
            row["candidates"] = json.loads(row["candidates"])
        row["candidates"] = row["candidates"] or []
    return rows


def decide(row: Mapping[str, Any]) -> dict[str, Any] | None:
    """Score each stored candidate again with the current scorer (folding,
    version rule and all), best first: one at the threshold is a plain match,
    else the first the version rule accepts. The chosen candidate comes back
    with its new score and match type."""
    scored = []
    for cand in row["candidates"]:
        ref = result_to_ref(cand.get("ref") or {})
        if ref is None:
            continue
        score = score_candidate(
            candidate=ref,
            artist=str(row.get("artists") or ""),
            title=str(row["title"] or ""),
            duration_ms=row.get("length_ms"),
            album=row.get("album_title"),
        )
        scored.append((cand, ref, score))
    scored.sort(key=lambda t: t[2].total, reverse=True)
    threshold = get_vendor_match_settings().fuzzy_match_threshold
    if scored and scored[0][2].total >= threshold:
        cand, ref, score = scored[0]
        if same_version(ref.title, str(row["title"] or ""), row.get("mix_name")):
            return {**cand, "score": score.total, "match_type": "fuzzy"}
    for cand, ref, score in scored:
        if version_rule_accepts(
            candidate_title=ref.title,
            title=str(row["title"] or ""),
            mix_name=row.get("mix_name"),
            score=score,
        ):
            return {**cand, "score": score.total, "match_type": "fuzzy_version"}
    return None


def artist_absent(row: Mapping[str, Any]) -> bool:
    """No stored candidate is our artist with a like title, so YouTube does
    not have the track; an early search waits for its second chance instead."""
    if row.get("early"):
        return False
    ours = [a for a in (row.get("artists") or "").split(", ") if a]
    verdicts = [
        candidate_names_track(
            ours,
            str(row["title"] or ""),
            row.get("mix_name"),
            str((c.get("ref") or {}).get("title") or ""),
            [str(a.get("name") or "") for a in (c.get("ref") or {}).get("artists") or []],
        )
        for c in row["candidates"]
    ]
    return bool(verdicts) and all(v is False for v in verdicts)


def close_absent(client: DataAPIClient, rows: Iterable[Mapping[str, Any]], now: datetime) -> int:
    """Close *rows* as not on YouTube, as a person's reject does (the open row
    goes, an empty no_match row stays), in one transaction; returns how many."""
    rows = list(rows)
    if not rows:
        return 0
    repository = ClouderRepository(client)
    with client.transaction() as tx:
        for row in rows:
            client.execute(
                "DELETE FROM match_review_queue WHERE id = :id AND status = 'pending'",
                {"id": row["review_id"]},
                transaction_id=tx,
            )
            repository.mark_no_match(
                clouder_track_id=row["track_id"],
                vendor="ytmusic",
                created_at=now,
                transaction_id=tx,
            )
    return len(rows)


def accept(client: DataAPIClient, rows: Iterable[Mapping[str, Any]], now: datetime) -> int:
    """Link each row's chosen `candidate` and resolve its review, in one
    transaction; returns how many."""
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
                    match_type=cand.get("match_type", "fuzzy_version"),
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

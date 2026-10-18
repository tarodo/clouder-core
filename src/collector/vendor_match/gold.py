"""Read-only extraction of the YT Music matching gold set (offline evaluation).

The owner runs these queries against production through
scripts/export_match_gold.py; no Lambda calls this module. `artist` is built
exactly like the vendor-match input (STRING_AGG of distinct names, ordered), so
re-scoring reproduces what the worker saw.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any


def _json(value: Any) -> Any:
    return json.loads(value) if isinstance(value, str) else value


def _query_fields(row: Mapping[str, Any]) -> dict[str, Any]:
    length = row.get("length_ms")
    return {
        "artist": row.get("artist_names") or "",
        "title": row.get("title") or "",
        "duration_ms": int(length) if length is not None else None,
        "album": row.get("album_title"),
    }


def review_accepts(client: Any) -> list[dict[str, Any]]:
    """Resolved review items with their scored candidates and the human's choice."""
    rows = client.execute(
        """
        SELECT DISTINCT ON (q.clouder_track_id)
               q.clouder_track_id AS track_id,
               q.candidates,
               m.vendor_track_id AS chosen_id,
               t.title,
               t.length_ms,
               alb.title AS album_title,
               (SELECT COALESCE(STRING_AGG(DISTINCT a.name, ', ' ORDER BY a.name), '')
                  FROM clouder_track_artists cta
                  JOIN clouder_artists a ON a.id = cta.artist_id
                 WHERE cta.track_id = t.id) AS artist_names
        FROM match_review_queue q
        JOIN vendor_track_map m
          ON m.clouder_track_id = q.clouder_track_id
         AND m.vendor = q.vendor
         AND m.match_type = 'manual'
        JOIN clouder_tracks t ON t.id = q.clouder_track_id
        LEFT JOIN clouder_albums alb ON alb.id = t.album_id
        WHERE q.vendor = 'ytmusic' AND q.status = 'resolved'
        ORDER BY q.clouder_track_id, q.resolved_at DESC NULLS LAST
        """
    )
    return [
        {
            "kind": "review_accept",
            "track_id": row["track_id"],
            **_query_fields(row),
            "chosen_id": row["chosen_id"],
            "candidates": [c.get("ref") or {} for c in candidates],
            # What the worker scored at the time, to detect metadata drift since.
            "stored_top_score": max(
                (float(c["score"]) for c in candidates if isinstance(c.get("score"), (int, float))),
                default=None,
            ),
        }
        for row in rows
        for candidates in [_json(row["candidates"]) or []]
    ]


def auto_sample(client: Any, n: int) -> list[dict[str, Any]]:
    """A deterministic sample (md5 order) of auto-accepted fuzzy matches to label by hand."""
    rows = client.execute(
        """
        SELECT m.clouder_track_id AS track_id,
               m.payload,
               m.confidence,
               t.title,
               t.length_ms,
               alb.title AS album_title,
               (SELECT COALESCE(STRING_AGG(DISTINCT a.name, ', ' ORDER BY a.name), '')
                  FROM clouder_track_artists cta
                  JOIN clouder_artists a ON a.id = cta.artist_id
                 WHERE cta.track_id = t.id) AS artist_names
        FROM vendor_track_map m
        JOIN clouder_tracks t ON t.id = m.clouder_track_id
        LEFT JOIN clouder_albums alb ON alb.id = t.album_id
        WHERE m.vendor = 'ytmusic' AND m.match_type IN ('fuzzy', 'fuzzy_version')
        ORDER BY md5(m.clouder_track_id)
        LIMIT :n
        """,
        {"n": n},
    )
    return [
        {
            "kind": "auto_sample",
            "track_id": row["track_id"],
            **_query_fields(row),
            "confidence": float(row["confidence"]),
            "candidate": _json(row["payload"]) or {},
        }
        for row in rows
    ]


def auto_population(client: Any) -> dict[str, Any]:
    """How many auto-accepted fuzzy matches the hand-labelled sample stands for."""
    (row,) = client.execute(
        """
        SELECT count(*) AS fuzzy
        FROM vendor_track_map
        WHERE vendor = 'ytmusic' AND match_type IN ('fuzzy', 'fuzzy_version')
        """
    )
    return {"kind": "auto_population", "fuzzy": int(row["fuzzy"])}


def duplicate_artists(client: Any) -> dict[str, Any]:
    """Artists sharing a normalized name — measured before any merge tooling exists."""
    (row,) = client.execute(
        """
        WITH groups AS (
            SELECT a.normalized_name,
                   count(*) AS n,
                   count(*) FILTER (WHERE im.clouder_id IS NULL) AS without_beatport_identity
            FROM clouder_artists a
            LEFT JOIN identity_map im
              ON im.clouder_id = a.id
             AND im.source = 'beatport'
             AND im.entity_type = 'artist'
            GROUP BY a.normalized_name
            HAVING count(*) > 1
        )
        SELECT count(*) AS name_groups,
               COALESCE(sum(n), 0) AS artists_in_groups,
               count(*) FILTER (WHERE without_beatport_identity > 0) AS groups_with_non_beatport_artist
        FROM groups
        """
    )
    return {
        "kind": "duplicate_artists",
        "name_groups": int(row["name_groups"]),
        "artists_in_groups": int(row["artists_in_groups"]),
        "groups_with_non_beatport_artist": int(row["groups_with_non_beatport_artist"]),
    }


def review_band_sample(
    client: Any, bands: list[tuple[float, float]], per_band: int
) -> list[dict[str, Any]]:
    """A deterministic sample (md5 order) of open review items per band of the top
    candidate's score, with the track's mix name and length next to the candidate's,
    to label by hand before moving the auto-accept threshold or the scoring."""
    params: dict[str, Any] = {"n": per_band}
    values = []
    for i, (lo, hi) in enumerate(bands):
        params |= {f"label{i}": f"{lo:.2f}-{hi:.2f}", f"lo{i}": lo, f"hi{i}": hi}
        values.append(f"(:label{i}, CAST(:lo{i} AS numeric), CAST(:hi{i} AS numeric))")
    rows = client.execute(
        f"""
        WITH pending AS (
            SELECT q.clouder_track_id AS track_id,
                   (SELECT c FROM jsonb_array_elements(q.candidates) c
                     ORDER BY (c->>'score')::numeric DESC NULLS LAST LIMIT 1) AS top
            FROM match_review_queue q
            WHERE q.vendor = 'ytmusic' AND q.status = 'pending'
        ), bands(label, lo, hi) AS (VALUES {", ".join(values)}),
        banded AS (
            SELECT p.track_id, p.top, b.label,
                   row_number() OVER (PARTITION BY b.label ORDER BY md5(p.track_id)) AS rn
            FROM pending p
            JOIN bands b ON (p.top->>'score')::numeric >= b.lo AND (p.top->>'score')::numeric < b.hi
        )
        SELECT bd.track_id, bd.top, bd.label, t.title, t.mix_name, t.length_ms,
               alb.title AS album_title,
               (SELECT COALESCE(STRING_AGG(DISTINCT a.name, ', ' ORDER BY a.name), '')
                  FROM clouder_track_artists cta
                  JOIN clouder_artists a ON a.id = cta.artist_id
                 WHERE cta.track_id = t.id) AS artist_names
        FROM banded bd
        JOIN clouder_tracks t ON t.id = bd.track_id
        LEFT JOIN clouder_albums alb ON alb.id = t.album_id
        WHERE bd.rn <= :n
        ORDER BY bd.label DESC, bd.rn
        """,
        params,
    )
    out = []
    for row in rows:
        top = _json(row["top"]) or {}
        ref = top.get("ref") or {}
        seconds = ref.get("duration_seconds")
        out.append(
            {
                "kind": "band_sample",
                "band": row["label"],
                "track_id": row["track_id"],
                **_query_fields(row),
                "mix_name": row.get("mix_name"),
                "candidate": ref,
                "candidate_duration_ms": round(seconds * 1000)
                if isinstance(seconds, (int, float))
                else None,
                "score": float(top["score"])
                if isinstance(top.get("score"), (int, float))
                else None,
                "title_sim": top.get("title_sim"),
                "artist_sim": top.get("artist_sim"),
                "duration_ok": top.get("duration_ok"),
            }
        )
    return out

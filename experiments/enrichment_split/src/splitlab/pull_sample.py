"""Stratified sample from prod: per kind, N/2 instagram-missing + N/2 random
with instagram present. Baseline = the existing prod merged payload."""

from __future__ import annotations

import json
from typing import Callable

from .config import Settings

_IG_NULL = "(merged->>'instagram_url' IS NULL OR merged->>'instagram_url' = '')"

_LABEL_SQL = """
SELECT l.id::text AS id, l.name AS name,
       coalesce((
           SELECT s.name FROM clouder_albums a
           JOIN clouder_tracks t ON t.album_id = a.id
           JOIN clouder_styles s ON s.id = t.style_id
           WHERE a.label_id = l.id
           GROUP BY s.name ORDER BY count(*) DESC LIMIT 1
       ), 'electronic music') AS style,
       li.merged::text AS merged
FROM clouder_label_info li
JOIN clouder_labels l ON l.id = li.label_id
WHERE {where}
ORDER BY random() LIMIT {limit}
"""

_ARTIST_SQL = """
SELECT ar.id::text AS id, ar.name AS name,
       coalesce((
           SELECT s.name FROM clouder_track_artists ta
           JOIN clouder_tracks t ON t.id = ta.track_id
           JOIN clouder_styles s ON s.id = t.style_id
           WHERE ta.artist_id = ar.id
           GROUP BY s.name ORDER BY count(*) DESC LIMIT 1
       ), 'electronic music') AS style,
       ai.merged::text AS merged,
       coalesce((
           SELECT string_agg(title, '|') FROM (
               SELECT t.title FROM clouder_track_artists ta
               JOIN clouder_tracks t ON t.id = ta.track_id
               WHERE ta.artist_id = ar.id
               ORDER BY t.publish_date DESC NULLS LAST LIMIT 3
           ) x
       ), '') AS sample_tracks,
       coalesce((
           SELECT string_agg(DISTINCT l.name, '|') FROM clouder_track_artists ta
           JOIN clouder_tracks t ON t.id = ta.track_id
           JOIN clouder_albums a ON a.id = t.album_id
           JOIN clouder_labels l ON l.id = a.label_id
           WHERE ta.artist_id = ar.id
       ), '') AS known_labels
FROM clouder_artist_info ai
JOIN clouder_artists ar ON ar.id = ai.artist_id
WHERE {where}
ORDER BY random() LIMIT {limit}
"""


def _default_execute(settings: Settings) -> Callable[[str], list[dict]]:
    import boto3

    client = boto3.client("rds-data", region_name="us-east-1")

    def execute(sql: str) -> list[dict]:
        resp = client.execute_statement(
            resourceArn=settings.cluster_arn,
            secretArn=settings.secret_arn,
            database=settings.database,
            sql=sql,
            formatRecordsAs="JSON",
        )
        return json.loads(resp.get("formattedRecords") or "[]")

    return execute


def _rows_to_entities(rows: list[dict], stratum: str, kind: str) -> list[dict]:
    out = []
    for r in rows:
        merged = r.get("merged")
        baseline = json.loads(merged) if isinstance(merged, str) else (merged or {})
        out.append({
            "id": str(r["id"]),
            "name": r["name"],
            "style": r.get("style") or "electronic music",
            "stratum": stratum,
            "baseline": baseline,
            "sample_tracks": [t for t in (r.get("sample_tracks") or "").split("|") if t],
            "known_labels": [t for t in (r.get("known_labels") or "").split("|") if t],
        })
    return out


def pull(
    settings: Settings,
    execute: Callable[[str], list[dict]] | None = None,
    labels: int = 50,
    artists: int = 50,
) -> dict:
    execute = execute or _default_execute(settings)
    data: dict = {"labels": [], "artists": []}
    for kind, sql, total in (("labels", _LABEL_SQL, labels), ("artists", _ARTIST_SQL, artists)):
        half = total // 2
        for stratum, where, limit in (
            ("ig_missing", _IG_NULL, half),
            ("random", f"NOT {_IG_NULL}", total - half),
        ):
            rows = execute(sql.format(where=where, limit=limit))
            data[kind].extend(_rows_to_entities(rows, stratum, kind))
    return data

"""The tracks of a label or an artist for the player on its page: newest release first, each with
the categories and playlists of the user it already sits in."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any, Literal

from .api.http import _parse_pagination_params
from .data_api import DataAPIClient, create_default_data_api_client
from .errors import ValidationError
from .repositories.analysis import AI_VERDICT_SQL, ai_rep_sql, parse_ai_rep
from .settings import get_data_api_settings

Kind = Literal["label", "artist"]

# The entity's tracks (`t`); served by ix_clouder_albums_label / ix_clouder_track_artists_artist.
_TRACKS: dict[Kind, str] = {
    "label": """FROM clouder_albums alb JOIN clouder_tracks t ON t.album_id = alb.id
        WHERE alb.label_id = :entity_id""",
    "artist": """FROM clouder_tracks t WHERE t.id IN (
        SELECT track_id FROM clouder_track_artists WHERE artist_id = :entity_id)""",
}
# The page first, the per-track lookups only for its rows. The user's categories / playlists come
# first in each lookup so the (category_id, track_id) / (playlist_id, track_id) keys serve it.
_PAGE = """
WITH page AS (
    SELECT t.id, coalesce(t.publish_date, t.spotify_release_date) AS release_date
    {tracks}
    ORDER BY release_date DESC NULLS LAST, t.id
    LIMIT :limit OFFSET :offset
)
SELECT t.id, t.title, t.mix_name, t.bpm, t.length_ms, t.key_name, t.key_camelot, t.spotify_id,
       p.release_date, t.style_id, s.name AS style_name, {ai_verdict},
       l.id AS label_id, l.name AS label_name, {label_ai} AS label_ai,
       (SELECT coalesce(json_agg(json_build_object('id', a.id, 'name', a.name, 'ai', {artist_ai})
                                 ORDER BY cta.role, a.name), '[]'::json)
        FROM clouder_track_artists cta JOIN clouder_artists a ON a.id = cta.artist_id
        WHERE cta.track_id = t.id) AS artists_json,
       (SELECT coalesce(json_agg(json_build_object('id', c.id, 'name', c.name)
                                 ORDER BY c.position, c.name), '[]'::json)
        FROM categories c JOIN category_tracks ct ON ct.category_id = c.id AND ct.track_id = t.id
        WHERE c.user_id = :user_id AND c.deleted_at IS NULL) AS categories_json,
       (SELECT coalesce(json_agg(json_build_object('id', pl.id, 'name', pl.name)
                                 ORDER BY pl.name), '[]'::json)
        FROM playlists pl JOIN playlist_tracks pt ON pt.playlist_id = pl.id AND pt.track_id = t.id
        WHERE pl.user_id = :user_id AND pl.deleted_at IS NULL) AS playlists_json
FROM page p
JOIN clouder_tracks t ON t.id = p.id
LEFT JOIN clouder_styles s ON s.id = t.style_id
LEFT JOIN clouder_albums alb ON alb.id = t.album_id
LEFT JOIN clouder_labels l ON l.id = alb.label_id
ORDER BY p.release_date DESC NULLS LAST, t.id
"""


def _json(value: Any) -> Any:
    """A json column as the Data API (text) or psycopg (decoded) returns it."""
    return json.loads(value) if isinstance(value, str) else value


def _date(value: Any) -> str | None:
    return value.isoformat() if hasattr(value, "isoformat") else value


def _track(r: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "id": r["id"],
        "title": r["title"],
        "mix_name": r["mix_name"],
        "artists": [{**a, "ai": parse_ai_rep(a.get("ai"))} for a in _json(r["artists_json"])],
        "label": (
            {"id": r["label_id"], "name": r["label_name"], "ai": parse_ai_rep(r["label_ai"])}
            if r["label_id"]
            else None
        ),
        "style": {"id": r["style_id"], "name": r["style_name"]} if r["style_id"] else None,
        "bpm": r["bpm"],
        "length_ms": r["length_ms"],
        "key_name": r["key_name"],
        "key_camelot": r["key_camelot"],
        "release_date": _date(r["release_date"]),
        "spotify_id": r["spotify_id"],
        "ai_verdict": r["ai_verdict"],
        "categories": _json(r["categories_json"]),
        "playlists": _json(r["playlists_json"]),
    }


class EntityTracksRepository:
    def __init__(self, data_api: DataAPIClient) -> None:
        self._data_api = data_api

    def list_tracks(
        self, *, kind: Kind, entity_id: str, user_id: str, limit: int, offset: int
    ) -> tuple[list[dict[str, Any]], int]:
        tracks = _TRACKS[kind]
        rows = self._data_api.execute(
            _PAGE.format(
                tracks=tracks,
                ai_verdict=AI_VERDICT_SQL,
                label_ai=ai_rep_sql("l"),
                artist_ai=ai_rep_sql("a"),
            ),
            {"entity_id": entity_id, "user_id": user_id, "limit": limit, "offset": offset},
        )
        (count,) = self._data_api.execute(
            f"SELECT count(*) AS n {tracks}", {"entity_id": entity_id}
        )
        return [_track(r) for r in rows], int(count["n"])


def _build_repository() -> EntityTracksRepository:
    settings = get_data_api_settings()
    if not settings.is_configured:
        raise RuntimeError("Aurora Data API not configured")
    return EntityTracksRepository(
        create_default_data_api_client(
            resource_arn=str(settings.aurora_cluster_arn),
            secret_arn=str(settings.aurora_secret_arn),
            database=settings.aurora_database,
        )
    )


def _user_id(event: Mapping[str, Any]) -> str:
    ctx = ((event.get("requestContext") or {}).get("authorizer") or {}).get("lambda") or {}
    return str(ctx.get("user_id") or "")


def _handle(event: Mapping[str, Any], kind: Kind, param: str) -> tuple[int, dict]:
    entity_id = ((event.get("pathParameters") or {}).get(param) or "").strip()
    if not entity_id:
        raise ValidationError(f"{param} is required")
    limit, offset, _ = _parse_pagination_params(event)
    items, total = _build_repository().list_tracks(
        kind=kind, entity_id=entity_id, user_id=_user_id(event), limit=limit, offset=offset
    )
    return 200, {"items": items, "total": total, "limit": limit, "offset": offset}


def handle_label_tracks(event: Mapping[str, Any]) -> tuple[int, dict]:
    return _handle(event, "label", "label_id")


def handle_artist_tracks(event: Mapping[str, Any]) -> tuple[int, dict]:
    return _handle(event, "artist", "artist_id")

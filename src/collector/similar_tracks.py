"""Similar tracks (spec 2026-11-01): the tracks of a style that sound nearest to a track, or to an
artist's centroid, for the player of the similar page / the artist page's Similar view.

Nearest by cosine distance of the sim vectors (`audio_embeddings`), never AI-flagged, one track per
video; the user's keeps first (a keep placement, else no DISCARD and the keep head's prediction),
then by distance. Rows are the entity player's, plus `discarded`.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .data_api import DataAPIClient
from .entity_tracks import caller_id, data_api_client, row_select, track_row
from .errors import ValidationError
from .repositories.analysis import AI_FLAGGED_SQL
from .repositories.ml import PLACEMENTS_SQL
from .repositories.similarity import VERSION

LIMIT = 50

# A profiled track of the style: `t` with its video `v` and vector `e` of the live version.
_PROFILED = """clouder_tracks t
    JOIN vendor_track_map v ON v.clouder_track_id = t.id AND v.vendor = 'ytmusic'
    JOIN audio_embeddings e ON e.video_id = v.vendor_track_id AND e.version = :version"""

_TRACK_SEED = f"""
seed AS (
    SELECT t.id, v.vendor_track_id AS video_id, e.embedding
    FROM {_PROFILED}
    WHERE t.id = :track_id
)"""
# The seed's own video goes too: the same recording on a compilation.
_TRACK_EXCLUDE = "t.id <> s.id AND v.vendor_track_id <> s.video_id"
_TRACK_SEED_ROW = """UNION ALL
    SELECT t.id, coalesce(t.publish_date, t.spotify_release_date), 0, TRUE
    FROM seed s JOIN clouder_tracks t ON t.id = s.id"""

_ARTIST_SEED = f"""
mine AS (
    SELECT DISTINCT v.vendor_track_id AS video_id
    FROM {_PROFILED}
    JOIN clouder_track_artists cta ON cta.track_id = t.id AND cta.artist_id = :artist_id
    WHERE t.style_id = :style_id AND NOT {AI_FLAGGED_SQL}
), seed AS (
    SELECT avg(e.embedding) AS embedding
    FROM mine m JOIN audio_embeddings e ON e.video_id = m.video_id AND e.version = :version
)"""
# Its own tracks (any role) are the page's other list; so are their videos' other tracks.
_ARTIST_EXCLUDE = """NOT EXISTS (
        SELECT 1 FROM clouder_track_artists x WHERE x.track_id = t.id AND x.artist_id = :artist_id)
      AND v.vendor_track_id NOT IN (SELECT video_id FROM mine)"""

# ponytail: an exact scan of the style (DnB ~10 k vectors, 2026-11); an HNSW index with the iterative
# scan once a style passes ~100 k. ponytail: one row per video; collapse by ISRC if the same
# recording on two videos starts showing (79 of 44 k ISRCs, 2026-11).
_RANKED = """
WITH {seed},
cand AS (
    SELECT t.id, v.vendor_track_id AS video_id, e.embedding <=> s.embedding AS distance,
           coalesce(t.publish_date, t.spotify_release_date) AS release_date
    FROM seed s
    CROSS JOIN {profiled}
    WHERE s.embedding IS NOT NULL AND t.style_id = :style_id AND {exclude}
      AND NOT {ai}
), near AS (
    SELECT video_id, min(distance) AS distance FROM cand
    GROUP BY video_id ORDER BY 2, 1 LIMIT :limit
), marks AS (
    SELECT track_id, bool_or(keep) AS kept, bool_or(NOT keep) AS put_in_discard
    FROM ({placements}) pl GROUP BY track_id
), chosen AS (
    (SELECT DISTINCT ON (c.video_id) c.id, c.release_date, n.distance, FALSE AS is_seed
     FROM near n JOIN cand c ON c.video_id = n.video_id
     LEFT JOIN marks m ON m.track_id = c.id
     ORDER BY c.video_id, m.track_id IS NULL, c.release_date NULLS LAST, c.id)
    {seed_row}
), page AS (
    SELECT c.id, c.release_date, c.distance, c.is_seed,
           coalesce(m.kept, FALSE) AS kept,
           coalesce(m.put_in_discard AND NOT m.kept, FALSE) AS discarded,
           coalesce(tp.keep, FALSE) AS predicted
    FROM chosen c
    LEFT JOIN marks m ON m.track_id = c.id
    LEFT JOIN track_predictions tp
      ON tp.user_id = :user_id AND tp.style_id = :style_id AND tp.track_id = c.id
)
"""
_EXTRA = """, p.discarded, p.is_seed, p.distance,
       (p.kept OR (NOT p.discarded AND p.predicted)) AS keep_group"""
_ORDER = "p.is_seed DESC, keep_group DESC, p.distance, t.id"


def _ranked(seed: str, exclude: str, seed_row: str = "") -> str:
    return _RANKED.format(
        seed=seed,
        profiled=_PROFILED,
        exclude=exclude,
        ai=AI_FLAGGED_SQL,
        placements=PLACEMENTS_SQL,
        seed_row=seed_row,
    ) + row_select(order=_ORDER, extra=_EXTRA)


def _row(r: Mapping[str, Any]) -> dict[str, Any]:
    return track_row(r) | {"discarded": bool(r["discarded"])}


class SimilarTracksRepository:
    def __init__(self, data_api: DataAPIClient) -> None:
        self._data_api = data_api

    def for_track(self, *, track_id: str, user_id: str, limit: int = LIMIT) -> dict[str, Any]:
        """{seed, profiled, items}: the seed's row (None for an unknown track) and its neighbours."""
        found = self._data_api.execute(
            """
            SELECT t.style_id, EXISTS (
                SELECT 1 FROM vendor_track_map v
                JOIN audio_embeddings e ON e.video_id = v.vendor_track_id AND e.version = :version
                WHERE v.clouder_track_id = t.id AND v.vendor = 'ytmusic') AS profiled
            FROM clouder_tracks t WHERE t.id = :track_id
            """,
            {"track_id": track_id, "version": VERSION},
        )
        if not found:
            return {"seed": None, "profiled": False, "items": []}
        style_id, profiled = found[0]["style_id"], bool(found[0]["profiled"])
        if not (style_id and profiled):
            (seed,) = self._data_api.execute(
                "WITH page AS (SELECT t.id, coalesce(t.publish_date, t.spotify_release_date)"
                " AS release_date FROM clouder_tracks t WHERE t.id = :track_id)"
                + row_select(order="t.id"),
                {"track_id": track_id, "user_id": user_id},
            )
            return {"seed": track_row(seed) | {"discarded": False}, "profiled": False, "items": []}
        rows = self._data_api.execute(
            _ranked(_TRACK_SEED, _TRACK_EXCLUDE, _TRACK_SEED_ROW),
            {
                "track_id": track_id,
                "user_id": user_id,
                "style_id": style_id,
                "version": VERSION,
                "limit": limit,
            },
        )
        seed = next(_row(r) for r in rows if r["is_seed"])
        return {
            "seed": seed,
            "profiled": True,
            "items": [_row(r) for r in rows if not r["is_seed"]],
        }

    def for_artist(
        self, *, artist_id: str, user_id: str, style_id: str | None, limit: int = LIMIT
    ) -> dict[str, Any]:
        """{profiled, style, styles, items}: the artist's styles with profiled non-AI tracks (most
        first), the one used (*style_id*, else the first) and the tracks nearest its centroid."""
        styles = [
            {"id": r["id"], "name": r["name"], "count": int(r["count"])}
            for r in self._data_api.execute(
                f"""
                SELECT t.style_id AS id, st.name, count(DISTINCT v.vendor_track_id) AS count
                FROM {_PROFILED}
                JOIN clouder_track_artists cta ON cta.track_id = t.id AND cta.artist_id = :artist_id
                JOIN clouder_styles st ON st.id = t.style_id
                WHERE NOT {AI_FLAGGED_SQL}
                GROUP BY t.style_id, st.name
                ORDER BY 3 DESC, st.name
                """,
                {"artist_id": artist_id, "version": VERSION},
            )
        ]
        wanted = style_id or (styles[0]["id"] if styles else None)
        style = next((s for s in styles if s["id"] == wanted), None)
        if style is None:
            return {"profiled": False, "style": None, "styles": styles, "items": []}
        rows = self._data_api.execute(
            _ranked(_ARTIST_SEED, _ARTIST_EXCLUDE),
            {
                "artist_id": artist_id,
                "user_id": user_id,
                "style_id": style["id"],
                "version": VERSION,
                "limit": limit,
            },
        )
        return {
            "profiled": True,
            "style": {"id": style["id"], "name": style["name"]},
            "styles": styles,
            "items": [_row(r) for r in rows],
        }


def _build_repository() -> SimilarTracksRepository:
    return SimilarTracksRepository(data_api_client())


def _path_id(event: Mapping[str, Any], param: str) -> str:
    value = ((event.get("pathParameters") or {}).get(param) or "").strip()
    if not value:
        raise ValidationError(f"{param} is required")
    return value


def handle_track_similar(event: Mapping[str, Any]) -> tuple[int, dict]:
    track_id = _path_id(event, "track_id")
    return 200, _build_repository().for_track(track_id=track_id, user_id=caller_id(event))


def handle_artist_similar(event: Mapping[str, Any]) -> tuple[int, dict]:
    artist_id = _path_id(event, "artist_id")
    style_id = ((event.get("queryStringParameters") or {}).get("style_id") or "").strip() or None
    return 200, _build_repository().for_artist(
        artist_id=artist_id, user_id=caller_id(event), style_id=style_id
    )

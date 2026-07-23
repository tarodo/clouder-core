"""Assemble the full playlist export payload (tracks + comments + enrichment).

The Copy-playlist button used to build this JSON client-side from the already
loaded playlist tracks. Once the export grew to carry the enrichment blob stored
for every artist and label, that shape would have cost one `/artists/{id}` or
`/labels/{id}` request per entity — ~100 round-trips for a 50-track playlist — so
assembly moved server-side behind `GET /playlists/{id}/export`.

`tracks` keeps the shape the client used to produce, so existing consumers of the
copied JSON keep working; `artists` and `labels` are new top-level arrays. They
are deduplicated (an artist appearing on ten tracks is described once) — the
payload is large enough without repeating a merged blob per track.
"""

from __future__ import annotations

import json
from typing import Any, Iterable, Mapping

# Imported rather than re-declared on purpose: this is the list of admin-only
# fields that must never reach a user-facing response. Duplicating it here would
# let the two copies drift and silently leak a field.
from ..artist_enrichment.repository import _USER_FACING_FORBIDDEN as _ARTIST_FORBIDDEN
from ..label_enrichment.repository import _USER_FACING_FORBIDDEN as _LABEL_FORBIDDEN


def _decode_merged(raw: Any, forbidden: frozenset[str]) -> dict[str, Any] | None:
    """Decode a `merged` JSONB blob and drop admin-only fields."""
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            return None
    if not isinstance(raw, dict):
        return None
    return {k: v for k, v in raw.items() if k not in forbidden}


def _fetch_info(
    data_api,
    *,
    table: str,
    id_column: str,
    ids: list[str],
    forbidden: frozenset[str],
    prefix: str,
) -> dict[str, dict[str, Any]]:
    if not ids:
        return {}
    # Data API forbids array binds — build the IN-list parametrically.
    placeholders = ", ".join(f":{prefix}{i}" for i in range(len(ids)))
    params: dict[str, Any] = {f"{prefix}{i}": v for i, v in enumerate(ids)}
    rows = data_api.execute(
        f"SELECT {id_column}, merged FROM {table} "  # noqa: S608 - table/column are literals
        f"WHERE {id_column} IN ({placeholders})",
        params,
    )
    out: dict[str, dict[str, Any]] = {}
    for r in rows:
        info = _decode_merged(r.get("merged"), forbidden)
        if info is not None:
            out[r[id_column]] = info
    return out


def fetch_entity_info(
    data_api,
    *,
    artist_ids: list[str],
    label_ids: list[str],
) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    """Bulk-read merged artist/label enrichment, admin-only fields stripped.

    Two statements regardless of playlist size. Entities with no enrichment row
    are simply absent from the returned maps.
    """
    artists = _fetch_info(
        data_api, table="clouder_artist_info", id_column="artist_id",
        ids=artist_ids, forbidden=_ARTIST_FORBIDDEN, prefix="a",
    )
    labels = _fetch_info(
        data_api, table="clouder_label_info", id_column="label_id",
        ids=label_ids, forbidden=_LABEL_FORBIDDEN, prefix="l",
    )
    return artists, labels


def beatport_track_url(track_id: str | None, slug: str | None) -> str | None:
    """Beatport track URL. The slug is not always stored; `_` makes Beatport
    redirect to the canonical URL by id."""
    if not track_id:
        return None
    s = (slug or "").strip() or "_"
    return f"https://www.beatport.com/track/{s}/{track_id}"


def collect_entity_ids(track_rows: Iterable[Any]) -> tuple[list[str], list[str]]:
    """Unique artist and label ids across the playlist, in first-seen order."""
    artist_ids: dict[str, None] = {}
    label_ids: dict[str, None] = {}
    for row in track_rows:
        for a in getattr(row, "artists", ()) or ():
            aid = a.get("id")
            if aid:
                artist_ids.setdefault(aid, None)
        label = getattr(row, "label", None) or {}
        lid = label.get("id")
        if lid:
            label_ids.setdefault(lid, None)
    return list(artist_ids), list(label_ids)


def build_playlist_export(
    *,
    playlist_name: str,
    track_rows: Iterable[Any],
    comments_by_track: Mapping[str, list[dict[str, Any]]],
    artist_info: Mapping[str, dict[str, Any]],
    label_info: Mapping[str, dict[str, Any]],
) -> dict[str, Any]:
    """Build the export payload. Pure — all reads happen before this call."""
    tracks: list[dict[str, Any]] = []
    artist_names: dict[str, str] = {}
    label_names: dict[str, str] = {}

    for row in track_rows:
        row_artists = list(getattr(row, "artists", ()) or ())
        for a in row_artists:
            if a.get("id"):
                artist_names.setdefault(a["id"], a.get("name") or "")
        label = getattr(row, "label", None) or {}
        if label.get("id"):
            label_names.setdefault(label["id"], label.get("name") or "")

        ytmusic = getattr(row, "ytmusic", None) or {}
        spotify_id = getattr(row, "spotify_id", None)
        tracks.append({
            "title": row.title,
            "mix_name": getattr(row, "mix_name", None),
            "artists": [a.get("name") for a in row_artists if a.get("name")],
            "label": label.get("name"),
            "isrc": getattr(row, "isrc", None),
            "beatport_url": beatport_track_url(
                getattr(row, "beatport_track_id", None),
                getattr(row, "beatport_slug", None),
            ),
            "spotify_url": (
                f"https://open.spotify.com/track/{spotify_id}" if spotify_id else None
            ),
            "youtube_music_url": (
                ytmusic.get("url") if ytmusic.get("status") == "matched" else None
            ),
            "comments": list(comments_by_track.get(row.track_id, ())),
        })

    return {
        "playlist": playlist_name,
        "track_count": len(tracks),
        "tracks": tracks,
        "artists": [
            {"id": aid, "name": name, "info": artist_info.get(aid)}
            for aid, name in artist_names.items()
        ],
        "labels": [
            {"id": lid, "name": name, "info": label_info.get(lid)}
            for lid, name in label_names.items()
        ],
    }

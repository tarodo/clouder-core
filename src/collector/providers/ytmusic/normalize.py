"""Pure helpers: build a YT Music search query and convert a raw search
result (song or video) into a VendorTrackRef. No network, no scoring."""

from __future__ import annotations

from typing import Any

from ..base import VendorTrackRef

_TOPIC_SUFFIX = " - Topic"


def build_query(artist: str, title: str) -> str:
    """Whitespace-normalized "artist title" query."""
    return " ".join(f"{artist} {title}".split())


def _strip_topic(name: str) -> str:
    if name.endswith(_TOPIC_SUFFIX):
        return name[: -len(_TOPIC_SUFFIX)].strip()
    return name.strip()


def _artist_names(raw: dict[str, Any]) -> tuple[str, ...]:
    artists = raw.get("artists")
    if not isinstance(artists, list):
        return ()
    names = []
    for a in artists:
        if isinstance(a, dict) and a.get("name"):
            cleaned = _strip_topic(str(a["name"]))
            if cleaned:
                names.append(cleaned)
    return tuple(names)


def result_to_ref(raw: dict[str, Any]) -> VendorTrackRef | None:
    """Convert one YT Music search result to a VendorTrackRef.

    Returns None when the result carries no videoId (not playable).
    Works for both `songs` and `videos` result shapes; `videos` simply
    lack an `album` key, which maps to album_name=None.
    """
    video_id = raw.get("videoId")
    if not isinstance(video_id, str) or not video_id:
        return None

    album = raw.get("album")
    album_name = album.get("name") if isinstance(album, dict) else None

    seconds = raw.get("duration_seconds")
    duration_ms = int(seconds) * 1000 if isinstance(seconds, (int, float)) else None

    return VendorTrackRef(
        vendor="ytmusic",
        vendor_track_id=video_id,
        isrc=None,
        artist_names=_artist_names(raw),
        title=str(raw.get("title") or ""),
        duration_ms=duration_ms,
        album_name=str(album_name) if album_name else None,
        raw_payload=raw,
    )

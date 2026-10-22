"""Resolve an open vendor-match review: shared by the playlist popover and the
admin YouTube review page, so both accept and reject the same way."""

from __future__ import annotations

from typing import Any

from ..comments.dispatch import try_dispatch_comment_collection
from ..providers.ytmusic.normalize import result_to_ref
from . import utc_now


def project_candidate(c: dict) -> dict[str, Any] | None:
    ref = c.get("ref") or {}
    vt = result_to_ref(ref)
    vid = vt.vendor_track_id if vt else str(ref.get("videoId") or "")
    if not vid:
        return None
    return {
        "vendor_track_id": vid,
        "title": vt.title if vt else str(ref.get("title") or ""),
        "artists": list(vt.artist_names) if vt else [],
        "album": vt.album_name if vt else None,
        "duration_ms": vt.duration_ms if vt else None,
        "url": f"https://music.youtube.com/watch?v={vid}",
        "score": c.get("score"),
    }


def resolve_match(
    repo: Any, *, track_id: str, vendor: str, action: str, vendor_track_id: str | None
) -> None:
    """Accept *vendor_track_id* (a stored candidate keeps its full payload; a
    pasted link gets a minimal one) or reject the track as not on the vendor."""
    if action == "accept":
        assert vendor_track_id is not None  # ResolveMatchIn requires it on accept
        review = repo.get_open_review(track_id=track_id, vendor=vendor)
        payload: dict[str, Any] = {
            "videoId": vendor_track_id,
            "url": f"https://music.youtube.com/watch?v={vendor_track_id}",
            "source": "manual_url",
        }
        if review is not None:
            for c in review.candidates:
                ref = c.get("ref") or {}
                if str(ref.get("videoId") or "") == vendor_track_id:
                    payload = ref
                    break
        repo.resolve_review_accept(
            clouder_track_id=track_id,
            vendor=vendor,
            vendor_track_id=vendor_track_id,
            payload=payload,
            now=utc_now(),
        )
        if vendor == "ytmusic":
            # No seed: the accepted song often has comments disabled, and a track
            # already collected (from its ingest-time video) is skipped.
            try_dispatch_comment_collection(track_id=track_id, platform="youtube")
    else:
        repo.resolve_review_reject(clouder_track_id=track_id, vendor=vendor, now=utc_now())

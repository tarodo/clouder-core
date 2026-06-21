"""YouTube Data API v3 comment provider.

Reads public top-level comments via commentThreads.list with a shared
developer key. One request per video (maxResults<=100, single page) = 1
quota unit. The requests session is injected so tests can stub HTTP.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from ..base import CollectedComment

_BASE = "https://www.googleapis.com/youtube/v3/commentThreads"


class CommentsDisabledError(Exception):
    """Raised when the video has comments disabled (HTTP 403 commentsDisabled)."""


def _default_ytmusic_factory() -> Any:
    from ytmusicapi import YTMusic  # lazy: only when a fallback search runs

    return YTMusic()


class YouTubeCommentProvider:
    platform = "youtube"

    def __init__(
        self,
        *,
        api_key: str,
        session: Any,
        ytmusic_client: Any | None = None,
        ytmusic_client_factory: Any = _default_ytmusic_factory,
        search_limit: int = 10,
        threshold: float | None = None,
    ) -> None:
        self._api_key = api_key
        self._session = session
        self._ytmusic_client = ytmusic_client
        self._ytmusic_client_factory = ytmusic_client_factory
        self._search_limit = search_limit
        self._threshold = threshold

    def collect(self, video_ref: str, *, limit: int = 100) -> list[CollectedComment]:
        resp = self._session.get(
            _BASE,
            params={
                "part": "snippet",
                "videoId": video_ref,
                "maxResults": min(int(limit), 100),
                "order": "relevance",
                "textFormat": "plainText",
                "key": self._api_key,
            },
            timeout=20,
        )
        if getattr(resp, "status_code", 0) == 403:
            if _first_error_reason(_safe_json(resp)) == "commentsDisabled":
                raise CommentsDisabledError(video_ref)
            resp.raise_for_status()
        resp.raise_for_status()

        data = resp.json() or {}
        out: list[CollectedComment] = []
        for rank, item in enumerate((data.get("items") or [])[:limit]):
            top = ((item.get("snippet") or {}).get("topLevelComment") or {})
            sn = top.get("snippet") or {}
            out.append(
                CollectedComment(
                    external_id=str(top.get("id") or item.get("id") or ""),
                    author_name=str(sn.get("authorDisplayName") or ""),
                    author_avatar_url=sn.get("authorProfileImageUrl"),
                    text=str(sn.get("textDisplay") or ""),
                    like_count=int(sn.get("likeCount") or 0),
                    published_at=_parse_iso(sn.get("publishedAt")),
                    rank=rank,
                )
            )
        return out

    def _get_ytmusic(self) -> Any:
        if self._ytmusic_client is None:
            self._ytmusic_client = self._ytmusic_client_factory()
        return self._ytmusic_client

    def resolve_alternate_videos(
        self,
        *,
        artist: str,
        title: str,
        duration_ms: int | None,
        exclude_video_id: str,
    ) -> list[str]:
        from ..ytmusic.normalize import build_query, result_to_ref
        from ...vendor_match.scorer import score_candidate
        from ...settings import get_vendor_match_settings

        threshold = (
            self._threshold
            if self._threshold is not None
            else get_vendor_match_settings().fuzzy_match_threshold
        )
        query = build_query(artist, title)
        raw_results = self._get_ytmusic().search(
            query, filter="videos", limit=self._search_limit
        )
        scored: list[tuple[float, str]] = []
        for raw in raw_results or []:
            if not isinstance(raw, dict):
                continue
            ref = result_to_ref(raw)
            if ref is None or ref.vendor_track_id == exclude_video_id:
                continue
            score = score_candidate(
                candidate=ref, artist=artist, title=title,
                duration_ms=duration_ms, album=None,
            )
            if score.total >= threshold:
                scored.append((score.total, ref.vendor_track_id))
        scored.sort(key=lambda t: t[0], reverse=True)
        return [vid for _, vid in scored[:3]]


def _safe_json(resp: Any) -> dict:
    try:
        return resp.json() or {}
    except Exception:  # noqa: BLE001 — defensive on error bodies
        return {}


def _first_error_reason(data: dict) -> str | None:
    errors = ((data.get("error") or {}).get("errors") or [])
    if errors and isinstance(errors[0], dict):
        return errors[0].get("reason")
    return None


def _parse_iso(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        return None

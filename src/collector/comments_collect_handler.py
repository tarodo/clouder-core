"""SQS-driven Lambda that collects comments for one video per record."""

from __future__ import annotations

import requests
from datetime import datetime, timezone
from typing import Any, Mapping

from pydantic import ValidationError as PydanticValidationError

from .comments.messages import CommentCollectMessage
from .comments.registry import CommentPlatformDisabledError, get_comment_provider
from .comments.repository import (
    CommentsRepository,
    TrackMeta,
    create_default_comments_repository,
)
from .logging_utils import log_event
from .providers.base import CollectedComment, CommentProvider
from .providers.youtube.comments import CommentsDisabledError
from .settings import get_comment_collection_worker_settings


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _build_repository() -> CommentsRepository:
    repo = create_default_comments_repository()
    if repo is None:
        raise RuntimeError("Aurora Data API not configured")
    return repo


def _resolve_and_collect(
    provider: CommentProvider, *, primary_video_id: str, meta: TrackMeta | None
) -> tuple[str, list[CollectedComment], str]:
    """Collect from the primary video; on CommentsDisabledError, fall back to up to
    3 resolver-provided regular videos. Returns (status, comments, video_id), where
    video_id is the video actually reached (the collected-from one, or the first
    real alternate even when it had no comments).

    When primary_video_id is empty (decoupled dispatch from triage finalize), the
    primary is resolved first from track metadata via the same YT-Music search used
    for the disabled-comments fallback. If nothing is resolvable, status is
    "disabled" (no commentable video reached).

    Raises are left to the caller (generic/platform errors -> 'failed')."""
    if not primary_video_id:
        if meta is None:
            return ("disabled", [], "")
        resolved = provider.resolve_alternate_videos(
            artist=meta.artist, title=meta.title,
            duration_ms=meta.duration_ms, exclude_video_id="",
        )
        if not resolved:
            return ("disabled", [], "")
        primary_video_id = resolved[0]

    try:
        comments = provider.collect(primary_video_id, limit=100)
        return ("collected" if comments else "empty", comments, primary_video_id)
    except CommentsDisabledError:
        pass

    # Need track metadata to build the fallback search query.
    if meta is None:
        return ("disabled", [], primary_video_id)

    alts = provider.resolve_alternate_videos(
        artist=meta.artist, title=meta.title,
        duration_ms=meta.duration_ms, exclude_video_id=primary_video_id,
    )
    first_empty_alt: str | None = None
    # belt-and-suspenders: the resolver already caps at 3 best-scored ids.
    for alt in (alts or [])[:3]:
        try:
            comments = provider.collect(alt, limit=100)
        except CommentsDisabledError:
            continue
        if comments:
            return ("collected", comments, alt)
        if first_empty_alt is None:
            first_empty_alt = alt
    # A real video was reached but had no comments -> point at it; else disabled.
    if first_empty_alt is not None:
        return ("empty", [], first_empty_alt)
    return ("disabled", [], primary_video_id)


def lambda_handler(event: Mapping[str, Any], context: Any) -> dict[str, Any]:
    del context
    records = event.get("Records") or []
    if not isinstance(records, list):
        return {"processed": 0}

    log_event("INFO", "comments_collect_worker_invoked", sqs_record_count=len(records))

    repo = _build_repository()
    settings = get_comment_collection_worker_settings()
    session = requests.Session()

    processed = 0
    for index, record in enumerate(records):
        if not isinstance(record, Mapping):
            continue
        body = record.get("body")
        if not isinstance(body, str):
            continue
        try:
            msg = CommentCollectMessage.model_validate_json(body)
        except PydanticValidationError as exc:
            log_event(
                "ERROR", "comments_collect_message_invalid",
                sqs_record_index=index, error_message=str(exc)[:500],
            )
            continue

        now = _utc_now()
        try:
            provider = get_comment_provider(
                msg.platform, api_key=settings.youtube_api_key, session=session
            )
            meta = repo.fetch_track_meta([msg.track_id]).get(msg.track_id)
            status, comments, video_id = _resolve_and_collect(
                provider, primary_video_id=msg.video_id, meta=meta
            )
            repo.store_comments(
                collection_id=msg.collection_id, platform=msg.platform,
                comments=comments, status=status, now=now, external_video_id=video_id,
            )
        # Platform not enabled is an ops/config gate (not per-video state); store
        # as "failed" so it is visible in the DB and not silently dropped.
        except CommentPlatformDisabledError as exc:
            repo.store_comments(
                collection_id=msg.collection_id, platform=msg.platform,
                comments=[], status="failed", now=now, error=str(exc)[:500],
            )
        except Exception as exc:  # noqa: BLE001 — never retry: 1-request budget
            repo.store_comments(
                collection_id=msg.collection_id, platform=msg.platform,
                comments=[], status="failed", now=now, error=str(exc)[:500],
            )
        processed += 1
        log_event(
            "INFO", "comments_collect_completed",
            collection_id=msg.collection_id, platform=msg.platform,
        )

    return {"processed": processed}

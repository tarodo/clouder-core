"""Best-effort dispatch of comment-collection jobs from curation/match paths.

Called inline after a track gains a YouTube match. Never raises — collection
must never break the originating request. Mirrors label_enrichment.auto_dispatch.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone

from ..logging_utils import log_event
from .messages import CommentCollectMessage
from .repository import CommentsRepository, create_default_comments_repository


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _build_repository() -> CommentsRepository:
    repo = create_default_comments_repository()
    if repo is None:
        raise RuntimeError("Aurora Data API not configured")
    return repo


def _build_sqs_client():
    import boto3

    return boto3.client("sqs")


def _queue_url() -> str:
    url = os.environ.get("COMMENT_COLLECT_QUEUE_URL", "").strip()
    if not url:
        raise RuntimeError("COMMENT_COLLECT_QUEUE_URL is required")
    return url


def _safe(fn) -> None:
    try:
        fn()
    except Exception as exc:  # noqa: BLE001 — best-effort, never break caller
        log_event("ERROR", "comment_dispatch_error", error_message=str(exc)[:500])


def try_dispatch_comment_collection(
    *, track_id: str, video_id: str, platform: str = "youtube", user_id: str | None = None
) -> None:
    def _run() -> None:
        if not video_id:
            return
        repo = _build_repository()
        collection_id = repo.start_collection(
            track_id=track_id, platform=platform, video_id=video_id, now=_utc_now()
        )
        if collection_id is None:
            log_event(
                "INFO", "comment_dispatch_skipped_collected",
                track_id=track_id, platform=platform,
            )
            return
        msg = CommentCollectMessage(
            track_id=track_id, platform=platform, video_id=video_id, collection_id=collection_id
        )
        _build_sqs_client().send_message(
            QueueUrl=_queue_url(), MessageBody=msg.model_dump_json()
        )
        log_event(
            "INFO", "comment_dispatch_enqueued",
            track_id=track_id, platform=platform, collection_id=collection_id,
        )

    _safe(_run)

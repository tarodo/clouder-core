"""SQS-driven Lambda that collects comments for one video per record."""

from __future__ import annotations

import requests
from datetime import datetime, timezone
from typing import Any, Mapping

from pydantic import ValidationError as PydanticValidationError

from .comments.messages import CommentCollectMessage
from .comments.registry import CommentPlatformDisabledError, get_comment_provider
from .comments.repository import CommentsRepository, create_default_comments_repository
from .logging_utils import log_event
from .providers.youtube.comments import CommentsDisabledError
from .settings import get_comment_collection_worker_settings


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _build_repository() -> CommentsRepository:
    repo = create_default_comments_repository()
    if repo is None:
        raise RuntimeError("Aurora Data API not configured")
    return repo


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
            comments = provider.collect(msg.video_id, limit=100)
            status = "collected" if comments else "empty"
            repo.store_comments(
                collection_id=msg.collection_id, platform=msg.platform,
                comments=comments, status=status, now=now,
            )
        except CommentsDisabledError:
            repo.store_comments(
                collection_id=msg.collection_id, platform=msg.platform,
                comments=[], status="disabled", now=now,
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

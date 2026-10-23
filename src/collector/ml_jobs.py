"""Enqueue work for the ML worker (ml-jobs queue).

The API-side producers (score, retrain) are best-effort: they never fail the caller. The worker's own
page chain (score_style) raises, so the failed record is redriven instead of the chain ending."""

from __future__ import annotations

import json
import os
from typing import Any

from .logging_utils import log_event


def _build_sqs_client():
    import boto3

    return boto3.client("sqs")


def _queue_url() -> str:
    url = os.environ.get("ML_JOBS_QUEUE_URL", "").strip()
    if not url:
        raise RuntimeError("ML_JOBS_QUEUE_URL is required")
    return url


def _send(message: dict[str, Any]) -> None:
    _build_sqs_client().send_message(QueueUrl=_queue_url(), MessageBody=json.dumps(message))


def _try_send(message: dict[str, Any]) -> None:
    try:
        _send(message)
    except Exception as exc:  # best-effort: the next trigger, or the 1 h retrain dedupe, heals it
        log_event(
            "ERROR",
            "ml_jobs_enqueue_error",
            error_message=str(exc)[:500],
        )


def enqueue_score(*, video_ids: list[str]) -> None:
    _try_send({"type": "score", "video_ids": video_ids})


def enqueue_retrain(*, user_id: str, style_id: str) -> None:
    _try_send({"type": "retrain", "user_id": user_id, "style_id": style_id})


def enqueue_score_style(
    *, user_id: str, style_id: str, model_version: int, after_track_id: str | None
) -> None:
    """The worker's chain: raises on a failed send or a missing ML_JOBS_QUEUE_URL."""
    _send(
        {
            "type": "score_style",
            "user_id": user_id,
            "style_id": style_id,
            "model_version": model_version,
            "after_track_id": after_track_id,
        }
    )

"""Enqueue scoring work for the ML worker (ml-jobs queue). Best-effort: never fails the caller."""

from __future__ import annotations

import json
import os

from .logging_utils import log_event


def _build_sqs_client():
    import boto3

    return boto3.client("sqs")


def _queue_url() -> str:
    url = os.environ.get("ML_JOBS_QUEUE_URL", "").strip()
    if not url:
        raise RuntimeError("ML_JOBS_QUEUE_URL is required")
    return url


def enqueue_score(*, video_ids: list[str]) -> None:
    try:
        _build_sqs_client().send_message(
            QueueUrl=_queue_url(),
            MessageBody=json.dumps({"type": "score", "video_ids": video_ids}),
        )
    except Exception as exc:  # best-effort: the profiles are stored already
        log_event(
            "ERROR",
            "ml_jobs_enqueue_error",
            error_message=str(exc)[:500],
        )

"""Enqueue one block-level auto-enrichment dispatch message.

Called from the finalize handler INSTEAD of running the label + artist fan-out
inline. The fan-out (claim, resolve, create-run, per-item enqueue) runs in the
auto-enrich-dispatch worker, so finalize returns in milliseconds regardless of
block size. Best-effort: never break finalize.
"""

from __future__ import annotations

import json
import os

from ..logging_utils import log_event


def _build_sqs_client():
    import boto3
    return boto3.client("sqs")


def _queue_url() -> str:
    url = os.environ.get("AUTO_ENRICH_DISPATCH_QUEUE_URL", "").strip()
    if not url:
        raise RuntimeError("AUTO_ENRICH_DISPATCH_QUEUE_URL is required")
    return url


def enqueue_block_auto_enrich(*, block_id: str, user_id: str | None) -> None:
    try:
        sqs = _build_sqs_client()
        sqs.send_message(
            QueueUrl=_queue_url(),
            MessageBody=json.dumps({"block_id": block_id, "user_id": user_id}),
        )
    except Exception as exc:  # noqa: BLE001 — best-effort, never break finalize
        log_event(
            "ERROR", "auto_enrich_block_enqueue_error",
            block_id=block_id, error_message=str(exc)[:500],
        )

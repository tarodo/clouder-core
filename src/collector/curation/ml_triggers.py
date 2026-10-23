"""Retrain triggers from triage (spec §5): a finalize, or the 150th label since the model trained.

On the request path, best-effort: never raises. A move costs one small query, two when it lands
in a label bucket; the request dedupe (ml_request_retrain) keeps a burst of taps to one message."""

from __future__ import annotations

from .. import ml_jobs
from ..logging_utils import log_event
from ..repositories import utc_now
from . import deps

RETRAIN_AFTER = 150  # STAGING / DISCARD placements since trained_at
LABEL_BUCKETS = ("STAGING", "DISCARD")


def after_labels(
    *, user_id: str, block_id: str, finalized: bool, bucket_id: str | None = None
) -> None:
    """After a finalize of *block_id*, or a move / transfer out of it into *bucket_id*."""
    try:
        repo = deps.create_clouder_repository_from_env()
        if repo is None:
            return
        ctx = repo.ml_trigger_context(user_id=user_id, block_id=block_id, bucket_id=bucket_id)
        if ctx is None:
            return
        style_id = ctx["style_id"]
        if not finalized and (
            ctx["bucket_type"] not in LABEL_BUCKETS
            or repo.ml_labels_since_training(user_id=user_id, style_id=style_id) < RETRAIN_AFTER
        ):
            return
        if repo.ml_request_retrain(user_id=user_id, style_id=style_id, now=utc_now()):
            ml_jobs.enqueue_retrain(user_id=user_id, style_id=style_id)
    except Exception as exc:  # never break the tap: the next label, or the next finalize, retries
        log_event(
            "ERROR",
            "ml_retrain_trigger_error",
            user_id=user_id,
            block_id=block_id,
            bucket_id=bucket_id,
            error_message=str(exc)[:500],
        )

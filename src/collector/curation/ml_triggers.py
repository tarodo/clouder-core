"""Retrain triggers from triage (spec §5): a finalize, or the 150th label since the model trained.

On the request path, best-effort: never raises. A tap that placed tracks anywhere but a STAGING /
DISCARD bucket costs nothing; a label tap costs one count on the route's own Data API client, and
the request dedupe (ml_request_retrain) keeps a burst of taps past 150 to one message."""

from __future__ import annotations

from typing import Any

from .. import ml_jobs
from ..logging_utils import log_event
from ..repositories import ClouderRepository, utc_now

RETRAIN_AFTER = 150  # STAGING / DISCARD placements since trained_at
LABEL_BUCKETS = ("STAGING", "DISCARD")


def after_labels(
    triage_repo: Any,
    *,
    user_id: str,
    style_id: str | None,
    finalized: bool = False,
    bucket_type: str | None = None,
) -> None:
    """After a finalize, or a move / transfer that placed tracks in a *bucket_type* bucket."""
    if not style_id or not (finalized or bucket_type in LABEL_BUCKETS):
        return
    try:
        repo = ClouderRepository(triage_repo._data_api)  # the route's client: no second one per tap
        if not finalized and (
            repo.ml_labels_since_training(user_id=user_id, style_id=style_id) < RETRAIN_AFTER
        ):
            return
        if repo.ml_request_retrain(user_id=user_id, style_id=style_id, now=utc_now()):
            ml_jobs.enqueue_retrain(user_id=user_id, style_id=style_id)
    except Exception as exc:  # never break the tap: the next label, or the next finalize, retries
        log_event(
            "ERROR",
            "ml_retrain_trigger_error",
            user_id=user_id,
            style_id=style_id,
            error_message=str(exc)[:500],
        )

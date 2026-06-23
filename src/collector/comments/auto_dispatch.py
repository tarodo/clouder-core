"""Best-effort fan-out of comment-collection jobs for a finalized triage block.

Runs in the auto-enrich-dispatch worker (off the finalize request path), mirroring
label_enrichment.auto_dispatch.try_dispatch_for_triage_block. For each track the
block promoted into the user's categories, enqueue a comment-collection job with no
seed video — the comment worker resolves the video from track metadata. Best-effort:
never breaks the worker.
"""

from __future__ import annotations

from ..logging_utils import log_event
from .dispatch import try_dispatch_comment_collection
from .repository import CommentsRepository, create_default_comments_repository


def _build_repository() -> CommentsRepository:
    repo = create_default_comments_repository()
    if repo is None:
        raise RuntimeError("Aurora Data API not configured")
    return repo


def _safe(fn) -> None:
    try:
        fn()
    except Exception as exc:  # noqa: BLE001 — best-effort, never break the worker
        log_event(
            "ERROR", "comments_auto_dispatch_error", error_message=str(exc)[:500]
        )


def try_dispatch_comments_for_triage_block(
    *, block_id: str, user_id: str | None
) -> None:
    def _run() -> None:
        if not user_id:
            return
        repo = _build_repository()
        track_ids = repo.promoted_track_ids_for_block(
            block_id=block_id, user_id=user_id
        )
        for track_id in track_ids:
            try_dispatch_comment_collection(track_id=track_id, platform="youtube")

    _safe(_run)

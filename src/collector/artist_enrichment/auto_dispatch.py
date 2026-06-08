"""Best-effort auto-enrichment dispatch for artists from curation actions.

Mirror of label_enrichment.auto_dispatch. Enqueues onto the artist-enrichment
SQS queue; the worker derives disambiguation context, so the message carries
only run_id/artist_id/artist_name (no style). Every public entrypoint swallows
exceptions: auto-search must never break curation.
"""

from __future__ import annotations

import json
import os

from ..data_api import DataAPIClient, create_default_data_api_client
from ..logging_utils import log_event
from ..settings import get_data_api_settings
from .auto_repository import AutoEnrichRepository
from .repository import ArtistEnrichmentRepository, RunSpec

_KIND = "artists"
_SQS_BATCH = 10


def _build_data_api() -> DataAPIClient:
    settings = get_data_api_settings()
    if not settings.is_configured:
        raise RuntimeError("Aurora Data API not configured")
    return create_default_data_api_client(
        resource_arn=str(settings.aurora_cluster_arn),
        secret_arn=str(settings.aurora_secret_arn),
        database=settings.aurora_database,
    )


def _build_auto_repository() -> AutoEnrichRepository:
    return AutoEnrichRepository(data_api=_build_data_api())


def _build_artist_repository() -> ArtistEnrichmentRepository:
    return ArtistEnrichmentRepository(data_api=_build_data_api())


def _build_sqs_client():
    import boto3
    return boto3.client("sqs")


def _queue_url() -> str:
    url = os.environ.get("ARTIST_ENRICHMENT_QUEUE_URL", "").strip()
    if not url:
        raise RuntimeError("ARTIST_ENRICHMENT_QUEUE_URL is required")
    return url


def _dispatch_artists(*, artist_ids: list[str], source_hint: str, user_id: str | None) -> None:
    if not artist_ids:
        return
    log_event(
        "INFO", "auto_enrich_artists_dispatch_started",
        source_hint=source_hint, candidate_artists=len(artist_ids),
    )
    auto_repo = _build_auto_repository()
    cfg = auto_repo.get_config(_KIND)
    if not cfg or not cfg.get("enabled"):
        log_event(
            "INFO", "auto_enrich_artists_skipped_disabled",
            source_hint=source_hint, candidate_artists=len(artist_ids),
        )
        return

    claimed = auto_repo.claim_artists(sorted(set(artist_ids)))
    if not claimed:
        log_event(
            "INFO", "auto_enrich_artists_dispatched",
            claimed=0, skipped=len(set(artist_ids)), run_id=None, source_hint=source_hint,
        )
        return

    ae_repo = _build_artist_repository()
    names = ae_repo.get_artists_by_ids(claimed)
    resolved: list[tuple[str, str]] = [
        (artist_id, names[artist_id]) for artist_id in claimed if artist_id in names
    ]

    if not resolved:
        # Artists vanished between claim and resolve — leave state queued; the
        # stale-queued recovery in claim_artists re-enables them later.
        return

    spec = RunSpec(
        prompt_slug=cfg["prompt_slug"],
        prompt_version=cfg["prompt_version"],
        vendors=list(cfg["vendors"]),
        models=dict(cfg["models"]),
        merge_vendor=cfg["merge_vendor"],
        merge_model=cfg["merge_model"],
        requested_artists=len(resolved),
        created_by_user_id=user_id,
        source="auto",
    )
    run_id = ae_repo.create_run(spec)
    auto_repo.attach_run(claimed, run_id)

    sqs = _build_sqs_client()
    queue_url = _queue_url()
    entries = [
        {
            "Id": str(idx),
            "MessageBody": json.dumps(
                {"run_id": run_id, "artist_id": artist_id, "artist_name": name}
            ),
        }
        for idx, (artist_id, name) in enumerate(resolved)
    ]
    failed = 0
    for start in range(0, len(entries), _SQS_BATCH):
        batch = entries[start : start + _SQS_BATCH]
        resp = sqs.send_message_batch(QueueUrl=queue_url, Entries=batch)
        failed += len(resp.get("Failed", []))
    if failed:
        log_event(
            "ERROR", "auto_enrich_artists_enqueue_partial_failure",
            run_id=run_id, error_message=f"{failed} of {len(entries)} sqs entries failed",
        )

    log_event(
        "INFO", "auto_enrich_artists_dispatched",
        claimed=len(resolved), skipped=len(set(artist_ids)) - len(claimed),
        run_id=run_id, source_hint=source_hint,
    )


def _safe(fn) -> None:
    try:
        fn()
    except Exception as exc:  # noqa: BLE001 — best-effort, never break curation
        log_event("ERROR", "auto_enrich_artists_dispatch_error", error_message=str(exc)[:500])


def try_dispatch_artists_for_track(*, track_id: str, user_id: str | None) -> None:
    def _run() -> None:
        auto_repo = _build_auto_repository()
        artist_ids = auto_repo.artist_ids_for_track(track_id)
        if not artist_ids:
            return
        _dispatch_artists(artist_ids=artist_ids, source_hint="single", user_id=user_id)
    _safe(_run)


def try_dispatch_artists_for_triage_block(*, block_id: str, user_id: str | None) -> None:
    def _run() -> None:
        auto_repo = _build_auto_repository()
        artist_ids = auto_repo.artist_ids_for_triage_block(block_id)
        if not artist_ids:
            return
        _dispatch_artists(artist_ids=artist_ids, source_hint="triage", user_id=user_id)
    _safe(_run)

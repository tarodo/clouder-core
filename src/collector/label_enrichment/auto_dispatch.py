"""Best-effort auto-enrichment dispatch from curation actions.

The single-track entrypoint runs inline from the curation handler after its DB
write commits; the triage-block entrypoint runs in the auto-enrich-dispatch
worker (off the finalize request path). Either way this only enqueues work onto
the existing label-enrichment SQS queue — the enricher worker runs the searches
in the background, so curation never waits for results. Every public entrypoint
swallows exceptions: auto-search must never break curation.
"""

from __future__ import annotations

import json
import os

from ..data_api import DataAPIClient, create_default_data_api_client
from ..logging_utils import log_event
from ..settings import get_data_api_settings
from .auto_repository import AutoEnrichRepository
from .repository import LabelEnrichmentRepository, RunSpec

_KIND = "labels"
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


def _build_label_repository() -> LabelEnrichmentRepository:
    return LabelEnrichmentRepository(data_api=_build_data_api())


def _build_sqs_client():
    import boto3
    return boto3.client("sqs")


def _queue_url() -> str:
    url = os.environ.get("LABEL_ENRICHMENT_QUEUE_URL", "").strip()
    if not url:
        raise RuntimeError("LABEL_ENRICHMENT_QUEUE_URL is required")
    return url


def _dispatch_labels(*, label_ids: list[str], source_hint: str, user_id: str | None) -> None:
    if not label_ids:
        return
    log_event(
        "INFO", "auto_enrich_dispatch_started",
        source_hint=source_hint, candidate_labels=len(label_ids),
    )
    auto_repo = _build_auto_repository()
    cfg = auto_repo.get_config(_KIND)
    if not cfg or not cfg.get("enabled"):
        log_event(
            "INFO", "auto_enrich_skipped_disabled",
            source_hint=source_hint, candidate_labels=len(label_ids),
        )
        return

    claimed = auto_repo.claim_labels(sorted(set(label_ids)))
    if not claimed:
        log_event(
            "INFO", "auto_enrich_dispatched",
            claimed=0, skipped=len(set(label_ids)), run_id=None, source_hint=source_hint,
        )
        return

    le_repo = _build_label_repository()
    names = le_repo.get_labels_by_ids(claimed)
    styles = le_repo.derive_styles_for_labels(claimed)
    resolved: list[tuple[str, str, str]] = [
        (label_id, names[label_id], styles.get(label_id) or "music")
        for label_id in claimed
        if label_id in names
    ]

    if not resolved:
        # Labels vanished between claim and resolve — leave state queued; the
        # stale-queued recovery in claim_labels re-enables them later.
        return

    spec = RunSpec(
        prompt_slug=cfg["prompt_slug"],
        prompt_version=cfg["prompt_version"],
        vendors=list(cfg["vendors"]),
        models=dict(cfg["models"]),
        merge_vendor=cfg["merge_vendor"],
        merge_model=cfg["merge_model"],
        requested_labels=len(resolved),
        created_by_user_id=user_id,
        source="auto",
    )
    run_id = le_repo.create_run(spec)
    auto_repo.attach_run(claimed, run_id)

    sqs = _build_sqs_client()
    queue_url = _queue_url()
    entries = [
        {
            "Id": str(idx),
            "MessageBody": json.dumps(
                {"run_id": run_id, "label_id": label_id, "label_name": name, "style": style}
            ),
        }
        for idx, (label_id, name, style) in enumerate(resolved)
    ]
    failed = 0
    for start in range(0, len(entries), _SQS_BATCH):
        batch = entries[start : start + _SQS_BATCH]
        resp = sqs.send_message_batch(QueueUrl=queue_url, Entries=batch)
        failed += len(resp.get("Failed", []))
    if failed:
        log_event(
            "ERROR", "auto_enrich_enqueue_partial_failure",
            run_id=run_id, error_message=f"{failed} of {len(entries)} sqs entries failed",
        )

    log_event(
        "INFO", "auto_enrich_dispatched",
        claimed=len(resolved), skipped=len(set(label_ids)) - len(claimed),
        run_id=run_id, source_hint=source_hint,
    )


def _safe(fn) -> None:
    try:
        fn()
    except Exception as exc:  # noqa: BLE001 — best-effort, never break curation
        log_event("ERROR", "auto_enrich_dispatch_error", error_message=str(exc)[:500])


def try_dispatch_for_track(*, track_id: str, user_id: str | None) -> None:
    def _run() -> None:
        auto_repo = _build_auto_repository()
        label_id = auto_repo.label_id_for_track(track_id)
        if not label_id:
            return
        _dispatch_labels(label_ids=[label_id], source_hint="single", user_id=user_id)
    _safe(_run)


def try_dispatch_for_triage_block(*, block_id: str, user_id: str | None) -> None:
    def _run() -> None:
        auto_repo = _build_auto_repository()
        label_ids = auto_repo.label_ids_for_triage_block(block_id)
        if not label_ids:
            return
        _dispatch_labels(label_ids=label_ids, source_hint="triage", user_id=user_id)
    _safe(_run)

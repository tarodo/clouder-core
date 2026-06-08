"""Best-effort auto-enrichment dispatch from curation actions.

Called inline from the curation handlers AFTER their DB writes commit. Only
enqueues work onto the existing label-enrichment SQS queue — the worker runs
the searches in the background, so curation never waits for results. Every
public entrypoint swallows exceptions: auto-search must never break curation.
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
    resolved: list[tuple[str, str, str]] = []
    for label_id in claimed:
        row = le_repo.get_label_by_id(label_id)
        if row is None:
            continue
        style = le_repo.derive_style_for_label(label_id) or "music"
        resolved.append((label_id, row["name"], style))

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
    for label_id, name, style in resolved:
        sqs.send_message(
            QueueUrl=queue_url,
            MessageBody=json.dumps({
                "run_id": run_id,
                "label_id": label_id,
                "label_name": name,
                "style": style,
            }),
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

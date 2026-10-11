"""Triage routes (spec-D): blocks, buckets, move/transfer, finalize."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

# Imported for the tests: finalize no longer dispatches inline (it moved to
# the dispatch worker, see enqueue_block_auto_enrich). The finalize tests
# patch these and assert-not-called as a regression guard against re-inlining.
from ..artist_enrichment.auto_dispatch import (
    try_dispatch_artists_for_triage_block,  # noqa: F401
)
from ..label_enrichment.auto_dispatch import (
    try_dispatch_for_triage_block,  # noqa: F401
)
from ..logging_utils import log_event
from . import (
    NotFoundError,
    ValidationError,
    deps,
)
from .auto_enrich_dispatch import enqueue_block_auto_enrich
from .http import _error, _json_response, _parse_body, _parse_pagination
from .schemas import (
    CreateTriageBlockIn,
    MoveTracksIn,
    TransferTracksIn,
)
from .triage_repository import (
    TriageRepository,
)


def _serialize_triage_block(row, correlation_id: str) -> dict[str, Any]:
    return {
        "id": row.id,
        "style_id": row.style_id,
        "style_name": row.style_name,
        "name": row.name,
        "date_from": row.date_from,
        "date_to": row.date_to,
        "status": row.status,
        "old_offset_weeks": row.old_offset_weeks,
        "include_disliked_labels": row.include_disliked_labels,
        "include_disliked_artists": row.include_disliked_artists,
        "compilations_to_not": row.compilations_to_not,
        "include_favorites": row.include_favorites,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
        "finalized_at": row.finalized_at,
        "buckets": [
            {
                "id": b.id,
                "bucket_type": b.bucket_type,
                "category_id": b.category_id,
                "category_name": b.category_name,
                "inactive": b.inactive,
                "track_count": b.track_count,
            }
            for b in row.buckets
        ],
        "correlation_id": correlation_id,
    }


def _create_triage_block(event, triage_repo: TriageRepository, user_id: str, correlation_id: str):
    schema = CreateTriageBlockIn.model_validate(_parse_body(event))
    out = triage_repo.create_block(
        user_id=user_id,
        style_id=schema.style_id,
        name=schema.name,
        date_from=schema.date_from,
        date_to=schema.date_to,
        old_offset_weeks=schema.old_offset_weeks,
        include_disliked_labels=schema.include_disliked_labels,
        include_disliked_artists=schema.include_disliked_artists,
        compilations_to_not=schema.compilations_to_not,
        include_favorites=schema.include_favorites,
    )
    log_event(
        "INFO",
        "triage_block_created",
        correlation_id=correlation_id,
        user_id=user_id,
        block_id=out.id,
        style_id=out.style_id,
        date_from=out.date_from,
        date_to=out.date_to,
    )
    return _json_response(201, _serialize_triage_block(out, correlation_id), correlation_id)


def _serialize_block_summary(row) -> dict[str, Any]:
    return {
        "id": row.id,
        "style_id": row.style_id,
        "style_name": row.style_name,
        "name": row.name,
        "date_from": row.date_from,
        "date_to": row.date_to,
        "status": row.status,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
        "finalized_at": row.finalized_at,
        "track_count": row.track_count,
    }


def _serialize_bucket_track(row) -> dict[str, Any]:
    return {
        "track_id": row.track_id,
        "title": row.title,
        "mix_name": row.mix_name,
        "isrc": row.isrc,
        "bpm": row.bpm,
        "length_ms": row.length_ms,
        "key_name": row.key_name,
        "key_camelot": row.key_camelot,
        "publish_date": row.publish_date,
        "spotify_release_date": row.spotify_release_date,
        "spotify_id": row.spotify_id,
        "release_type": row.release_type,
        "is_ai_suspected": row.is_ai_suspected,
        "artists": row.artists,
        "label_name": row.label_name,
        "label_id": row.label_id,
        "added_at": row.added_at,
    }


def _parse_status_query(event: Mapping[str, Any]) -> str | None:
    qp = event.get("queryStringParameters") or {}
    status = qp.get("status")
    if status is None:
        return None
    if status not in ("IN_PROGRESS", "FINALIZED"):
        raise ValidationError("status must be IN_PROGRESS or FINALIZED")
    return status


def _list_triage_blocks_by_style(event, repo: TriageRepository, user_id: str, correlation_id: str):
    style_id = (event.get("pathParameters") or {}).get("style_id")
    if not style_id:
        raise ValidationError("style_id is required in path")
    limit, offset = _parse_pagination(event)
    status = _parse_status_query(event)

    items, total = repo.list_blocks_by_style(
        user_id=user_id,
        style_id=style_id,
        limit=limit,
        offset=offset,
        status=status,
    )
    log_event(
        "INFO",
        "triage_block_listed",
        correlation_id=correlation_id,
        user_id=user_id,
        style_id=style_id,
        count=len(items),
        total=total,
    )
    return _json_response(
        200,
        {
            "items": [_serialize_block_summary(r) for r in items],
            "total": total,
            "limit": limit,
            "offset": offset,
            "correlation_id": correlation_id,
        },
        correlation_id,
    )


def _list_triage_blocks_all(event, repo: TriageRepository, user_id: str, correlation_id: str):
    limit, offset = _parse_pagination(event)
    status = _parse_status_query(event)

    items, total = repo.list_blocks_all(
        user_id=user_id,
        limit=limit,
        offset=offset,
        status=status,
    )
    return _json_response(
        200,
        {
            "items": [_serialize_block_summary(r) for r in items],
            "total": total,
            "limit": limit,
            "offset": offset,
            "correlation_id": correlation_id,
        },
        correlation_id,
    )


def _get_triage_block(event, repo: TriageRepository, user_id: str, correlation_id: str):
    block_id = (event.get("pathParameters") or {}).get("id")
    if not block_id:
        raise ValidationError("id is required in path")
    out = repo.get_block(user_id=user_id, block_id=block_id)
    if out is None:
        raise NotFoundError(
            "triage_block_not_found",
            f"triage block not found: {block_id}",
        )
    return _json_response(200, _serialize_triage_block(out, correlation_id), correlation_id)


def _list_bucket_tracks(event, repo: TriageRepository, user_id: str, correlation_id: str):
    pp = event.get("pathParameters") or {}
    block_id = pp.get("id")
    bucket_id = pp.get("bucket_id")
    if not block_id or not bucket_id:
        raise ValidationError("id and bucket_id are required in path")
    limit, offset = _parse_pagination(event)
    qp = event.get("queryStringParameters") or {}
    search = qp.get("search")

    items, total = repo.list_bucket_tracks(
        user_id=user_id,
        block_id=block_id,
        bucket_id=bucket_id,
        limit=limit,
        offset=offset,
        search=search,
    )
    return _json_response(
        200,
        {
            "items": [_serialize_bucket_track(r) for r in items],
            "total": total,
            "limit": limit,
            "offset": offset,
            "correlation_id": correlation_id,
        },
        correlation_id,
    )


def _move_tracks(event, repo: TriageRepository, user_id: str, correlation_id: str):
    block_id = (event.get("pathParameters") or {}).get("id")
    if not block_id:
        raise ValidationError("id is required in path")
    schema = MoveTracksIn.model_validate(_parse_body(event))

    out = repo.move_tracks(
        user_id=user_id,
        block_id=block_id,
        from_bucket_id=schema.from_bucket_id,
        to_bucket_id=schema.to_bucket_id,
        track_ids=schema.track_ids,
    )
    log_event(
        "INFO",
        "triage_tracks_moved",
        correlation_id=correlation_id,
        user_id=user_id,
        block_id=block_id,
        from_bucket_id=schema.from_bucket_id,
        to_bucket_id=schema.to_bucket_id,
        moved=out.moved,
    )
    return _json_response(
        200,
        {"moved": out.moved, "correlation_id": correlation_id},
        correlation_id,
    )


def _transfer_tracks(event, repo: TriageRepository, user_id: str, correlation_id: str):
    src_block_id = (event.get("pathParameters") or {}).get("src_id")
    if not src_block_id:
        raise ValidationError("src_id is required in path")
    schema = TransferTracksIn.model_validate(_parse_body(event))

    out = repo.transfer_tracks(
        user_id=user_id,
        src_block_id=src_block_id,
        target_bucket_id=schema.target_bucket_id,
        track_ids=schema.track_ids,
    )
    log_event(
        "INFO",
        "triage_tracks_transferred",
        correlation_id=correlation_id,
        user_id=user_id,
        src_block_id=src_block_id,
        target_bucket_id=schema.target_bucket_id,
        transferred=out.transferred,
    )
    return _json_response(
        200,
        {"transferred": out.transferred, "correlation_id": correlation_id},
        correlation_id,
    )


def _finalize_triage_block(event, repo: TriageRepository, user_id: str, correlation_id: str):
    block_id = (event.get("pathParameters") or {}).get("id")
    if not block_id:
        raise ValidationError("id is required in path")

    cat_repo = deps.create_default_categories_repository()
    if cat_repo is None:
        # Triage factory already gated on db config, so this is a defensive
        # mismatch guard — both factories read the same Aurora env vars.
        return _error(503, "db_not_configured", "Database not configured", correlation_id)

    out = repo.finalize_block(
        user_id=user_id,
        block_id=block_id,
        categories_repository=cat_repo,
    )
    log_event(
        "INFO",
        "triage_block_finalized",
        correlation_id=correlation_id,
        user_id=user_id,
        block_id=block_id,
        promoted_count=sum(out.promoted.values()),
    )
    enqueue_block_auto_enrich(block_id=block_id, user_id=user_id)
    return _json_response(
        200,
        {
            "block": _serialize_triage_block(out.block, correlation_id),
            "promoted": out.promoted,
            "correlation_id": correlation_id,
        },
        correlation_id,
    )


def _soft_delete_triage_block(event, repo: TriageRepository, user_id: str, correlation_id: str):
    block_id = (event.get("pathParameters") or {}).get("id")
    if not block_id:
        raise ValidationError("id is required in path")
    deleted = repo.soft_delete_block(user_id=user_id, block_id=block_id)
    if not deleted:
        raise NotFoundError(
            "triage_block_not_found",
            f"triage block not found: {block_id}",
        )
    log_event(
        "INFO",
        "triage_block_soft_deleted",
        correlation_id=correlation_id,
        user_id=user_id,
        block_id=block_id,
    )
    return {
        "statusCode": 204,
        "headers": {"x-correlation-id": correlation_id},
        "body": "",
    }

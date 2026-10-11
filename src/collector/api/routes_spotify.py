"""Spotify search admin: tracks not found, search status, retry."""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import timedelta
from typing import Any

from ..errors import ValidationError
from ..logging_utils import log_event
from . import deps
from .http import (
    _json_response,
    _load_api_settings,
    _parse_date_param,
    _parse_iso_date_field,
    _parse_json_body,
    _parse_pagination_params,
)


def _handle_spotify_not_found(
    event: Mapping[str, Any], context: Any, correlation_id: str
) -> dict[str, Any]:
    repository = deps.create_clouder_repository_from_env()
    if repository is None:
        return _json_response(
            503,
            {
                "error_code": "db_not_configured",
                "message": "Database is not configured",
            },
            correlation_id,
        )

    try:
        limit, offset, search = _parse_pagination_params(event)
        publish_date_from = _parse_date_param(event, "publish_date_from")
        publish_date_to = _parse_date_param(event, "publish_date_to")
        if (
            publish_date_from is not None
            and publish_date_to is not None
            and publish_date_from > publish_date_to
        ):
            raise ValidationError("publish_date_from must be <= publish_date_to")
    except ValidationError as exc:
        return _json_response(
            400,
            {"error_code": "validation_error", "message": exc.message},
            correlation_id,
        )

    rows = repository.find_tracks_not_found_on_spotify(
        limit,
        offset,
        search,
        publish_date_from=publish_date_from,
        publish_date_to=publish_date_to,
    )
    total = repository.count_tracks_not_found_on_spotify(
        search,
        publish_date_from=publish_date_from,
        publish_date_to=publish_date_to,
    )

    items = []
    for row in rows:
        item: dict[str, Any] = {}
        for key, value in row.items():
            item[key] = value
        if "id" in item:
            item["track_id"] = item.pop("id")
        if "artist_names" in item:
            raw = item.pop("artist_names")
            item["artists"] = [n.strip() for n in raw.split(",")] if raw else []
        items.append(item)

    log_event(
        "INFO",
        "spotify_not_found_list_completed",
        correlation_id=correlation_id,
        result_count=len(items),
        total_count=total,
        limit=limit,
        offset=offset,
    )

    return _json_response(
        200,
        {
            "items": items,
            "total": total,
            "limit": limit,
            "offset": offset,
            "correlation_id": correlation_id,
        },
        correlation_id,
    )


def _handle_spotify_search_status(
    event: Mapping[str, Any], context: Any, correlation_id: str
) -> dict[str, Any]:
    """Admin view of the Spotify search: the queue (SQS) and the backlog (Aurora)."""
    repository = deps.create_clouder_repository_from_env()
    if repository is None:
        return _json_response(
            503,
            {"error_code": "db_not_configured", "message": "Database is not configured"},
            correlation_id,
        )
    now = deps.utc_now()
    counts = repository.spotify_search_counts(since=now - timedelta(minutes=10))
    blocked_until = repository.get_vendor_blocked_until("spotify")
    paused_until = blocked_until if blocked_until is not None and blocked_until > now else None

    queue = {"waiting_messages": 0, "in_flight": 0, "delayed": 0}
    queue_url = _load_api_settings().spotify_search_queue_url.strip()
    if queue_url:
        attrs = deps.create_default_sqs_client().get_queue_attributes(
            QueueUrl=queue_url,
            AttributeNames=[
                "ApproximateNumberOfMessages",
                "ApproximateNumberOfMessagesNotVisible",
                "ApproximateNumberOfMessagesDelayed",
            ],
        )["Attributes"]
        queue = {
            "waiting_messages": int(attrs.get("ApproximateNumberOfMessages", 0)),
            "in_flight": int(attrs.get("ApproximateNumberOfMessagesNotVisible", 0)),
            "delayed": int(attrs.get("ApproximateNumberOfMessagesDelayed", 0)),
        }

    if paused_until is not None:
        status = "paused"
    elif queue["in_flight"]:
        status = "running"
    elif queue["waiting_messages"] or queue["delayed"]:
        status = "queued"
    else:
        status = "idle"
    return _json_response(
        200,
        {
            "status": status,
            "paused_until": paused_until.isoformat() if paused_until else None,
            "queue": queue,
            "tracks": {
                "waiting": counts["waiting"],
                "not_found": counts["not_found"],
                "searched_last_10_min": counts["searched_recently"],
            },
        },
        correlation_id,
    )


def _handle_spotify_retry_not_found(
    event: Mapping[str, Any], context: Any, correlation_id: str
) -> dict[str, Any]:
    payload = _parse_json_body(event)

    publish_date_from = _parse_iso_date_field(payload, "publish_date_from")
    publish_date_to = _parse_iso_date_field(payload, "publish_date_to")
    if publish_date_from > publish_date_to:
        raise ValidationError("publish_date_from must be <= publish_date_to")

    repository = deps.create_clouder_repository_from_env()
    if repository is None:
        return _json_response(
            503,
            {
                "error_code": "db_not_configured",
                "message": "Database is not configured",
            },
            correlation_id,
        )

    settings = _load_api_settings()
    queue_url = settings.spotify_search_queue_url.strip()
    if not queue_url:
        log_event(
            "ERROR",
            "spotify_retry_enqueue_failed",
            correlation_id=correlation_id,
            error_code="queue_not_configured",
        )
        return _json_response(
            500,
            {
                "error_code": "enqueue_failed",
                "message": "SPOTIFY_SEARCH_QUEUE_URL is not configured",
            },
            correlation_id,
        )

    now = deps.utc_now()
    reset_count = repository.reset_spotify_not_found(publish_date_from, publish_date_to, now)
    pending_count = repository.count_spotify_pending_in_range(publish_date_from, publish_date_to)

    log_event(
        "INFO",
        "spotify_retry_requested",
        correlation_id=correlation_id,
        reset_count=reset_count,
        pending_count=pending_count,
    )

    if reset_count > 0 or pending_count > 0:
        message = {"batch_size": 200, "auto_continue": True}
        try:
            client = deps.create_default_sqs_client()
            client.send_message(
                QueueUrl=queue_url,
                MessageBody=json.dumps(message, ensure_ascii=False, separators=(",", ":")),
                MessageAttributes={
                    "correlation_id": {
                        "DataType": "String",
                        "StringValue": correlation_id,
                    }
                },
            )
            log_event(
                "INFO",
                "spotify_retry_enqueued",
                correlation_id=correlation_id,
                reset_count=reset_count,
            )
        except Exception as exc:
            log_event(
                "ERROR",
                "spotify_retry_enqueue_failed",
                correlation_id=correlation_id,
                error_type=exc.__class__.__name__,
                error_message=str(exc)[:500],
            )
            return _json_response(
                500,
                {
                    "error_code": "enqueue_failed",
                    "message": (
                        "Tracks were reset but the search message could not "
                        "be enqueued; retry the request"
                    ),
                },
                correlation_id,
            )

    return _json_response(
        200,
        {"queued_count": reset_count, "correlation_id": correlation_id},
        correlation_id,
    )

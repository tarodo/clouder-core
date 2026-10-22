"""Admin view of the YouTube search: queue (SQS), backlog and outcomes (Aurora)."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import timedelta
from typing import Any

from . import deps
from .http import _json_response, _load_api_settings


def _handle_youtube_search_status(
    event: Mapping[str, Any], context: Any, correlation_id: str
) -> dict[str, Any]:
    repository = deps.create_clouder_repository_from_env()
    if repository is None:
        return _json_response(
            503,
            {"error_code": "db_not_configured", "message": "Database is not configured"},
            correlation_id,
        )
    settings = _load_api_settings()
    now = deps.utc_now()
    counts = repository.youtube_search_counts(recent_since=now - timedelta(minutes=10))
    blocked_until = repository.get_vendor_blocked_until("ytmusic")
    paused_until = blocked_until if blocked_until is not None and blocked_until > now else None

    queue = {"waiting_messages": 0, "in_flight": 0, "delayed": 0}
    queue_url = settings.youtube_search_queue_url.strip()
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
                "searched_last_10_min": counts["searched_recently"],
                "searched_total": counts["searched_total"],
            },
            "results": {
                "matched": counts["matched"],
                "needs_review": counts["needs_review"],
                "not_found": counts["not_found"],
                "videos": counts["videos"],
            },
        },
        correlation_id,
    )

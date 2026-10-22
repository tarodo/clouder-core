"""Admin YouTube search: queue (SQS), backlog and outcomes (Aurora), and the
review of one Coverage cell's open YT Music matches."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import timedelta
from typing import Any

from pydantic import ValidationError as PydanticValidationError

from ..curation.match_review import project_candidate, resolve_match
from ..curation.playlists_repository import create_default_playlists_repository
from ..curation.schemas import ResolveMatchIn
from ..errors import ValidationError
from ..logging_utils import log_event
from ..saturday_week import saturday_week_range, weeks_in_year
from ..schemas import validation_error_message
from . import deps
from .http import _json_response, _load_api_settings, _parse_json_body


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


def _int_param(qs: Mapping[str, Any], name: str) -> int:
    raw = qs.get(name)
    if not isinstance(raw, str) or not raw.isdigit():
        raise ValidationError(f"{name} is required (a whole number)")
    return int(raw)


def _handle_youtube_review_list(
    event: Mapping[str, Any], context: Any, correlation_id: str
) -> dict[str, Any]:
    """Open YT Music reviews of one Coverage cell (style, Saturday-week)."""
    qs = event.get("queryStringParameters") or {}
    style_id = _int_param(qs, "style_id")
    week_year = _int_param(qs, "week_year")
    week_number = _int_param(qs, "week_number")
    if not 2000 <= week_year <= 2100 or not 1 <= week_number <= weeks_in_year(week_year):
        raise ValidationError("week_year / week_number out of range")
    repository = deps.create_clouder_repository_from_env()
    if repository is None:
        return _json_response(
            503,
            {"error_code": "db_not_configured", "message": "Database is not configured"},
            correlation_id,
        )
    date_from, date_to = saturday_week_range(week_year, week_number)
    rows = repository.youtube_review_tracks(
        beatport_style_id=str(style_id), date_from=date_from, date_to=date_to
    )
    tracks = [
        {
            "track_id": row["track_id"],
            "title": row["title"],
            "mix_name": row.get("mix_name"),
            "artists": row.get("artists") or "",
            "length_ms": row.get("length_ms"),
            "spotify_url": (
                f"https://open.spotify.com/track/{row['spotify_id']}"
                if row.get("spotify_id")
                else None
            ),
            "candidates": [p for c in row["candidates"] if (p := project_candidate(c)) is not None],
        }
        for row in rows
    ]
    return _json_response(
        200,
        {
            "style_name": rows[0]["style_name"] if rows else None,
            "week_year": week_year,
            "week_number": week_number,
            "tracks": tracks,
        },
        correlation_id,
    )


def _handle_youtube_review_resolve(
    event: Mapping[str, Any], context: Any, correlation_id: str
) -> dict[str, Any]:
    """Accept one candidate (or a pasted id) or mark the track as not on YT Music."""
    track_id = (event.get("pathParameters") or {}).get("track_id")
    if not track_id:
        raise ValidationError("track_id is required in path")
    try:
        body = ResolveMatchIn.model_validate({**_parse_json_body(event), "vendor": "ytmusic"})
    except PydanticValidationError as exc:
        raise ValidationError(validation_error_message(exc)) from exc
    repo = create_default_playlists_repository()
    if repo is None:
        return _json_response(
            503,
            {"error_code": "db_not_configured", "message": "Database is not configured"},
            correlation_id,
        )
    resolve_match(
        repo,
        track_id=track_id,
        vendor=body.vendor,
        action=body.action,
        vendor_track_id=body.vendor_track_id,
    )
    log_event(
        "INFO",
        "match_review_resolved",
        correlation_id=correlation_id,
        track_id=track_id,
        vendor=body.vendor,
        action=body.action,
    )
    return _json_response(200, {"track_id": track_id, "action": body.action}, correlation_id)

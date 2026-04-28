"""Structured logging helpers with sensitive data redaction."""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, Mapping

import structlog

from .settings import get_logging_settings

SENSITIVE_KEYS = {"bp_token", "authorization", "token", "access_token"}
ALLOWED_LOG_FIELDS = {
    "correlation_id",
    "api_request_id",
    "lambda_request_id",
    "run_id",
    "style_id",
    "iso_year",
    "iso_week",
    "item_count",
    "duration_ms",
    "api_pages_fetched",
    "status_code",
    "error_code",
    "error_type",
    "error_message",
    "beatport_url_hash",
    "beatport_page",
    "beatport_attempt",
    "beatport_http_status",
    "s3_bucket",
    "s3_key",
    "s3_size_bytes",
    "sqs_record_count",
    "phase",
    "completed_phases",
    "failed_after",
    "entity_type",
    "relations_total",
    "tracks_total",
    "tracks_processed",
    "artists_total",
    "labels_total",
    "albums_total",
    "chunk_index",
    "chunk_count",
    "chunk_size",
    "processed",
    "run_status",
    "processing_status",
    "processing_outcome",
    "processing_reason",
    "sqs_record_index",
    "limit",
    "offset",
    "search",
    "total_count",
    "result_count",
    "entity",
    "attempt",
    "sleep_seconds",
    "track_id",
    "user_id",
    "category_id",
    "blocks_snapshot_into",
    "inactivated_buckets",
    "block_id",
    "date_from",
    "date_to",
    "vendor",
    "match_type",
    "confidence",
    "candidate_count",
    "title_sim",
    "artist_sim",
    "reason",
}


LOG_LEVEL = getattr(logging, get_logging_settings().log_level.upper(), logging.INFO)

structlog.configure(
    processors=[
        structlog.processors.TimeStamper(fmt="iso", utc=True, key="timestamp"),
        lambda logger, method_name, event_dict: _sanitize_event(event_dict),
        structlog.processors.EventRenamer("message"),
        structlog.processors.JSONRenderer(serializer=json.dumps, ensure_ascii=True),
    ],
    wrapper_class=structlog.make_filtering_bound_logger(LOG_LEVEL),
    logger_factory=structlog.PrintLoggerFactory(),
    cache_logger_on_first_use=True,
)

LOGGER = structlog.get_logger("collector")


def redact_sensitive_data(value: Any) -> Any:
    if isinstance(value, Mapping):
        result: Dict[str, Any] = {}
        for key, item in value.items():
            if key.lower() in SENSITIVE_KEYS:
                result[key] = "[REDACTED]"
            else:
                result[key] = redact_sensitive_data(item)
        return result

    if isinstance(value, list):
        return [redact_sensitive_data(item) for item in value]

    return value


def _sanitize_fields(fields: Mapping[str, Any]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for key, value in fields.items():
        if key in ALLOWED_LOG_FIELDS:
            out[key] = redact_sensitive_data(value)
    return out


def _sanitize_event(event_dict: Mapping[str, Any]) -> Dict[str, Any]:
    payload: Dict[str, Any] = {}

    timestamp = event_dict.get("timestamp")
    if isinstance(timestamp, str):
        payload["timestamp"] = timestamp

    level = event_dict.get("level")
    if isinstance(level, str):
        payload["level"] = level.upper()

    message = event_dict.get("event")
    if isinstance(message, str):
        payload["event"] = message

    payload.update(_sanitize_fields(event_dict))
    return payload


def log_event(level: str, message: str, **fields: Any) -> None:
    method = level.lower()
    logger_method = getattr(LOGGER, method, LOGGER.info)
    logger_method(message, level=level.upper(), **fields)

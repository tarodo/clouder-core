"""Structured logging helpers with sensitive data redaction."""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, Mapping

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
    "beatport_url",
    "beatport_page",
    "beatport_attempt",
    "beatport_http_status",
    "s3_bucket",
    "s3_key",
    "s3_size_bytes",
}


LOGGER = logging.getLogger("collector")
if not LOGGER.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(message)s"))
    LOGGER.addHandler(handler)

LOGGER.setLevel(getattr(logging, os.getenv("LOG_LEVEL", "INFO").upper(), logging.INFO))


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


def log_event(level: str, message: str, **fields: Any) -> None:
    payload: Dict[str, Any] = {
        "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "level": level.upper(),
        "message": message,
    }
    payload.update(_sanitize_fields(fields))
    LOGGER.log(getattr(logging, level.upper(), logging.INFO), json.dumps(payload, ensure_ascii=True))

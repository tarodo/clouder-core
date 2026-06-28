"""Standalone telemetry ingest Lambda (spec §5.1/§5.2).

Validates a batch of behavior/playback envelopes, server-stamps identity, and
forwards valid events to Kinesis Firehose as NDJSON. Strictly isolated: its own
least-privilege role (firehose:PutRecordBatch only), its own integration/route.
Never touches the collector, the worker queue, or Aurora; never reads bp_token.
Shares the collector zip — entry point is collector.telemetry_handler.lambda_handler.
"""

from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from typing import Any, Mapping

from pydantic import ValidationError

from .logging_utils import log_event
from .telemetry_schemas import validate_event

_MAX_EVENTS = 256
_MAX_BODY_BYTES = 256 * 1024


def create_default_firehose_client():  # pragma: no cover - thin boto3 factory
    import boto3

    return boto3.client("firehose")


def _authorizer_context(event: Mapping[str, Any]) -> dict[str, Any]:
    rc = event.get("requestContext")
    if isinstance(rc, Mapping):
        authorizer = rc.get("authorizer")
        if isinstance(authorizer, Mapping):
            ctx = authorizer.get("lambda")
            if isinstance(ctx, Mapping):
                return dict(ctx)
    return {}


def _correlation_id(event: Mapping[str, Any]) -> str:
    headers = event.get("headers")
    if isinstance(headers, Mapping):
        for k, v in headers.items():
            if isinstance(k, str) and k.lower() == "x-correlation-id" and isinstance(v, str) and v:
                return v
    rc = event.get("requestContext")
    if isinstance(rc, Mapping):
        rid = rc.get("requestId")
        if isinstance(rid, str):
            return rid
    return "telemetry"


def _response(status: int, body: dict[str, Any], correlation_id: str) -> dict[str, Any]:
    return {
        "statusCode": status,
        "headers": {
            "content-type": "application/json",
            "x-correlation-id": correlation_id,
        },
        "body": json.dumps(body),
    }


def lambda_handler(event: Mapping[str, Any], context: Any, *, firehose_client: Any = None) -> dict[str, Any]:
    started = time.monotonic()
    correlation_id = _correlation_id(event)
    user_id = _authorizer_context(event).get("user_id")

    raw = event.get("body") or ""
    if len(raw.encode("utf-8")) > _MAX_BODY_BYTES:
        log_event(
            "WARNING", "telemetry_body_too_large",
            correlation_id=correlation_id, user_id=user_id, status_code=413,
        )
        return _response(413, {"error_code": "payload_too_large", "message": "body exceeds 256KB"}, correlation_id)

    try:
        parsed = json.loads(raw)
        events = parsed["events"]
        if not isinstance(events, list):
            raise ValueError("events must be a list")
    except (json.JSONDecodeError, KeyError, TypeError, ValueError):
        log_event(
            "WARNING", "telemetry_unparseable_body",
            correlation_id=correlation_id, user_id=user_id, status_code=400,
        )
        return _response(400, {"error_code": "invalid_body", "message": "expected {events: [...]}"}, correlation_id)

    if len(events) > _MAX_EVENTS:
        log_event(
            "WARNING", "telemetry_batch_too_large",
            correlation_id=correlation_id, user_id=user_id, status_code=400, count=len(events),
        )
        return _response(400, {"error_code": "batch_too_large", "message": "max 256 events"}, correlation_id)

    ts_server = datetime.now(timezone.utc).isoformat()
    records: list[dict[str, bytes]] = []
    rejected = 0
    for raw_event in events:
        try:
            clean = validate_event(raw_event, user_id=user_id, ts_server=ts_server)
        except (ValidationError, ValueError, TypeError):
            rejected += 1
            continue
        # props AND context both land on `string`-typed bronze Glue columns
        # (schema-on-read). The Firehose JSON SerDe will not coerce an object
        # onto a string column — emit both as JSON strings; dbt json_extracts
        # them back in silver (the locked bronze_events contract, Increment 4).
        clean["props"] = json.dumps(clean["props"], separators=(",", ":"))
        clean["context"] = json.dumps(clean["context"], separators=(",", ":"))
        line = (json.dumps(clean, separators=(",", ":")) + "\n").encode("utf-8")
        records.append({"Data": line})

    accepted = len(records)
    if records:
        client = firehose_client or create_default_firehose_client()
        stream = os.environ["TELEMETRY_FIREHOSE_STREAM_NAME"]
        # ponytail: single PutRecordBatch — the 256-event cap is well under
        # Firehose's 500-record limit, so no chunking is needed here.
        result = client.put_record_batch(DeliveryStreamName=stream, Records=records)
        failed = result.get("FailedPutCount", 0)
        if failed:
            # Loss-tolerant: log counts (allowlisted fields only), never retry inline.
            log_event(
                "WARNING", "telemetry_firehose_partial_failure",
                correlation_id=correlation_id, user_id=user_id, count=accepted, failed_after=failed,
            )

    log_event(
        "INFO", "telemetry_ingest",
        correlation_id=correlation_id, user_id=user_id, status_code=202,
        duration_ms=int((time.monotonic() - started) * 1000), count=accepted,
    )
    return _response(202, {"accepted": accepted, "rejected": rejected}, correlation_id)

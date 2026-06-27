"""Daily ops/pipeline-health export: enrichment + latency metrics from the
worker / auto-enrich-dispatch / collector CloudWatch log groups to the
analytics lake (bronze/ops/), for Dashboard 5 (spec sections 11, 16.1).

Each Lambda log line is one structlog JSON object. structlog's EventRenamer
maps the event name to the 'message' key (logging_utils.py:111), so the event
name is read from 'message', never 'event'. We keep the curated ops events and
project each record down to _OPS_FIELDS.

Real log group names (beatport-prod-*):
  /aws/lambda/beatport-prod-collector-api
  /aws/lambda/beatport-prod-canonicalization-worker
  /aws/lambda/beatport-prod-spotify-search-worker
  /aws/lambda/beatport-prod-vendor-match-worker
  /aws/lambda/beatport-prod-label-enricher-worker
  /aws/lambda/beatport-prod-artist-enricher-worker
  /aws/lambda/beatport-prod-auto-enrich-dispatch-worker
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any

from .logging_utils import log_event

# Event names worth landing for Dashboard 5 — read from the 'message' key.
# These are the real strings the workers emit (grep-confirmed). ponytail:
# curated allowlist of ~13 names; widen by one line if a dashboard needs more.
_OPS_EVENTS = frozenset({
    "canonicalization_worker_invoked", "canonicalization_completed",
    "spotify_worker_invoked", "spotify_search_completed",
    "vendor_match_worker_invoked",
    "label_enrichment_worker_invoked", "label_enrichment_completed",
    "artist_enrichment_worker_invoked", "artist_enrichment_completed",
    "auto_enrich_dispatch_started", "auto_enrich_dispatched",
    "auto_enrich_skipped_disabled", "auto_enrich_enqueue_partial_failure",
})

# Fields projected into bronze/ops. NOTE on the two non-allowlist keys we keep:
# 'timestamp' is set by TimeStamper, and 'level' is injected by log_event
# (level=level.upper(), logging_utils.py:168) and preserved by _sanitize_event
# (logging_utils.py:153-155) — both are TOP-LEVEL structlog keys, and NEITHER is
# an ALLOWED_LOG_FIELDS metric field. 'message' is the event name (EventRenamer
# renamed event->message, logging_utils.py:111). The rest ARE real
# ALLOWED_LOG_FIELDS metric fields (logging_utils.py:14-102).
_OPS_FIELDS = (
    "timestamp", "level", "message",
    "duration_ms", "source_hint", "completed_phases", "failed_after",
    "vendor", "phase", "attempt", "status_code",
    "candidate_labels", "candidate_artists", "claimed", "skipped", "run_id",
)


def _project(record: dict[str, Any]) -> dict[str, Any]:
    return {k: record[k] for k in _OPS_FIELDS if k in record}


def _ops_records(messages: list[str]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for raw in messages:
        try:
            rec = json.loads(raw)
        except (ValueError, TypeError):
            continue
        if not isinstance(rec, dict):
            continue
        if rec.get("message") not in _OPS_EVENTS:  # event name lives under 'message'
            continue
        out.append(_project(rec))
    return out


def _day_window(dt: str) -> tuple[int, int]:
    day = datetime.strptime(dt, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    start_ms = int(day.timestamp() * 1000)
    return start_ms, start_ms + 86_400_000


def export_ops_logs(
    logs_client: Any,
    s3_client: Any,
    bucket: str,
    log_groups: list[str],
    dt: str,
    start_ms: int,
    end_ms: int,
) -> dict[str, int]:
    counts: dict[str, int] = {}
    for group in log_groups:
        messages: list[str] = []
        kwargs: dict[str, Any] = {
            "logGroupName": group, "startTime": start_ms, "endTime": end_ms,
        }
        while True:
            resp = logs_client.filter_log_events(**kwargs)
            messages.extend(e["message"] for e in resp.get("events", []))
            token = resp.get("nextToken")
            if not token:
                break
            kwargs["nextToken"] = token
        records = _ops_records(messages)
        counts[group] = len(records)
        if not records:
            continue
        slug = group.rsplit("/", 1)[-1]
        body = "".join(
            json.dumps(r, ensure_ascii=False, separators=(",", ":")) + "\n"
            for r in records
        ).encode("utf-8")
        s3_client.put_object(
            Bucket=bucket, Key=f"bronze/ops/dt={dt}/{slug}.json", Body=body,
            ContentType="application/x-ndjson",
        )
    return counts


def lambda_handler(event: Any, context: Any) -> dict[str, Any]:
    import boto3

    bucket = os.environ["ANALYTICS_LAKE_BUCKET"]
    groups = [g.strip() for g in os.environ["OPS_LOG_GROUPS"].split(",") if g.strip()]
    dt = (event or {}).get("dt") or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    start_ms, end_ms = _day_window(dt)
    counts = export_ops_logs(
        boto3.client("logs"), boto3.client("s3"), bucket, groups, dt, start_ms, end_ms,
    )
    log_event("INFO", "ops_log_export_completed", item_count=sum(counts.values()))
    return {"dt": dt, "counts": counts}

"""SQS worker: run triage-block auto-enrichment fan-out off the request path.

Each message is `{block_id, user_id}`. For each, runs the label, artist, and comment
dispatch (each best-effort internally), which enqueue per-item work onto the
existing enrichment queues. An unparseable record raises so SQS redrives it to
the DLQ after the queue's maxReceiveCount.
"""

from __future__ import annotations

import json
from typing import Any, Mapping

from .artist_enrichment.auto_dispatch import try_dispatch_artists_for_triage_block
from .comments.auto_dispatch import try_dispatch_comments_for_triage_block
from .label_enrichment.auto_dispatch import try_dispatch_for_triage_block
from .logging_utils import log_event


def lambda_handler(event: Mapping[str, Any], context: Any) -> dict[str, Any]:
    records = event.get("Records", [])
    for record in records:
        msg = json.loads(record["body"])
        block_id = msg["block_id"]
        user_id = msg.get("user_id")
        log_event("INFO", "auto_enrich_block_dispatch_received", block_id=block_id)
        try_dispatch_for_triage_block(block_id=block_id, user_id=user_id)
        try_dispatch_artists_for_triage_block(block_id=block_id, user_id=user_id)
        try_dispatch_comments_for_triage_block(block_id=block_id, user_id=user_id)
    return {"processed": len(records)}

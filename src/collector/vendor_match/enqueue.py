"""Producer: send VendorMatchMessage to the vendor-match queue.

Failures never propagate — enqueue is best-effort so a transient SQS issue
cannot fail the originating user request. The match simply arrives later.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol

from ..logging_utils import log_event
from ..schemas import VendorMatchMessage

if TYPE_CHECKING:
    from ..curation.playlists_repository import MatchInput

YTMUSIC_VENDOR = "ytmusic"


class SqsSender(Protocol):
    def send_message(self, *, QueueUrl: str, MessageBody: str) -> Any: ...


def enqueue_vendor_matches(
    *,
    track_inputs: "list[MatchInput]",
    vendor: str,
    queue_url: str,
    sqs: SqsSender,
    correlation_id: str = "",
) -> int:
    """Send one message per input. Returns the count actually sent."""
    if not queue_url:
        log_event(
            "WARNING", "vendor_match_enqueue_skipped",
            reason="no_queue_url", vendor=vendor,
        )
        return 0

    sent = 0
    for inp in track_inputs:
        try:
            message = VendorMatchMessage(
                clouder_track_id=inp.track_id,
                vendor=vendor,
                isrc=inp.isrc,
                artist=inp.artist,
                title=inp.title,
                duration_ms=inp.duration_ms,
                album=inp.album,
            )
        except Exception as exc:  # pydantic validation (e.g. empty artist/title)
            log_event(
                "WARNING", "vendor_match_enqueue_invalid",
                track_id=inp.track_id, vendor=vendor, error_message=str(exc),
            )
            continue
        try:
            sqs.send_message(QueueUrl=queue_url, MessageBody=message.model_dump_json())
            sent += 1
        except Exception as exc:
            log_event(
                "ERROR", "vendor_match_enqueue_failed",
                track_id=inp.track_id, vendor=vendor, error_message=str(exc),
            )

    log_event(
        "INFO", "vendor_match_enqueued",
        vendor=vendor, count=sent, correlation_id=correlation_id,
    )
    return sent

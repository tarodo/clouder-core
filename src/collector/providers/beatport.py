"""BeatportProvider — IngestProvider adapter over BeatportClient."""

from __future__ import annotations

from typing import Any

from ..beatport_client import BeatportClient


class BeatportProvider:
    """Thin adapter — delegates everything to BeatportClient.

    Exists so handlers depend on the providers package surface, not on
    vendor-specific modules. Internal client behavior (retries, pagination,
    correlation_id propagation) is preserved as-is.
    """

    source_name = "beatport"

    def __init__(
        self,
        base_url: str,
        client: BeatportClient | None = None,
    ) -> None:
        self._client = client or BeatportClient(base_url=base_url)

    def fetch_weekly_releases(
        self,
        bp_token: str,
        style_id: int,
        week_start: str,
        week_end: str,
        correlation_id: str,
    ) -> tuple[list[dict[str, Any]], int]:
        return self._client.fetch_weekly_releases(
            bp_token=bp_token,
            style_id=style_id,
            week_start=week_start,
            week_end=week_end,
            correlation_id=correlation_id,
        )

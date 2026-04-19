"""Tidal lookup stub — raises VendorDisabledError until implemented."""

from __future__ import annotations

from typing import Any

from ...errors import VendorDisabledError
from ..base import VendorTrackRef


class TidalLookup:
    vendor_name = "tidal"

    def lookup_batch_by_isrc(
        self,
        tracks: list[dict[str, str]],
        correlation_id: str,
    ) -> list[Any]:
        raise VendorDisabledError(self.vendor_name, reason="not_implemented")

    def lookup_by_isrc(self, isrc: str) -> VendorTrackRef | None:
        raise VendorDisabledError(self.vendor_name, reason="not_implemented")

    def lookup_by_metadata(
        self,
        artist: str,
        title: str,
        duration_ms: int | None,
        album: str | None,
    ) -> list[VendorTrackRef]:
        raise VendorDisabledError(self.vendor_name, reason="not_implemented")

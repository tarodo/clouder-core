"""Tidal lookup stub — raises VendorDisabledError until implemented."""

from __future__ import annotations

from typing import Any

from ...errors import VendorDisabledError


class TidalLookup:
    vendor_name = "tidal"

    def lookup_batch_by_isrc(
        self,
        tracks: list[dict[str, str]],
        correlation_id: str,
    ) -> list[Any]:
        raise VendorDisabledError(self.vendor_name)

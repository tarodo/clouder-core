"""Deezer export stub — raises VendorDisabledError until implemented."""

from __future__ import annotations

from ...errors import VendorDisabledError
from ..base import VendorPlaylistRef, VendorTrackRef


class DeezerExporter:
    vendor_name = "deezer"

    def create_playlist(
        self,
        user_token: str,
        name: str,
        track_refs: list[VendorTrackRef],
    ) -> VendorPlaylistRef:
        raise VendorDisabledError(self.vendor_name, reason="not_implemented")

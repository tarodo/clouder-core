"""SpotifyExporter — stub. Real implementation requires user OAuth (Plan 4)."""

from __future__ import annotations

from ...errors import VendorDisabledError
from ..base import VendorPlaylistRef, VendorTrackRef


class SpotifyExporter:
    vendor_name = "spotify"

    def create_playlist(
        self,
        user_token: str,
        name: str,
        track_refs: list[VendorTrackRef],
    ) -> VendorPlaylistRef:
        raise VendorDisabledError("spotify", reason="not_implemented")

"""Unit tests for SpotifyExporter stub."""
from __future__ import annotations

import pytest

from collector.errors import VendorDisabledError
from collector.providers.base import ExportProvider
from collector.providers.spotify.export import SpotifyExporter


def test_exporter_implements_protocol() -> None:
    exporter = SpotifyExporter()
    assert isinstance(exporter, ExportProvider)
    assert exporter.vendor_name == "spotify"


def test_exporter_raises_until_implemented() -> None:
    exporter = SpotifyExporter()
    with pytest.raises(VendorDisabledError) as exc_info:
        exporter.create_playlist(user_token="t", name="n", track_refs=[])
    assert "spotify" in exc_info.value.vendor

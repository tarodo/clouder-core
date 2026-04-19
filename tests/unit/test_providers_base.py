"""Unit tests for provider Protocol surface and shared types."""
from __future__ import annotations

import pytest

from collector.errors import AppError, VendorDisabledError
from collector.providers.base import (
    EnrichProvider,
    EnrichResult,
    ExportProvider,
    IngestProvider,
    LookupProvider,
    ProviderBundle,
    RawIngestPayload,
    VendorPlaylistRef,
    VendorTrackRef,
)


def test_vendor_track_ref_is_frozen() -> None:
    ref = VendorTrackRef(
        vendor="spotify",
        vendor_track_id="abc",
        isrc="USRC00000001",
        artist_names=("Foo",),
        title="Bar",
        duration_ms=200_000,
        album_name="Baz",
        raw_payload={"id": "abc"},
    )
    assert ref.vendor == "spotify"
    assert ref.artist_names == ("Foo",)
    with pytest.raises(Exception):
        ref.vendor = "other"  # frozen dataclass


def test_provider_bundle_defaults_none() -> None:
    bundle = ProviderBundle()
    assert bundle.ingest is None
    assert bundle.lookup is None
    assert bundle.enrich is None
    assert bundle.export is None


def test_raw_ingest_payload_holds_source_and_meta() -> None:
    payload = RawIngestPayload(
        source="beatport",
        items=[{"id": 1}],
        meta={"pages": 2},
    )
    assert payload.source == "beatport"
    assert payload.items == [{"id": 1}]
    assert payload.meta == {"pages": 2}


def test_enrich_result_required_fields() -> None:
    result = EnrichResult(
        entity_type="label",
        entity_id="42",
        prompt_slug="label_info",
        prompt_version="v1",
        payload={"size": "small"},
    )
    assert result.entity_type == "label"
    assert result.payload == {"size": "small"}


def test_vendor_playlist_ref_basic() -> None:
    ref = VendorPlaylistRef(vendor="spotify", vendor_playlist_id="pl1", url=None)
    assert ref.vendor == "spotify"


def test_vendor_disabled_error_is_app_error() -> None:
    err = VendorDisabledError("ytmusic")
    assert isinstance(err, AppError)
    assert err.status_code == 400
    assert err.error_code == "vendor_disabled"
    assert "ytmusic" in err.message
    assert err.vendor == "ytmusic"
    assert "ytmusic" in str(err)


def test_protocol_classes_are_runtime_checkable() -> None:
    # Negative check — random object isn't a provider.
    assert not isinstance(object(), IngestProvider)
    assert not isinstance(object(), LookupProvider)
    assert not isinstance(object(), EnrichProvider)
    assert not isinstance(object(), ExportProvider)

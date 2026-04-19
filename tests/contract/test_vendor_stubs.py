"""Contract tests — every stub vendor satisfies LookupProvider/ExportProvider
Protocol and raises VendorDisabledError on use."""
from __future__ import annotations

import pytest

from collector.errors import VendorDisabledError
from collector.providers import registry
from collector.providers.base import ExportProvider, LookupProvider


_STUB_VENDORS = ["ytmusic", "deezer", "apple", "tidal"]


@pytest.fixture(autouse=True)
def _enable_all_stubs(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("VENDORS_ENABLED", ",".join(_STUB_VENDORS))
    registry.reset_cache()
    yield
    registry.reset_cache()


@pytest.mark.parametrize("name", _STUB_VENDORS)
def test_stub_lookup_satisfies_protocol(name: str) -> None:
    lookup = registry.get_lookup(name)
    assert isinstance(lookup, LookupProvider)
    assert lookup.vendor_name == name


@pytest.mark.parametrize("name", _STUB_VENDORS)
def test_stub_lookup_raises(name: str) -> None:
    lookup = registry.get_lookup(name)
    with pytest.raises(VendorDisabledError) as exc_info:
        lookup.lookup_batch_by_isrc(
            tracks=[{"clouder_track_id": "x", "isrc": "USRC00000001"}],
            correlation_id="c",
        )
    assert exc_info.value.reason == "not_implemented"


@pytest.mark.parametrize("name", _STUB_VENDORS)
def test_stub_export_satisfies_protocol(name: str) -> None:
    exporter = registry.get_exporter(name)
    assert isinstance(exporter, ExportProvider)
    assert exporter.vendor_name == name


@pytest.mark.parametrize("name", _STUB_VENDORS)
def test_stub_export_raises(name: str) -> None:
    exporter = registry.get_exporter(name)
    with pytest.raises(VendorDisabledError) as exc_info:
        exporter.create_playlist(user_token="t", name="n", track_refs=[])
    assert exc_info.value.reason == "not_implemented"

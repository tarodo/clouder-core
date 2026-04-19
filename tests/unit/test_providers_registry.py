"""Unit tests for provider registry and VENDORS_ENABLED gating."""
from __future__ import annotations

import pytest
from collections.abc import Iterator

from collector.errors import VendorDisabledError
from collector.providers import registry


@pytest.fixture(autouse=True)
def _reset_cache() -> Iterator[None]:
    registry.reset_cache()
    yield
    registry.reset_cache()


def test_enabled_vendors_parse_csv(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VENDORS_ENABLED", "beatport, spotify ,, ytmusic")
    assert registry._enabled_vendors() == {"beatport", "spotify", "ytmusic"}


def test_enabled_vendors_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VENDORS_ENABLED", "")
    assert registry._enabled_vendors() == set()


def test_get_disabled_vendor_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VENDORS_ENABLED", "")
    with pytest.raises(VendorDisabledError) as exc_info:
        registry.get_lookup("spotify")
    assert exc_info.value.vendor == "spotify"


def test_get_unknown_vendor_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VENDORS_ENABLED", "spotify")
    with pytest.raises(VendorDisabledError):
        registry.get_lookup("nonexistent")


def test_disabled_vendor_does_not_build_bundle(monkeypatch: pytest.MonkeyPatch) -> None:
    """Disabled vendor must not instantiate its provider — important so
    that unrelated tests don't need to set every vendor's env vars.
    """
    monkeypatch.setenv("VENDORS_ENABLED", "")
    monkeypatch.delenv("RAW_BUCKET_NAME", raising=False)
    # If we eagerly built beatport, this would fail with pydantic.ValidationError
    # because RAW_BUCKET_NAME is a required field on ApiSettings.
    with pytest.raises(VendorDisabledError):
        registry.get_ingest("beatport")


def test_list_enabled_exporters_filters(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VENDORS_ENABLED", "ytmusic,deezer")
    names = sorted(p.vendor_name for p in registry.list_enabled_exporters())
    assert names == ["deezer", "ytmusic"]


def test_get_enricher_for_prompt_known(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VENDORS_ENABLED", "perplexity_label")
    enricher = registry.get_enricher_for_prompt("label_info")
    assert enricher.prompt_slug == "label_info"


def test_get_enricher_for_prompt_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VENDORS_ENABLED", "")
    with pytest.raises(VendorDisabledError):
        registry.get_enricher_for_prompt("label_info")


def test_get_enricher_for_prompt_unknown(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VENDORS_ENABLED", "perplexity_label")
    with pytest.raises(VendorDisabledError):
        registry.get_enricher_for_prompt("totally_unknown_slug")

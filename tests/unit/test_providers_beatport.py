"""Unit tests for the BeatportProvider adapter."""
from __future__ import annotations

from typing import Any

import pytest

from collector.providers.base import IngestProvider
from collector.providers.beatport import BeatportProvider


def test_beatport_provider_implements_protocol() -> None:
    provider = BeatportProvider(base_url="https://example.test/v4/catalog")
    assert isinstance(provider, IngestProvider)
    assert provider.source_name == "beatport"


def test_beatport_provider_delegates_to_client(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    def fake_fetch(self: Any, **kwargs: Any) -> tuple[list[dict[str, Any]], int]:
        captured.update(kwargs)
        return [{"id": 1}], 3

    from collector.beatport_client import BeatportClient

    monkeypatch.setattr(BeatportClient, "fetch_weekly_releases", fake_fetch)

    provider = BeatportProvider(base_url="https://example.test/v4/catalog")
    items, pages = provider.fetch_weekly_releases(
        bp_token="tok",
        style_id=11,
        week_start="2026-01-05",
        week_end="2026-01-11",
        correlation_id="corr-1",
    )

    assert items == [{"id": 1}]
    assert pages == 3
    assert captured == {
        "bp_token": "tok",
        "style_id": 11,
        "week_start": "2026-01-05",
        "week_end": "2026-01-11",
        "correlation_id": "corr-1",
    }

"""VendorMatchSettings tests (Plan 4 Task 0b)."""

from __future__ import annotations

import pytest

from collector.settings import get_vendor_match_settings, reset_settings_cache


@pytest.fixture(autouse=True)
def _clear_cache() -> None:
    reset_settings_cache()
    yield
    reset_settings_cache()


def test_defaults() -> None:
    settings = get_vendor_match_settings()
    assert settings.fuzzy_match_threshold == pytest.approx(0.92)
    assert settings.fuzzy_duration_tolerance_ms == 3000


def test_env_override(monkeypatch) -> None:
    monkeypatch.setenv("FUZZY_MATCH_THRESHOLD", "0.85")
    monkeypatch.setenv("FUZZY_DURATION_TOLERANCE_MS", "5000")
    reset_settings_cache()

    settings = get_vendor_match_settings()

    assert settings.fuzzy_match_threshold == pytest.approx(0.85)
    assert settings.fuzzy_duration_tolerance_ms == 5000


def test_threshold_bounds_rejected(monkeypatch) -> None:
    monkeypatch.setenv("FUZZY_MATCH_THRESHOLD", "1.5")
    reset_settings_cache()
    with pytest.raises(Exception):
        get_vendor_match_settings()

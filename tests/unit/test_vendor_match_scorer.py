"""Fuzzy scorer tests (Plan 4 Task 4)."""

from __future__ import annotations

import pytest

from collector.providers.base import VendorTrackRef
from collector.settings import reset_settings_cache
from collector.vendor_match.scorer import FuzzyScore, score_candidate


@pytest.fixture(autouse=True)
def _clear_cache() -> None:
    reset_settings_cache()
    yield
    reset_settings_cache()


def _candidate(**overrides) -> VendorTrackRef:
    base = dict(
        vendor="spotify",
        vendor_track_id="x",
        isrc=None,
        artist_names=("Foo",),
        title="Bar",
        duration_ms=200_000,
        album_name="Baz",
        raw_payload={},
    )
    base.update(overrides)
    return VendorTrackRef(**base)


def test_perfect_match() -> None:
    cand = _candidate()
    s = score_candidate(
        candidate=cand, artist="Foo", title="Bar",
        duration_ms=200_000, album="Baz",
    )
    assert s.total >= 0.95


def test_title_differs_slightly() -> None:
    cand = _candidate(title="Bar (Remix)")
    s = score_candidate(
        candidate=cand, artist="Foo", title="Bar",
        duration_ms=200_000, album="Baz",
    )
    assert 0.6 <= s.total < 0.95


def test_duration_outside_tolerance_penalises() -> None:
    cand = _candidate(duration_ms=250_000)
    s = score_candidate(
        candidate=cand, artist="Foo", title="Bar",
        duration_ms=200_000, album="Baz",
    )
    assert not s.duration_ok


def test_artist_mismatch() -> None:
    cand = _candidate(artist_names=("Different",))
    s = score_candidate(
        candidate=cand, artist="Foo", title="Bar",
        duration_ms=200_000, album="Baz",
    )
    assert s.artist_sim < 0.5


def test_multi_artist_query_uses_best_pair() -> None:
    cand = _candidate(artist_names=("Foo",))
    s = score_candidate(
        candidate=cand, artist="Foo & Bar", title="Bar",
        duration_ms=200_000, album="Baz",
    )
    assert s.artist_sim == pytest.approx(1.0)


def test_album_bonus_when_match() -> None:
    cand = _candidate()
    s = score_candidate(
        candidate=cand, artist="Foo", title="Bar",
        duration_ms=200_000, album="Baz",
    )
    assert s.album_bonus == pytest.approx(0.05)


def test_album_bonus_zero_when_mismatch() -> None:
    cand = _candidate(album_name="Different")
    s = score_candidate(
        candidate=cand, artist="Foo", title="Bar",
        duration_ms=200_000, album="Baz",
    )
    assert s.album_bonus == 0.0


def test_score_fields_accessible() -> None:
    cand = _candidate()
    s = score_candidate(
        candidate=cand, artist="Foo", title="Bar",
        duration_ms=200_000, album="Baz",
    )
    assert isinstance(s, FuzzyScore)
    assert 0.0 <= s.title_sim <= 1.0
    assert 0.0 <= s.artist_sim <= 1.0
    assert isinstance(s.duration_ok, bool)
    assert 0.0 <= s.total <= 1.0


def test_duration_unknown_is_not_ok() -> None:
    cand = _candidate(duration_ms=None)
    s = score_candidate(
        candidate=cand, artist="Foo", title="Bar",
        duration_ms=200_000, album="Baz",
    )
    assert not s.duration_ok


def test_tolerance_override_via_env(monkeypatch) -> None:
    monkeypatch.setenv("FUZZY_DURATION_TOLERANCE_MS", "60000")
    reset_settings_cache()

    cand = _candidate(duration_ms=250_000)
    s = score_candidate(
        candidate=cand, artist="Foo", title="Bar",
        duration_ms=200_000, album="Baz",
    )
    assert s.duration_ok

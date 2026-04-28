"""Unit tests for batch_update_spotify_results spotify_release_date COALESCE."""

from __future__ import annotations

from datetime import date, datetime, timezone

from collector.repositories import (
    ClouderRepository,
    UpdateSpotifyResultCmd,
)


def test_batch_update_spotify_results_includes_release_date() -> None:
    """spec-D: spotify_release_date must be COALESCEd into clouder_tracks."""
    captured: dict = {}

    class _FakeAPI:
        def batch_execute(self, sql, params, transaction_id=None):
            captured["sql"] = sql
            captured["params"] = params
            captured["transaction_id"] = transaction_id

    repo = ClouderRepository(_FakeAPI())
    cmd = UpdateSpotifyResultCmd(
        track_id="t-1",
        spotify_id="sp-1",
        searched_at=datetime.now(timezone.utc),
        release_type="album",
        spotify_release_date=date(2024, 3, 15),
    )
    repo.batch_update_spotify_results([cmd])

    assert "spotify_release_date = COALESCE(" in captured["sql"]
    assert captured["params"][0]["spotify_release_date"] == date(2024, 3, 15)


def test_batch_update_spotify_results_release_date_default_none() -> None:
    """spec-D: when spotify_release_date is omitted, bind value is None
    so COALESCE preserves the existing column value."""
    captured: dict = {}

    class _FakeAPI:
        def batch_execute(self, sql, params, transaction_id=None):
            captured["sql"] = sql
            captured["params"] = params

    repo = ClouderRepository(_FakeAPI())
    cmd = UpdateSpotifyResultCmd(
        track_id="t-2",
        spotify_id="sp-2",
        searched_at=datetime.now(timezone.utc),
    )
    repo.batch_update_spotify_results([cmd])

    assert captured["params"][0]["spotify_release_date"] is None


def test_batch_update_spotify_results_empty_no_call() -> None:
    """No commands -> no batch_execute call."""
    calls: list = []

    class _FakeAPI:
        def batch_execute(self, sql, params, transaction_id=None):
            calls.append((sql, params))

    repo = ClouderRepository(_FakeAPI())
    repo.batch_update_spotify_results([])
    assert calls == []

"""Tests for Spotify metadata-fallback scoring + accept gate."""

from __future__ import annotations

import json
from unittest.mock import patch

from collector.spotify_client import SpotifyClient, _accept_metadata_match


class _Resp:
    def __init__(self, payload: dict) -> None:
        self._b = json.dumps(payload).encode()

    def read(self) -> bytes:
        return self._b

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass


def _make_client() -> SpotifyClient:
    c = SpotifyClient(
        client_id="x", client_secret="y", sleep_fn=lambda _: None,
    )
    c._access_token = "tok"
    c._token_expires_at = 9e18
    return c


def _spotify_track(
    *, sp_id: str, name: str, artists: list[str],
    duration_ms: int, isrc: str = "ZZZ123",
) -> dict:
    return {
        "id": sp_id,
        "name": name,
        "artists": [{"name": a} for a in artists],
        "duration_ms": duration_ms,
        "external_ids": {"isrc": isrc},
        "album": {"release_date": "2026-01-01", "release_date_precision": "day"},
    }


def test_accept_match_passes_strict_thresholds() -> None:
    assert _accept_metadata_match(
        title_sim=0.92,
        artist_sim=0.88,
        candidate_duration_ms=180_000,
        query_duration_ms=181_500,
        title_min=0.90,
        artist_min=0.85,
        duration_tolerance_ms=3000,
    )


def test_accept_rejects_low_title_sim() -> None:
    assert not _accept_metadata_match(
        title_sim=0.89,
        artist_sim=0.99,
        candidate_duration_ms=180_000,
        query_duration_ms=180_000,
        title_min=0.90,
        artist_min=0.85,
        duration_tolerance_ms=3000,
    )


def test_accept_rejects_low_artist_sim() -> None:
    assert not _accept_metadata_match(
        title_sim=1.0,
        artist_sim=0.84,
        candidate_duration_ms=180_000,
        query_duration_ms=180_000,
        title_min=0.90,
        artist_min=0.85,
        duration_tolerance_ms=3000,
    )


def test_accept_rejects_duration_outside_tolerance() -> None:
    assert not _accept_metadata_match(
        title_sim=1.0,
        artist_sim=1.0,
        candidate_duration_ms=180_000,
        query_duration_ms=184_000,
        title_min=0.90,
        artist_min=0.85,
        duration_tolerance_ms=3000,
    )


def test_accept_passes_when_query_duration_unknown() -> None:
    assert _accept_metadata_match(
        title_sim=0.95,
        artist_sim=0.90,
        candidate_duration_ms=180_000,
        query_duration_ms=None,
        title_min=0.90,
        artist_min=0.85,
        duration_tolerance_ms=3000,
    )


def test_accept_passes_when_candidate_duration_unknown() -> None:
    assert _accept_metadata_match(
        title_sim=0.95,
        artist_sim=0.90,
        candidate_duration_ms=None,
        query_duration_ms=180_000,
        title_min=0.90,
        artist_min=0.85,
        duration_tolerance_ms=3000,
    )


def test_search_by_metadata_picks_best_when_passes_gate() -> None:
    client = _make_client()
    payload = {
        "tracks": {
            "items": [
                _spotify_track(
                    sp_id="sp_match",
                    name="Move On",
                    artists=["Guri & Eider"],
                    duration_ms=180_000,
                    isrc="GBKQU2633815",
                ),
            ]
        }
    }
    with patch(
        "collector.spotify_client.urllib.request.urlopen",
        return_value=_Resp(payload),
    ):
        track = client._search_by_metadata(
            title="Move On",
            artist="Guri & Eider",
            duration_ms=181_000,
            correlation_id="cid",
            title_min=0.90,
            artist_min=0.85,
            duration_tolerance_ms=3000,
        )
    assert track is not None
    assert track["id"] == "sp_match"


def test_search_by_metadata_returns_none_when_no_items() -> None:
    client = _make_client()
    with patch(
        "collector.spotify_client.urllib.request.urlopen",
        return_value=_Resp({"tracks": {"items": []}}),
    ):
        track = client._search_by_metadata(
            title="Nothing", artist="Nobody", duration_ms=180_000,
            correlation_id="cid",
            title_min=0.90, artist_min=0.85, duration_tolerance_ms=3000,
        )
    assert track is None


def test_search_by_metadata_returns_none_when_all_fail_gate() -> None:
    client = _make_client()
    payload = {
        "tracks": {
            "items": [
                _spotify_track(
                    sp_id="bad",
                    name="Totally Different Song",
                    artists=["Other Person"],
                    duration_ms=180_000,
                ),
            ]
        }
    }
    with patch(
        "collector.spotify_client.urllib.request.urlopen",
        return_value=_Resp(payload),
    ):
        track = client._search_by_metadata(
            title="Move On", artist="Guri & Eider", duration_ms=180_000,
            correlation_id="cid",
            title_min=0.90, artist_min=0.85, duration_tolerance_ms=3000,
        )
    assert track is None


def test_search_by_metadata_returns_none_for_empty_inputs() -> None:
    client = _make_client()
    with patch(
        "collector.spotify_client.urllib.request.urlopen",
        side_effect=AssertionError("must not be called"),
    ):
        assert client._search_by_metadata(
            title="", artist="Some Artist", duration_ms=180_000,
            correlation_id="cid",
            title_min=0.90, artist_min=0.85, duration_tolerance_ms=3000,
        ) is None
        assert client._search_by_metadata(
            title="Some Title", artist="", duration_ms=180_000,
            correlation_id="cid",
            title_min=0.90, artist_min=0.85, duration_tolerance_ms=3000,
        ) is None


def test_search_by_metadata_picks_highest_combined_when_multiple_pass() -> None:
    client = _make_client()
    payload = {
        "tracks": {
            "items": [
                _spotify_track(
                    sp_id="ok_but_lower",
                    name="Move On (Original)",
                    artists=["Guri Eider"],
                    duration_ms=180_500,
                ),
                _spotify_track(
                    sp_id="best",
                    name="Move On",
                    artists=["Guri & Eider"],
                    duration_ms=181_000,
                ),
            ]
        }
    }
    with patch(
        "collector.spotify_client.urllib.request.urlopen",
        return_value=_Resp(payload),
    ):
        track = client._search_by_metadata(
            title="Move On", artist="Guri & Eider", duration_ms=181_000,
            correlation_id="cid",
            title_min=0.90, artist_min=0.85, duration_tolerance_ms=3000,
        )
    assert track is not None
    assert track["id"] == "best"

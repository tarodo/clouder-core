"""Tests for SpotifyClient: auth, search, retry, rate limiting."""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from collector.errors import SpotifyAuthError, SpotifyUnavailableError
from collector.spotify_client import SpotifyClient, SpotifySearchResult, _album_release_sort_key


class FakeResponse:
    def __init__(self, data: dict, status: int = 200):
        self._data = json.dumps(data).encode("utf-8")
        self.status = status

    def read(self) -> bytes:
        return self._data

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass


def _noop_sleep(seconds: float) -> None:
    pass


def _make_client(**kwargs) -> SpotifyClient:
    return SpotifyClient(
        client_id="test_id",
        client_secret="test_secret",
        sleep_fn=_noop_sleep,
        **kwargs,
    )


def _auth_response() -> FakeResponse:
    return FakeResponse({"access_token": "tok123", "expires_in": 3600})


def _search_response(track_id: str = "sp1", track_name: str = "Test") -> FakeResponse:
    return FakeResponse({
        "tracks": {
            "items": [
                {"id": track_id, "name": track_name, "popularity": 42}
            ]
        }
    })


def _empty_search_response() -> FakeResponse:
    return FakeResponse({"tracks": {"items": []}})


def test_search_tracks_by_isrc_found() -> None:
    client = _make_client()
    call_count = 0

    def fake_urlopen(request, timeout=None):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return _auth_response()
        return _search_response(track_id="sp_abc")

    with patch("collector.spotify_client.urllib.request.urlopen", fake_urlopen):
        results = client.search_tracks_by_isrc(
            tracks=[{"clouder_track_id": "ct1", "isrc": "USRC12345"}],
            correlation_id="cid-1",
        )

    assert len(results) == 1
    assert results[0].spotify_id == "sp_abc"
    assert results[0].isrc == "USRC12345"
    assert results[0].clouder_track_id == "ct1"
    assert results[0].spotify_track is not None
    assert results[0].spotify_track["id"] == "sp_abc"


def test_search_tracks_by_isrc_not_found() -> None:
    client = _make_client()
    call_count = 0

    def fake_urlopen(request, timeout=None):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return _auth_response()
        return _empty_search_response()

    with patch("collector.spotify_client.urllib.request.urlopen", fake_urlopen):
        results = client.search_tracks_by_isrc(
            tracks=[{"clouder_track_id": "ct1", "isrc": "USRC99999"}],
            correlation_id="cid-1",
        )

    assert len(results) == 1
    assert results[0].spotify_id is None
    assert results[0].spotify_track is None


def test_search_tracks_multiple() -> None:
    client = _make_client()
    call_count = 0

    def fake_urlopen(request, timeout=None):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return _auth_response()
        if call_count == 2:
            return _search_response(track_id="sp1")
        return _empty_search_response()

    with patch("collector.spotify_client.urllib.request.urlopen", fake_urlopen):
        results = client.search_tracks_by_isrc(
            tracks=[
                {"clouder_track_id": "ct1", "isrc": "ISRC1"},
                {"clouder_track_id": "ct2", "isrc": "ISRC2"},
            ],
            correlation_id="cid-1",
        )

    assert len(results) == 2
    assert results[0].spotify_id == "sp1"
    assert results[1].spotify_id is None


def test_auth_failure_raises() -> None:
    client = _make_client()
    from urllib.error import HTTPError

    def fake_urlopen(request, timeout=None):
        raise HTTPError(
            url="https://accounts.spotify.com/api/token",
            code=403,
            msg="Forbidden",
            hdrs=None,
            fp=None,
        )

    with patch("collector.spotify_client.urllib.request.urlopen", fake_urlopen):
        with pytest.raises(SpotifyAuthError):
            client.search_tracks_by_isrc(
                tracks=[{"clouder_track_id": "ct1", "isrc": "ISRC1"}],
                correlation_id="cid-1",
            )


def test_token_reuse() -> None:
    """Second call should reuse the cached token, not re-authenticate."""
    client = _make_client()
    auth_call_count = 0

    def fake_urlopen(request, timeout=None):
        nonlocal auth_call_count
        url = request.full_url if hasattr(request, "full_url") else str(request)
        if "accounts.spotify.com" in url:
            auth_call_count += 1
            return _auth_response()
        return _search_response()

    with patch("collector.spotify_client.urllib.request.urlopen", fake_urlopen):
        client.search_tracks_by_isrc(
            tracks=[{"clouder_track_id": "ct1", "isrc": "ISRC1"}],
            correlation_id="cid-1",
        )
        client.search_tracks_by_isrc(
            tracks=[{"clouder_track_id": "ct2", "isrc": "ISRC2"}],
            correlation_id="cid-2",
        )

    assert auth_call_count == 1


def test_search_result_dataclass() -> None:
    result = SpotifySearchResult(
        isrc="USRC1",
        clouder_track_id="ct1",
        spotify_track={"id": "sp1"},
        spotify_id="sp1",
    )
    assert result.isrc == "USRC1"
    assert result.spotify_id == "sp1"


def test_search_picks_earliest_track_by_release_date() -> None:
    """When multiple tracks match the same ISRC, return the earliest by release date."""
    client = _make_client()
    call_count = 0

    def fake_urlopen(request, timeout=None):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return _auth_response()
        return FakeResponse({
            "tracks": {
                "items": [
                    {"id": "sp_remaster", "name": "Track (Remaster)", "album": {"release_date": "2020-06-15"}},
                    {"id": "sp_original", "name": "Track", "album": {"release_date": "2005-03-01"}},
                    {"id": "sp_deluxe", "name": "Track (Deluxe)", "album": {"release_date": "2021-01-10"}},
                ]
            }
        })

    with patch("collector.spotify_client.urllib.request.urlopen", fake_urlopen):
        results = client.search_tracks_by_isrc(
            tracks=[{"clouder_track_id": "ct1", "isrc": "ISRC001"}],
            correlation_id="cid-1",
        )

    assert len(results) == 1
    assert results[0].spotify_id == "sp_original"
    assert results[0].spotify_track["name"] == "Track"


def test_search_handles_partial_release_dates() -> None:
    """Tracks with year-only dates should still sort correctly."""
    client = _make_client()
    call_count = 0

    def fake_urlopen(request, timeout=None):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return _auth_response()
        return FakeResponse({
            "tracks": {
                "items": [
                    {"id": "sp_new", "name": "New", "album": {"release_date": "2022"}},
                    {"id": "sp_old", "name": "Old", "album": {"release_date": "1998-05"}},
                ]
            }
        })

    with patch("collector.spotify_client.urllib.request.urlopen", fake_urlopen):
        results = client.search_tracks_by_isrc(
            tracks=[{"clouder_track_id": "ct1", "isrc": "ISRC002"}],
            correlation_id="cid-1",
        )

    assert results[0].spotify_id == "sp_old"


def test_rate_limit_long_cooldown_raises_unavailable() -> None:
    """Retry-After > 120s must raise SpotifyUnavailableError instead of sleeping
    longer than the Lambda timeout."""
    from urllib.error import HTTPError

    client = _make_client()
    client._access_token = "tok"
    client._token_expires_at = 9e18

    class _Headers:
        def get(self, key, default=None):
            if key == "Retry-After":
                return "1296"
            return default

    def fake_urlopen(request, timeout=None):
        raise HTTPError(
            url=request.full_url, code=429, msg="rate", hdrs=_Headers(), fp=None
        )

    with patch("collector.spotify_client.urllib.request.urlopen", fake_urlopen):
        with pytest.raises(SpotifyUnavailableError, match="exceeds cap"):
            client.search_tracks_by_isrc(
                tracks=[{"clouder_track_id": "ct1", "isrc": "ZZ1"}],
                correlation_id="cid-rl",
            )


def test_rate_limit_short_cooldown_sleeps_and_retries() -> None:
    """Retry-After <= 120s should still sleep + retry as before."""
    from urllib.error import HTTPError

    sleep_calls: list[float] = []
    client = SpotifyClient(
        client_id="x", client_secret="y", sleep_fn=sleep_calls.append,
    )
    client._access_token = "tok"
    client._token_expires_at = 9e18

    class _Headers:
        def get(self, key, default=None):
            if key == "Retry-After":
                return "10"
            return default

    call_count = {"n": 0}

    def fake_urlopen(request, timeout=None):
        call_count["n"] += 1
        if call_count["n"] == 1:
            raise HTTPError(
                url=request.full_url, code=429, msg="rate",
                hdrs=_Headers(), fp=None,
            )
        return FakeResponse({"tracks": {"items": []}})

    with patch("collector.spotify_client.urllib.request.urlopen", fake_urlopen):
        results = client.search_tracks_by_isrc(
            tracks=[{"clouder_track_id": "ct1", "isrc": "ZZ1"}],
            correlation_id="cid-rl",
        )

    assert sleep_calls == [10.0]
    assert results[0].spotify_id is None
    assert call_count["n"] == 2


def test_get_tracks_maps_ids_to_artists() -> None:
    client = _make_client()
    client._ensure_token = MagicMock()  # skip auth
    client._request = MagicMock(return_value={
        "tracks": [
            {"id": "a", "artists": [{"name": "Guri"}, {"name": "Nu Zau"}]},
            {"id": "b", "artists": [{"name": "Solee"}]},
            None,  # unavailable track id
        ]
    })
    out = client.get_tracks(["a", "b", "c"], correlation_id="cid")
    assert out == {"a": ["Guri", "Nu Zau"], "b": ["Solee"]}
    # Batched into one call for ≤50 ids.
    assert client._request.call_count == 1


def test_album_release_sort_key_edge_cases() -> None:
    assert _album_release_sort_key({"album": {"release_date": "2020-01-15"}}) == "2020-01-15"
    assert _album_release_sort_key({"album": {"release_date": "2020-01"}}) == "2020-01-00"
    assert _album_release_sort_key({"album": {"release_date": "2020"}}) == "2020-00-00"
    assert _album_release_sort_key({"album": {}}) == "9999-99-99"
    assert _album_release_sort_key({}) == "9999-99-99"

"""HTTP-shaped unit tests for the user-OAuth Spotify Web API client.

`requests` is stubbed via a simple fake session that records calls and
returns canned responses. No network."""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from collector.curation import (
    SpotifyApiError,
    SpotifyNotAuthorizedError,
    SpotifyRateLimitedError,
    SpotifyScopeInsufficientError,
)
from collector.curation.spotify_user_client import (
    SpotifyPlaylistRef,
    SpotifyTrackPayload,
    SpotifyUserClient,
)


class _Resp:
    def __init__(self, status_code: int, body: dict | None = None,
                 headers: dict | None = None) -> None:
        self.status_code = status_code
        self._body = body or {}
        self.headers = headers or {}

    def json(self) -> dict:
        return self._body


def _client(session: MagicMock, sleep=lambda _s: None) -> SpotifyUserClient:
    return SpotifyUserClient(
        access_token="tok", session=session, sleep=sleep,
    )


def test_get_track_returns_payload() -> None:
    session = MagicMock()
    session.request.return_value = _Resp(200, {
        "id": "spt-abc", "name": "Track A",
        "duration_ms": 180000, "external_ids": {"isrc": "ISRC1"},
        "artists": [{"id": "art-1", "name": "Art One"}],
    })
    client = _client(session)
    track = client.get_track("spt-abc")
    assert isinstance(track, SpotifyTrackPayload)
    assert track.id == "spt-abc"
    assert track.isrc == "ISRC1"
    assert track.artists[0].name == "Art One"


def test_create_playlist_posts_and_returns_ref() -> None:
    session = MagicMock()
    session.request.return_value = _Resp(201, {
        "id": "pl-1",
        "external_urls": {"spotify": "https://open.spotify.com/playlist/pl-1"},
    })
    client = _client(session)
    ref = client.create_playlist(
        user_spotify_id="user-1", name="My Set",
        description="desc", public=False,
    )
    assert isinstance(ref, SpotifyPlaylistRef)
    assert ref.id == "pl-1"
    assert ref.url == "https://open.spotify.com/playlist/pl-1"


def test_429_with_retry_after_retries_then_succeeds() -> None:
    session = MagicMock()
    session.request.side_effect = [
        _Resp(429, headers={"Retry-After": "0"}),
        _Resp(200, {"id": "x", "name": "n", "duration_ms": 0,
                    "external_ids": {}, "artists": []}),
    ]
    slept: list[float] = []
    client = _client(session, sleep=lambda s: slept.append(s))
    client.get_track("x")
    assert slept and slept[0] == 0.0


def test_429_persistent_raises_rate_limited() -> None:
    session = MagicMock()
    session.request.return_value = _Resp(429, headers={"Retry-After": "0"})
    client = _client(session, sleep=lambda _: None)
    with pytest.raises(SpotifyRateLimitedError):
        client.get_track("x")


def test_5xx_retries_once_then_raises() -> None:
    session = MagicMock()
    session.request.side_effect = [
        _Resp(503),
        _Resp(503),
    ]
    client = _client(session, sleep=lambda _: None)
    with pytest.raises(SpotifyApiError):
        client.get_track("x")


def test_401_propagates_as_not_authorized() -> None:
    session = MagicMock()
    session.request.return_value = _Resp(401, {"error": "expired"})
    client = _client(session)
    with pytest.raises(SpotifyNotAuthorizedError):
        client.get_track("x")


def test_404_propagates_as_not_found() -> None:
    from collector.curation import SpotifyNotFoundError
    session = MagicMock()
    session.request.return_value = _Resp(404, {"error": "not found"})
    client = _client(session)
    with pytest.raises(SpotifyNotFoundError):
        client.get_track("x")


def test_403_insufficient_scope_propagates() -> None:
    session = MagicMock()
    session.request.return_value = _Resp(
        403, {"error": {"message": "Insufficient client scope"}},
    )
    client = _client(session)
    with pytest.raises(SpotifyScopeInsufficientError):
        client.set_cover("pl-1", b"jpeg-bytes")


def test_replace_tracks_uses_put() -> None:
    session = MagicMock()
    session.request.return_value = _Resp(200, {})
    client = _client(session)
    client.replace_tracks("pl-1", ["spotify:track:a", "spotify:track:b"])
    _, kwargs = session.request.call_args
    method = kwargs.get("method")
    url = kwargs.get("url")
    assert method == "PUT"
    assert "playlists/pl-1/tracks" in url


def test_append_tracks_uses_post() -> None:
    session = MagicMock()
    session.request.return_value = _Resp(201, {})
    client = _client(session)
    client.append_tracks("pl-1", ["spotify:track:c"])
    _, kwargs = session.request.call_args
    method = kwargs.get("method")
    assert method == "POST"


def test_set_cover_base64_encodes_and_sends() -> None:
    session = MagicMock()
    session.request.return_value = _Resp(202)
    client = _client(session)
    client.set_cover("pl-1", b"\xff\xd8\xff\xe0jpeg-bytes")
    _, kwargs = session.request.call_args
    body = kwargs.get("data")
    assert isinstance(body, (bytes, str))
    # base64-encoded JPEG bytes start with /9j when source is JPEG
    assert b"/9j" in (body if isinstance(body, bytes) else body.encode())

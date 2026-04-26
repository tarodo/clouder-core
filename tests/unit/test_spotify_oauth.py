from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from collector.auth.spotify_oauth import (
    SpotifyOAuthClient,
    SpotifyOAuthError,
    SpotifyProfile,
    SpotifyTokenSet,
    SpotifyTokenRevokedError,
)


class FakeResponse:
    def __init__(self, status: int, body: dict | str) -> None:
        self.status = status
        self._body = body

    def read(self) -> bytes:
        if isinstance(self._body, dict):
            return json.dumps(self._body).encode()
        return self._body.encode()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def test_exchange_code_returns_tokens() -> None:
    captured: dict = {}

    def opener(request, timeout):
        captured["url"] = request.full_url
        captured["data"] = request.data.decode()
        captured["auth"] = request.get_header("Authorization")
        return FakeResponse(
            200,
            {
                "access_token": "AT",
                "refresh_token": "RT",
                "expires_in": 3600,
                "scope": "user-read-email",
            },
        )

    client = SpotifyOAuthClient(
        client_id="cid",
        client_secret="csec",
        redirect_uri="https://x/cb",
        urlopen=opener,
    )

    tokens = client.exchange_code(code="AUTH_CODE", code_verifier="VERIFIER")

    assert isinstance(tokens, SpotifyTokenSet)
    assert tokens.access_token == "AT"
    assert tokens.refresh_token == "RT"
    assert tokens.expires_in == 3600
    assert tokens.scope == "user-read-email"
    assert "code=AUTH_CODE" in captured["data"]
    assert "code_verifier=VERIFIER" in captured["data"]
    assert captured["auth"].startswith("Basic ")


def test_exchange_code_http_error_raises_oauth_exchange_failed() -> None:
    def opener(request, timeout):
        return FakeResponse(400, {"error": "invalid_request"})

    client = SpotifyOAuthClient(
        client_id="cid", client_secret="csec",
        redirect_uri="https://x/cb", urlopen=opener,
    )

    with pytest.raises(SpotifyOAuthError):
        client.exchange_code(code="X", code_verifier="V")


def test_get_me_parses_profile() -> None:
    def opener(request, timeout):
        assert request.full_url == "https://api.spotify.com/v1/me"
        assert request.get_header("Authorization") == "Bearer AT"
        return FakeResponse(
            200,
            {
                "id": "spotify_user_1",
                "display_name": "Roman",
                "email": "r@example.com",
                "product": "premium",
            },
        )

    client = SpotifyOAuthClient(
        client_id="cid", client_secret="csec",
        redirect_uri="https://x/cb", urlopen=opener,
    )

    profile = client.get_me(access_token="AT")

    assert isinstance(profile, SpotifyProfile)
    assert profile.spotify_id == "spotify_user_1"
    assert profile.display_name == "Roman"
    assert profile.email == "r@example.com"
    assert profile.product == "premium"


def test_refresh_invalid_grant_raises_revoked() -> None:
    def opener(request, timeout):
        return FakeResponse(400, {"error": "invalid_grant"})

    client = SpotifyOAuthClient(
        client_id="cid", client_secret="csec",
        redirect_uri="https://x/cb", urlopen=opener,
    )

    with pytest.raises(SpotifyTokenRevokedError):
        client.refresh(refresh_token="OLD")


def test_refresh_returns_new_tokens() -> None:
    def opener(request, timeout):
        return FakeResponse(
            200,
            {
                "access_token": "NEW_AT",
                "expires_in": 3600,
                "scope": "user-read-email",
                # Spotify may or may not return a new refresh_token
            },
        )

    client = SpotifyOAuthClient(
        client_id="cid", client_secret="csec",
        redirect_uri="https://x/cb", urlopen=opener,
    )

    tokens = client.refresh(refresh_token="OLD")

    assert tokens.access_token == "NEW_AT"
    assert tokens.refresh_token == "OLD"  # falls back to the existing refresh
    assert tokens.expires_in == 3600

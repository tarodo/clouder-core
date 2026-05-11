"""Resolver reads + KMS-decrypts user_vendor_tokens.spotify, refreshing
when expiry is within 60s."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest

from collector.curation import SpotifyNotAuthorizedError
from collector.curation.spotify_token_resolver import (
    ResolvedSpotifyToken,
    SpotifyTokenResolver,
)


def _utc(offset_s: int = 0) -> datetime:
    return datetime.now(timezone.utc) + timedelta(seconds=offset_s)


def test_returns_existing_token_when_not_near_expiry() -> None:
    data_api = MagicMock()
    data_api.execute.return_value = [{
        "access_token_enc": b"enc-a",
        "refresh_token_enc": b"enc-r",
        "data_key_enc": b"dk",
        "expires_at": _utc(3600).isoformat(),
    }]
    envelope = MagicMock()
    envelope.decrypt.return_value = b"access-plain"
    oauth = MagicMock()

    resolver = SpotifyTokenResolver(
        data_api=data_api, envelope=envelope, oauth_client=oauth,
    )
    result = resolver.resolve(user_id="u-1")
    assert isinstance(result, ResolvedSpotifyToken)
    assert result.access_token == "access-plain"
    oauth.refresh.assert_not_called()


def test_refreshes_when_within_60s_of_expiry() -> None:
    data_api = MagicMock()
    data_api.execute.return_value = [{
        "access_token_enc": b"enc-a",
        "refresh_token_enc": b"enc-r",
        "data_key_enc": b"dk",
        "expires_at": _utc(30).isoformat(),
    }]
    envelope = MagicMock()
    envelope.decrypt.side_effect = [b"refresh-plain"]
    envelope.encrypt.side_effect = [
        MagicMock(serialize=lambda: b"new-enc-a"),
        MagicMock(serialize=lambda: b"new-enc-r"),
    ]
    oauth = MagicMock()
    new_tokens = MagicMock(
        access_token="new-access", refresh_token="new-refresh",
        expires_in=3600,
    )
    oauth.refresh.return_value = new_tokens

    resolver = SpotifyTokenResolver(
        data_api=data_api, envelope=envelope, oauth_client=oauth,
    )
    result = resolver.resolve(user_id="u-1")
    assert result.access_token == "new-access"
    oauth.refresh.assert_called_once_with(refresh_token="refresh-plain")
    # UPDATE was written
    update_calls = [
        c for c in data_api.execute.call_args_list
        if "UPDATE user_vendor_tokens" in c[0][0]
    ]
    assert len(update_calls) == 1


def test_raises_not_authorized_when_no_token_row() -> None:
    data_api = MagicMock()
    data_api.execute.return_value = []
    resolver = SpotifyTokenResolver(
        data_api=data_api, envelope=MagicMock(), oauth_client=MagicMock(),
    )
    with pytest.raises(SpotifyNotAuthorizedError):
        resolver.resolve(user_id="u-1")


def test_raises_not_authorized_when_refresh_fails() -> None:
    data_api = MagicMock()
    data_api.execute.return_value = [{
        "access_token_enc": b"enc-a",
        "refresh_token_enc": b"enc-r",
        "data_key_enc": b"dk",
        "expires_at": _utc(0).isoformat(),
    }]
    envelope = MagicMock()
    envelope.decrypt.return_value = b"refresh-plain"
    oauth = MagicMock()

    class _Boom(Exception):
        pass

    oauth.refresh.side_effect = _Boom("invalid_grant")

    resolver = SpotifyTokenResolver(
        data_api=data_api, envelope=envelope, oauth_client=oauth,
    )
    with pytest.raises(SpotifyNotAuthorizedError):
        resolver.resolve(user_id="u-1")

"""Resolver reads + KMS-decrypts user_vendor_tokens.spotify, refreshing
when expiry is within 60s."""
from __future__ import annotations

import base64
import struct
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest

from collector.auth.kms_envelope import EnvelopePayload
from collector.curation import SpotifyNotAuthorizedError
from collector.curation.spotify_token_resolver import (
    ResolvedSpotifyToken,
    SpotifyTokenResolver,
)


def _utc(offset_s: int = 0) -> datetime:
    return datetime.now(timezone.utc) + timedelta(seconds=offset_s)


def _fake_payload_blob() -> bytes:
    # 4-byte big-endian length, data_key_enc (1 byte), nonce (12 bytes), ciphertext.
    return struct.pack(">I", 1) + b"K" + (b"N" * 12) + b"CIPHER"


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def test_returns_existing_token_when_not_near_expiry() -> None:
    blob = _fake_payload_blob()
    data_api = MagicMock()
    data_api.execute.return_value = [{
        "access_token_enc": _b64(blob),
        "refresh_token_enc": _b64(blob),
        "data_key_enc": _b64(b"dk"),
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
    # decrypt was called with a deserialized EnvelopePayload, not raw bytes.
    args, _ = envelope.decrypt.call_args
    assert isinstance(args[0], EnvelopePayload)


def test_refreshes_when_within_60s_of_expiry() -> None:
    blob = _fake_payload_blob()
    data_api = MagicMock()
    data_api.execute.return_value = [{
        "access_token_enc": _b64(blob),
        "refresh_token_enc": _b64(blob),
        "data_key_enc": _b64(b"dk"),
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
    # decrypt got a deserialized EnvelopePayload (not raw bytes).
    args, _ = envelope.decrypt.call_args
    assert isinstance(args[0], EnvelopePayload)
    # UPDATE was written
    update_calls = [
        c for c in data_api.execute.call_args_list
        if "UPDATE user_vendor_tokens" in c[0][0]
    ]
    assert len(update_calls) == 1
    upd_params = update_calls[0][0][1]
    assert set(upd_params.keys()) == {
        "user_id", "access_enc", "refresh_enc", "expires_at", "updated_at"
    }
    # base64-strings, not raw bytes
    assert isinstance(upd_params["access_enc"], str)
    assert isinstance(upd_params["refresh_enc"], str)
    assert base64.b64decode(upd_params["access_enc"]) == b"new-enc-a"
    assert base64.b64decode(upd_params["refresh_enc"]) == b"new-enc-r"


def test_raises_not_authorized_when_no_token_row() -> None:
    data_api = MagicMock()
    data_api.execute.return_value = []
    resolver = SpotifyTokenResolver(
        data_api=data_api, envelope=MagicMock(), oauth_client=MagicMock(),
    )
    with pytest.raises(SpotifyNotAuthorizedError):
        resolver.resolve(user_id="u-1")


def test_raises_not_authorized_when_refresh_fails() -> None:
    blob = _fake_payload_blob()
    data_api = MagicMock()
    data_api.execute.return_value = [{
        "access_token_enc": _b64(blob),
        "refresh_token_enc": _b64(blob),
        "data_key_enc": _b64(b"dk"),
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

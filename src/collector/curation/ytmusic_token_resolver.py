"""Read + KMS-decrypt + refresh the user's YouTube Music OAuth token.

Storage shape comes from user_vendor_tokens (vendor='ytmusic'). Returns a
ytmusicapi-compatible token dict (with a fresh access token + epoch
expires_at) used to build an authenticated YTMusic client.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Protocol

from collector.auth.kms_envelope import EnvelopePayload, KmsEnvelope
from collector.data_api import DataAPIClient
from collector.logging_utils import log_event

from . import YtmusicNotAuthorizedError

_REFRESH_LEEWAY_SECONDS = 60
_SCOPE = "https://www.googleapis.com/auth/youtube"


def _b64e(value: bytes) -> str:
    return base64.b64encode(value).decode("ascii")


def _b64d(value: Any) -> bytes:
    if isinstance(value, bytes):
        return value
    if value is None:
        return b""
    return base64.b64decode(value)


def _parse_expires_at(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    s = str(value).replace(" ", "T")
    if "+" not in s and "Z" not in s:
        s = s + "+00:00"
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


@dataclass(frozen=True)
class ResolvedYtmusicToken:
    user_id: str
    token_dict: dict
    refreshed: bool


class _OAuthClientLike(Protocol):
    def refresh(self, *, refresh_token: str) -> Any: ...


class YtmusicTokenResolver:
    def __init__(
        self,
        *,
        data_api: DataAPIClient,
        envelope: KmsEnvelope,
        oauth_client: _OAuthClientLike,
    ) -> None:
        self._data_api = data_api
        self._envelope = envelope
        self._oauth = oauth_client

    def resolve(self, *, user_id: str) -> ResolvedYtmusicToken:
        rows = self._data_api.execute(
            """
            SELECT
                encode(access_token_enc, 'base64')  AS access_token_enc,
                encode(refresh_token_enc, 'base64') AS refresh_token_enc,
                encode(data_key_enc, 'base64')      AS data_key_enc,
                expires_at
            FROM user_vendor_tokens
            WHERE user_id = :user_id AND vendor = 'ytmusic'
            """,
            {"user_id": user_id},
        )
        if not rows:
            raise YtmusicNotAuthorizedError(
                f"No YouTube Music token on file for user {user_id}"
            )
        row = rows[0]
        expires_at = _parse_expires_at(row["expires_at"])
        now = datetime.now(timezone.utc)

        refresh_plain = self._envelope.decrypt(
            EnvelopePayload.deserialize(_b64d(row["refresh_token_enc"]))
        ).decode("utf-8")

        if (expires_at - now).total_seconds() > _REFRESH_LEEWAY_SECONDS:
            access_plain = self._envelope.decrypt(
                EnvelopePayload.deserialize(_b64d(row["access_token_enc"]))
            ).decode("utf-8")
            return ResolvedYtmusicToken(
                user_id=user_id,
                token_dict=self._token_dict(access_plain, refresh_plain, expires_at),
                refreshed=False,
            )

        # Refresh via Google.
        try:
            new_tokens = self._oauth.refresh(refresh_token=refresh_plain)
        except Exception as exc:
            raise YtmusicNotAuthorizedError("YouTube Music refresh failed") from exc

        new_expires = now + timedelta(seconds=int(round(new_tokens.expires_in)))
        access_payload_new = self._envelope.encrypt(
            new_tokens.access_token.encode("utf-8")
        )
        refresh_payload_new = self._envelope.encrypt(
            new_tokens.refresh_token.encode("utf-8")
        )
        self._data_api.execute(
            """
            UPDATE user_vendor_tokens SET
                access_token_enc = decode(:access_enc, 'base64'),
                refresh_token_enc = decode(:refresh_enc, 'base64'),
                expires_at = :expires_at,
                updated_at = :updated_at
            WHERE user_id = :user_id AND vendor = 'ytmusic'
            """,
            {
                "user_id": user_id,
                "access_enc": _b64e(access_payload_new.serialize()),
                "refresh_enc": _b64e(refresh_payload_new.serialize()),
                "expires_at": new_expires,
                "updated_at": now,
            },
        )
        log_event("INFO", "ytmusic_publish_token_refreshed", user_id=user_id)
        return ResolvedYtmusicToken(
            user_id=user_id,
            token_dict=self._token_dict(
                new_tokens.access_token, new_tokens.refresh_token, new_expires
            ),
            refreshed=True,
        )

    @staticmethod
    def _token_dict(
        access_token: str, refresh_token: str, expires_at: datetime
    ) -> dict:
        # ytmusicapi recognises an OAuth token only when the dict carries ALL of
        # Token.members() — scope, token_type, access_token, refresh_token,
        # expires_at AND expires_in (ytmusicapi.auth.oauth.token.OAuthToken.is_oauth).
        # Omit expires_in and ytmusicapi falls back to browser-header auth: the
        # dict keys are sent as raw HTTP headers, the request reaches YT Music
        # with no valid Authorization, and writes fail with HTTP 400
        # "Request contains an invalid argument".
        now = datetime.now(timezone.utc)
        expires_in = max(0, int((expires_at - now).total_seconds()))
        return {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "scope": _SCOPE,
            "token_type": "Bearer",
            "expires_at": int(expires_at.timestamp()),
            "expires_in": expires_in,
        }

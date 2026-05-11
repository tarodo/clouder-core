"""Read + KMS-decrypt + refresh the user's Spotify OAuth access token.

Storage shape comes from auth_repository / user_vendor_tokens (vendor='spotify').
This module is *only* the read+refresh path used at playlist publish/import
time. Initial OAuth + replay protection still lives in auth_handler.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Protocol

from collector.auth.kms_envelope import KmsEnvelope
from collector.data_api import DataAPIClient
from collector.logging_utils import log_event

from . import SpotifyNotAuthorizedError


_REFRESH_LEEWAY_SECONDS = 60


@dataclass(frozen=True)
class ResolvedSpotifyToken:
    user_id: str
    access_token: str
    refreshed: bool


class _OAuthClientLike(Protocol):
    def refresh(self, *, refresh_token: str) -> Any: ...


def _parse_expires_at(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    s = str(value).replace(" ", "T")
    if "+" not in s and "Z" not in s:
        s = s + "+00:00"
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


class SpotifyTokenResolver:
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

    def resolve(self, *, user_id: str) -> ResolvedSpotifyToken:
        rows = self._data_api.execute(
            """
            SELECT access_token_enc, refresh_token_enc,
                   data_key_enc, expires_at
            FROM user_vendor_tokens
            WHERE user_id = :user_id AND vendor = 'spotify'
            """,
            {"user_id": user_id},
        )
        if not rows:
            raise SpotifyNotAuthorizedError(
                f"No Spotify token on file for user {user_id}"
            )
        row = rows[0]
        expires_at = _parse_expires_at(row["expires_at"])
        now = datetime.now(timezone.utc)

        if (expires_at - now).total_seconds() > _REFRESH_LEEWAY_SECONDS:
            plain = self._envelope.decrypt(row["access_token_enc"])
            return ResolvedSpotifyToken(
                user_id=user_id,
                access_token=plain.decode("utf-8"),
                refreshed=False,
            )

        # Refresh path.
        try:
            refresh_plain = self._envelope.decrypt(
                row["refresh_token_enc"]
            ).decode("utf-8")
            new_tokens = self._oauth.refresh(refresh_token=refresh_plain)
        except Exception as exc:
            raise SpotifyNotAuthorizedError(
                "Spotify refresh failed"
            ) from exc

        access_payload = self._envelope.encrypt(
            new_tokens.access_token.encode("utf-8")
        )
        refresh_payload = self._envelope.encrypt(
            new_tokens.refresh_token.encode("utf-8")
        )
        new_expires = now + timedelta(seconds=int(new_tokens.expires_in))

        self._data_api.execute(
            """
            UPDATE user_vendor_tokens SET
                access_token_enc = :access_enc,
                refresh_token_enc = :refresh_enc,
                expires_at = :expires_at,
                updated_at = :updated_at
            WHERE user_id = :user_id AND vendor = 'spotify'
            """,
            {
                "user_id": user_id,
                "access_enc": access_payload.serialize(),
                "refresh_enc": refresh_payload.serialize(),
                "expires_at": new_expires,
                "updated_at": now,
            },
        )
        log_event(
            "INFO",
            "playlist_publish_token_refreshed",
            user_id=user_id,
        )
        return ResolvedSpotifyToken(
            user_id=user_id,
            access_token=new_tokens.access_token,
            refreshed=True,
        )

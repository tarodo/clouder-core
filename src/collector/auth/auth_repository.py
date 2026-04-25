"""Aurora Data API repository for users / sessions / vendor tokens.

Bytea columns must round-trip through the Data API stringValue field. We
base64-encode bytes on the way in and decode on the way out — Data API does
not natively support BYTEA parameters.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Mapping

from collector.data_api import DataAPIClient


@dataclass(frozen=True)
class UserRow:
    id: str
    spotify_id: str
    display_name: str | None
    email: str | None
    is_admin: bool
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class SessionRow:
    id: str
    user_id: str
    refresh_token_hash: str
    user_agent: str | None
    ip_address: str | None
    created_at: str
    last_used_at: str
    expires_at: str
    revoked_at: str | None


@dataclass(frozen=True)
class VendorTokenRow:
    user_id: str
    vendor: str
    access_token_enc: bytes
    refresh_token_enc: bytes | None
    data_key_enc: bytes
    scope: str | None
    expires_at: str | None
    updated_at: str


@dataclass(frozen=True)
class UpsertUserCmd:
    id: str
    spotify_id: str
    display_name: str | None
    email: str | None
    is_admin: bool
    now: datetime


@dataclass(frozen=True)
class UpsertVendorTokenCmd:
    user_id: str
    vendor: str
    access_token_enc: bytes
    refresh_token_enc: bytes | None
    data_key_enc: bytes
    scope: str | None
    expires_at: datetime | None
    updated_at: datetime


def _b64e(value: bytes | None) -> str | None:
    if value is None:
        return None
    return base64.b64encode(value).decode("ascii")


def _b64d(value: Any) -> bytes:
    if isinstance(value, bytes):
        return value
    if value is None:
        return b""
    return base64.b64decode(value)


def _b64d_optional(value: Any) -> bytes | None:
    if value is None:
        return None
    return _b64d(value)


class AuthRepository:
    def __init__(self, *, data_api: DataAPIClient) -> None:
        self._data_api = data_api

    # ── users ────────────────────────────────────────────────────────

    def upsert_user(self, cmd: UpsertUserCmd) -> None:
        self._data_api.execute(
            """
            INSERT INTO users (
                id, spotify_id, display_name, email, is_admin,
                created_at, updated_at
            ) VALUES (
                :id, :spotify_id, :display_name, :email, :is_admin,
                :now, :now
            )
            ON CONFLICT (spotify_id) DO UPDATE SET
                display_name = EXCLUDED.display_name,
                email = EXCLUDED.email,
                is_admin = EXCLUDED.is_admin,
                updated_at = EXCLUDED.updated_at
            """,
            {
                "id": cmd.id,
                "spotify_id": cmd.spotify_id,
                "display_name": cmd.display_name,
                "email": cmd.email,
                "is_admin": cmd.is_admin,
                "now": cmd.now,
            },
        )

    def get_user_by_spotify_id(self, spotify_id: str) -> UserRow | None:
        rows = self._data_api.execute(
            """
            SELECT id, spotify_id, display_name, email, is_admin,
                   created_at, updated_at
            FROM users
            WHERE spotify_id = :spotify_id
            """,
            {"spotify_id": spotify_id},
        )
        return _to_user_row(rows[0]) if rows else None

    def get_user_by_id(self, user_id: str) -> UserRow | None:
        rows = self._data_api.execute(
            """
            SELECT id, spotify_id, display_name, email, is_admin,
                   created_at, updated_at
            FROM users
            WHERE id = :id
            """,
            {"id": user_id},
        )
        return _to_user_row(rows[0]) if rows else None

    # ── sessions ─────────────────────────────────────────────────────

    def create_session(
        self,
        *,
        session_id: str,
        user_id: str,
        refresh_token_hash: str,
        user_agent: str | None,
        ip_address: str | None,
        created_at: datetime,
        expires_at: datetime,
    ) -> None:
        self._data_api.execute(
            """
            INSERT INTO user_sessions (
                id, user_id, refresh_token_hash, user_agent, ip_address,
                created_at, last_used_at, expires_at
            ) VALUES (
                :id, :user_id, :refresh_token_hash, :user_agent, :ip_address,
                :created_at, :created_at, :expires_at
            )
            """,
            {
                "id": session_id,
                "user_id": user_id,
                "refresh_token_hash": refresh_token_hash,
                "user_agent": user_agent,
                "ip_address": ip_address,
                "created_at": created_at,
                "expires_at": expires_at,
            },
        )

    def get_active_session(
        self, session_id: str, *, now: datetime
    ) -> SessionRow | None:
        rows = self._data_api.execute(
            """
            SELECT id, user_id, refresh_token_hash, user_agent, ip_address,
                   created_at, last_used_at, expires_at, revoked_at
            FROM user_sessions
            WHERE id = :id
              AND revoked_at IS NULL
              AND expires_at > :now
            """,
            {"id": session_id, "now": now},
        )
        return _to_session_row(rows[0]) if rows else None

    def rotate_session(
        self, *, session_id: str, new_hash: str, last_used_at: datetime
    ) -> None:
        self._data_api.execute(
            """
            UPDATE user_sessions
            SET refresh_token_hash = :hash,
                last_used_at = :last_used_at
            WHERE id = :id
            """,
            {"id": session_id, "hash": new_hash, "last_used_at": last_used_at},
        )

    def revoke_session(self, session_id: str, *, revoked_at: datetime) -> None:
        self._data_api.execute(
            """
            UPDATE user_sessions
            SET revoked_at = :revoked_at
            WHERE id = :id AND revoked_at IS NULL
            """,
            {"id": session_id, "revoked_at": revoked_at},
        )

    def revoke_all_user_sessions(
        self, user_id: str, *, revoked_at: datetime
    ) -> None:
        self._data_api.execute(
            """
            UPDATE user_sessions
            SET revoked_at = :revoked_at
            WHERE user_id = :user_id AND revoked_at IS NULL
            """,
            {"user_id": user_id, "revoked_at": revoked_at},
        )

    def list_active_sessions(
        self, *, user_id: str, now: datetime
    ) -> list[SessionRow]:
        rows = self._data_api.execute(
            """
            SELECT id, user_id, refresh_token_hash, user_agent, ip_address,
                   created_at, last_used_at, expires_at, revoked_at
            FROM user_sessions
            WHERE user_id = :user_id
              AND revoked_at IS NULL
              AND expires_at > :now
            ORDER BY last_used_at DESC
            """,
            {"user_id": user_id, "now": now},
        )
        return [_to_session_row(row) for row in rows]

    # ── vendor tokens ────────────────────────────────────────────────

    def upsert_vendor_token(self, cmd: UpsertVendorTokenCmd) -> None:
        self._data_api.execute(
            """
            INSERT INTO user_vendor_tokens (
                user_id, vendor, access_token_enc, refresh_token_enc,
                data_key_enc, scope, expires_at, updated_at
            ) VALUES (
                :user_id, :vendor,
                decode(:access_token_enc, 'base64'),
                decode(:refresh_token_enc, 'base64'),
                decode(:data_key_enc, 'base64'),
                :scope, :expires_at, :updated_at
            )
            ON CONFLICT (user_id, vendor) DO UPDATE SET
                access_token_enc = EXCLUDED.access_token_enc,
                refresh_token_enc = EXCLUDED.refresh_token_enc,
                data_key_enc = EXCLUDED.data_key_enc,
                scope = EXCLUDED.scope,
                expires_at = EXCLUDED.expires_at,
                updated_at = EXCLUDED.updated_at
            """,
            {
                "user_id": cmd.user_id,
                "vendor": cmd.vendor,
                "access_token_enc": _b64e(cmd.access_token_enc),
                "refresh_token_enc": _b64e(cmd.refresh_token_enc),
                "data_key_enc": _b64e(cmd.data_key_enc),
                "scope": cmd.scope,
                "expires_at": cmd.expires_at,
                "updated_at": cmd.updated_at,
            },
        )

    def get_vendor_token(
        self, *, user_id: str, vendor: str
    ) -> VendorTokenRow | None:
        rows = self._data_api.execute(
            """
            SELECT user_id, vendor,
                   encode(access_token_enc, 'base64')  AS access_token_enc,
                   encode(refresh_token_enc, 'base64') AS refresh_token_enc,
                   encode(data_key_enc, 'base64')      AS data_key_enc,
                   scope, expires_at, updated_at
            FROM user_vendor_tokens
            WHERE user_id = :user_id AND vendor = :vendor
            """,
            {"user_id": user_id, "vendor": vendor},
        )
        return _to_vendor_token_row(rows[0]) if rows else None

    def delete_vendor_token(self, *, user_id: str, vendor: str) -> None:
        self._data_api.execute(
            """
            DELETE FROM user_vendor_tokens
            WHERE user_id = :user_id AND vendor = :vendor
            """,
            {"user_id": user_id, "vendor": vendor},
        )


def _to_user_row(row: Mapping[str, Any]) -> UserRow:
    return UserRow(
        id=str(row["id"]),
        spotify_id=str(row["spotify_id"]),
        display_name=row.get("display_name"),
        email=row.get("email"),
        is_admin=bool(row.get("is_admin", False)),
        created_at=str(row["created_at"]),
        updated_at=str(row["updated_at"]),
    )


def _to_session_row(row: Mapping[str, Any]) -> SessionRow:
    return SessionRow(
        id=str(row["id"]),
        user_id=str(row["user_id"]),
        refresh_token_hash=str(row["refresh_token_hash"]),
        user_agent=row.get("user_agent"),
        ip_address=row.get("ip_address"),
        created_at=str(row["created_at"]),
        last_used_at=str(row["last_used_at"]),
        expires_at=str(row["expires_at"]),
        revoked_at=row.get("revoked_at"),
    )


def _to_vendor_token_row(row: Mapping[str, Any]) -> VendorTokenRow:
    return VendorTokenRow(
        user_id=str(row["user_id"]),
        vendor=str(row["vendor"]),
        access_token_enc=_b64d(row["access_token_enc"]),
        refresh_token_enc=_b64d_optional(row.get("refresh_token_enc")),
        data_key_enc=_b64d(row["data_key_enc"]),
        scope=row.get("scope"),
        expires_at=row.get("expires_at"),
        updated_at=str(row["updated_at"]),
    )

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock

from collector.auth.auth_repository import (
    AuthRepository,
    SessionRow,
    UpsertUserCmd,
    UpsertVendorTokenCmd,
    UserRow,
    VendorTokenRow,
)


def _make() -> tuple[AuthRepository, MagicMock]:
    data_api = MagicMock()
    return AuthRepository(data_api=data_api), data_api


def test_upsert_user_emits_insert_on_conflict() -> None:
    repo, data_api = _make()
    now = datetime(2026, 4, 26, 12, 0, tzinfo=timezone.utc)

    repo.upsert_user(
        UpsertUserCmd(
            id="u-1",
            spotify_id="sp-1",
            display_name="Roman",
            email="r@x",
            is_admin=True,
            now=now,
        )
    )

    sql = data_api.execute.call_args.args[0]
    params = data_api.execute.call_args.args[1]
    assert "INSERT INTO users" in sql
    assert "ON CONFLICT (spotify_id) DO UPDATE SET" in sql
    assert params["spotify_id"] == "sp-1"
    assert params["is_admin"] is True


def test_get_user_by_spotify_id_returns_user_row() -> None:
    repo, data_api = _make()
    now = datetime(2026, 4, 26, 12, 0, tzinfo=timezone.utc)
    data_api.execute.return_value = [
        {
            "id": "u-1",
            "spotify_id": "sp-1",
            "display_name": "Roman",
            "email": "r@x",
            "is_admin": True,
            "created_at": now.isoformat(),
            "updated_at": now.isoformat(),
        }
    ]

    user = repo.get_user_by_spotify_id("sp-1")
    assert isinstance(user, UserRow)
    assert user.id == "u-1"
    assert user.is_admin is True


def test_create_session_inserts_row() -> None:
    repo, data_api = _make()
    now = datetime(2026, 4, 26, 12, 0, tzinfo=timezone.utc)

    repo.create_session(
        session_id="s-1",
        user_id="u-1",
        refresh_token_hash="hash",
        user_agent="ua",
        ip_address="1.2.3.4",
        created_at=now,
        expires_at=now,
    )

    sql = data_api.execute.call_args.args[0]
    params = data_api.execute.call_args.args[1]
    assert "INSERT INTO user_sessions" in sql
    assert params["id"] == "s-1"
    assert params["refresh_token_hash"] == "hash"


def test_get_active_session_filters_by_revoked_and_expiry() -> None:
    repo, data_api = _make()
    now = datetime(2026, 4, 26, 12, 0, tzinfo=timezone.utc)
    data_api.execute.return_value = [
        {
            "id": "s-1",
            "user_id": "u-1",
            "refresh_token_hash": "h1",
            "user_agent": "ua",
            "ip_address": "1.2.3.4",
            "created_at": now.isoformat(),
            "last_used_at": now.isoformat(),
            "expires_at": now.isoformat(),
            "revoked_at": None,
        }
    ]

    session = repo.get_active_session("s-1", now=now)

    assert isinstance(session, SessionRow)
    assert session.id == "s-1"
    sql = data_api.execute.call_args.args[0]
    assert "revoked_at IS NULL" in sql
    assert "expires_at > :now" in sql


def test_rotate_session_updates_hash_and_last_used() -> None:
    repo, data_api = _make()
    now = datetime(2026, 4, 26, 12, 0, tzinfo=timezone.utc)

    repo.rotate_session(
        session_id="s-1", new_hash="h2", last_used_at=now
    )

    sql = data_api.execute.call_args.args[0]
    params = data_api.execute.call_args.args[1]
    assert "UPDATE user_sessions" in sql
    assert "SET refresh_token_hash = :hash" in sql
    assert params["id"] == "s-1"
    assert params["hash"] == "h2"


def test_revoke_session_sets_revoked_at() -> None:
    repo, data_api = _make()
    now = datetime(2026, 4, 26, 12, 0, tzinfo=timezone.utc)

    repo.revoke_session("s-1", revoked_at=now)

    sql = data_api.execute.call_args.args[0]
    assert "UPDATE user_sessions" in sql
    assert "SET revoked_at = :revoked_at" in sql


def test_revoke_all_sessions_for_user() -> None:
    repo, data_api = _make()
    now = datetime(2026, 4, 26, 12, 0, tzinfo=timezone.utc)

    repo.revoke_all_user_sessions("u-1", revoked_at=now)

    sql = data_api.execute.call_args.args[0]
    assert "WHERE user_id = :user_id" in sql
    assert "revoked_at IS NULL" in sql


def test_list_user_sessions_returns_active_only() -> None:
    repo, data_api = _make()
    now = datetime(2026, 4, 26, 12, 0, tzinfo=timezone.utc)
    data_api.execute.return_value = []

    repo.list_active_sessions(user_id="u-1", now=now)

    sql = data_api.execute.call_args.args[0]
    assert "WHERE user_id = :user_id" in sql
    assert "revoked_at IS NULL" in sql
    assert "expires_at > :now" in sql


def test_upsert_vendor_token_serializes_bytes() -> None:
    repo, data_api = _make()
    now = datetime(2026, 4, 26, 12, 0, tzinfo=timezone.utc)

    repo.upsert_vendor_token(
        UpsertVendorTokenCmd(
            user_id="u-1",
            vendor="spotify",
            access_token_enc=b"\x01\x02",
            refresh_token_enc=b"\x03\x04",
            data_key_enc=b"\x05",
            scope="user-read-email",
            expires_at=now,
            updated_at=now,
        )
    )

    sql = data_api.execute.call_args.args[0]
    params = data_api.execute.call_args.args[1]
    assert "INSERT INTO user_vendor_tokens" in sql
    assert "ON CONFLICT (user_id, vendor) DO UPDATE SET" in sql
    # Bytes are base64-encoded for the Data API stringValue serializer.
    assert isinstance(params["access_token_enc"], str)
    assert isinstance(params["data_key_enc"], str)


def test_get_vendor_token_decodes_bytes() -> None:
    import base64

    repo, data_api = _make()
    now = datetime(2026, 4, 26, 12, 0, tzinfo=timezone.utc)
    data_api.execute.return_value = [
        {
            "user_id": "u-1",
            "vendor": "spotify",
            "access_token_enc": base64.b64encode(b"\x01\x02").decode(),
            "refresh_token_enc": base64.b64encode(b"\x03\x04").decode(),
            "data_key_enc": base64.b64encode(b"\x05").decode(),
            "scope": "user-read-email",
            "expires_at": now.isoformat(),
            "updated_at": now.isoformat(),
        }
    ]

    row = repo.get_vendor_token(user_id="u-1", vendor="spotify")
    assert isinstance(row, VendorTokenRow)
    assert row.access_token_enc == b"\x01\x02"
    assert row.refresh_token_enc == b"\x03\x04"
    assert row.data_key_enc == b"\x05"


def test_delete_vendor_token() -> None:
    repo, _ = _make()

    repo.delete_vendor_token(user_id="u-1", vendor="spotify")

    sql = repo._data_api.execute.call_args.args[0]
    assert "DELETE FROM user_vendor_tokens" in sql

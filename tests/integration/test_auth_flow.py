"""End-to-end auth flow with in-memory fakes for KMS, OAuth, repo."""

from __future__ import annotations

import hashlib
import json
import urllib.parse
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from collector import auth_handler
from collector.auth import auth_settings
from collector.auth.auth_repository import (
    SessionRow,
    UpsertUserCmd,
    UpsertVendorTokenCmd,
    UserRow,
    VendorTokenRow,
)
from collector.auth.kms_envelope import EnvelopePayload
from collector.auth.spotify_oauth import (
    SpotifyProfile,
    SpotifyTokenSet,
)


SECRET = "0" * 32


class FakeKms:
    """In-memory KMS envelope: identity-encrypts. Sufficient to verify wiring."""

    def encrypt(self, plaintext: bytes) -> EnvelopePayload:
        return EnvelopePayload(data_key_enc=b"DK", nonce=b"\x00" * 12, ciphertext=plaintext)

    def decrypt(self, payload: EnvelopePayload) -> bytes:
        return payload.ciphertext


class FakeOAuth:
    def __init__(self) -> None:
        self.refresh_calls = 0

    def authorize_url(self, *, state, code_challenge, scopes):  # not used here
        return "https://accounts.spotify.com/authorize"

    def exchange_code(self, *, code, code_verifier):
        return SpotifyTokenSet(
            access_token="AT-1", refresh_token="RT-1",
            expires_in=3600, scope="user-read-email",
        )

    def get_me(self, *, access_token):
        return SpotifyProfile(
            spotify_id="sp-user", display_name="Roman",
            email="r@x", product="premium",
        )

    def refresh(self, *, refresh_token):
        self.refresh_calls += 1
        return SpotifyTokenSet(
            access_token=f"AT-{self.refresh_calls + 1}",
            refresh_token=f"RT-{self.refresh_calls + 1}",
            expires_in=3600, scope=None,
        )


class FakeRepo:
    def __init__(self) -> None:
        self.users: dict[str, UserRow] = {}
        self.users_by_spotify: dict[str, UserRow] = {}
        self.sessions: dict[str, SessionRow] = {}
        self.vendor_tokens: dict[tuple[str, str], VendorTokenRow] = {}

    def upsert_user(self, cmd: UpsertUserCmd) -> None:
        row = UserRow(
            id=cmd.id, spotify_id=cmd.spotify_id,
            display_name=cmd.display_name, email=cmd.email,
            is_admin=cmd.is_admin,
            created_at=cmd.now.isoformat(), updated_at=cmd.now.isoformat(),
        )
        self.users[row.id] = row
        self.users_by_spotify[row.spotify_id] = row

    def get_user_by_spotify_id(self, spotify_id):
        return self.users_by_spotify.get(spotify_id)

    def get_user_by_id(self, user_id):
        return self.users.get(user_id)

    def create_session(self, *, session_id, user_id, refresh_token_hash,
                       user_agent, ip_address, created_at, expires_at):
        self.sessions[session_id] = SessionRow(
            id=session_id, user_id=user_id,
            refresh_token_hash=refresh_token_hash,
            user_agent=user_agent, ip_address=ip_address,
            created_at=created_at.isoformat(),
            last_used_at=created_at.isoformat(),
            expires_at=expires_at.isoformat(),
            revoked_at=None,
        )

    def get_active_session(self, session_id, *, now):
        s = self.sessions.get(session_id)
        if s is None or s.revoked_at is not None:
            return None
        return s

    def rotate_session(self, *, session_id, new_hash, last_used_at):
        s = self.sessions[session_id]
        self.sessions[session_id] = SessionRow(
            id=s.id, user_id=s.user_id,
            refresh_token_hash=new_hash,
            user_agent=s.user_agent, ip_address=s.ip_address,
            created_at=s.created_at,
            last_used_at=last_used_at.isoformat(),
            expires_at=s.expires_at,
            revoked_at=None,
        )

    def revoke_session(self, session_id, *, revoked_at):
        s = self.sessions.get(session_id)
        if s is None:
            return
        self.sessions[session_id] = SessionRow(
            **{**s.__dict__, "revoked_at": revoked_at.isoformat()},
        )

    def revoke_all_user_sessions(self, user_id, *, revoked_at):
        for sid, s in list(self.sessions.items()):
            if s.user_id == user_id and s.revoked_at is None:
                self.revoke_session(sid, revoked_at=revoked_at)

    def list_active_sessions(self, *, user_id, now):
        return [s for s in self.sessions.values()
                if s.user_id == user_id and s.revoked_at is None]

    def upsert_vendor_token(self, cmd: UpsertVendorTokenCmd) -> None:
        self.vendor_tokens[(cmd.user_id, cmd.vendor)] = VendorTokenRow(
            user_id=cmd.user_id, vendor=cmd.vendor,
            access_token_enc=cmd.access_token_enc,
            refresh_token_enc=cmd.refresh_token_enc,
            data_key_enc=cmd.data_key_enc, scope=cmd.scope,
            expires_at=cmd.expires_at.isoformat() if cmd.expires_at else None,
            updated_at=cmd.updated_at.isoformat(),
        )

    def get_vendor_token(self, *, user_id, vendor):
        return self.vendor_tokens.get((user_id, vendor))

    def delete_vendor_token(self, *, user_id, vendor):
        self.vendor_tokens.pop((user_id, vendor), None)


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("KMS_USER_TOKENS_KEY_ARN", "arn:k")
    monkeypatch.setenv("SPOTIFY_OAUTH_REDIRECT_URI", "https://app.x/auth/callback")
    monkeypatch.setenv("ALLOWED_FRONTEND_REDIRECTS", "/, /dashboard")
    monkeypatch.setenv("ADMIN_SPOTIFY_IDS", "")
    monkeypatch.setenv("SPOTIFY_OAUTH_CLIENT_ID", "cid")
    monkeypatch.setenv("SPOTIFY_OAUTH_CLIENT_SECRET", "csec")
    monkeypatch.setenv("JWT_SIGNING_KEY", SECRET)
    monkeypatch.setenv("JWT_REFRESH_TOKEN_TTL_SECONDS", "604800")
    monkeypatch.setenv("JWT_ACCESS_TOKEN_TTL_SECONDS", "1800")
    auth_settings.reset_auth_settings_cache()
    yield
    auth_settings.reset_auth_settings_cache()


def _wire(monkeypatch, *, repo, oauth, kms, now):
    monkeypatch.setattr(auth_handler, "_build_auth_repository", lambda: repo)
    monkeypatch.setattr(auth_handler, "_build_oauth_client", lambda: oauth)
    monkeypatch.setattr(auth_handler, "_build_kms_envelope", lambda: kms)
    monkeypatch.setattr(auth_handler, "_now", lambda: now)


def _ctx() -> SimpleNamespace:
    return SimpleNamespace(aws_request_id="L")


def test_full_login_to_logout_flow(monkeypatch) -> None:
    now = datetime(2026, 4, 26, 12, 0, tzinfo=timezone.utc)
    repo = FakeRepo()
    oauth = FakeOAuth()
    kms = FakeKms()
    _wire(monkeypatch, repo=repo, oauth=oauth, kms=kms, now=now)

    # 1. /auth/login
    login_response = auth_handler.lambda_handler(
        {
            "version": "2.0",
            "requestContext": {"requestId": "1", "routeKey": "GET /auth/login"},
            "headers": {"x-correlation-id": "cid"},
            "body": None,
        },
        _ctx(),
    )
    assert login_response["statusCode"] == 302
    state_cookie = next(c for c in login_response["cookies"] if c.startswith("oauth_state="))
    state = state_cookie.split("=", 1)[1].split(";")[0]
    verifier_cookie = next(c for c in login_response["cookies"] if c.startswith("oauth_verifier="))
    verifier = verifier_cookie.split("=", 1)[1].split(";")[0]

    # 2. /auth/callback
    callback_response = auth_handler.lambda_handler(
        {
            "version": "2.0",
            "requestContext": {"requestId": "2", "routeKey": "GET /auth/callback"},
            "headers": {"x-correlation-id": "cid"},
            "queryStringParameters": {"code": "AUTHCODE", "state": state},
            "cookies": [
                f"oauth_state={state}",
                f"oauth_verifier={verifier}",
            ],
            "body": None,
        },
        _ctx(),
    )
    assert callback_response["statusCode"] == 200
    body = json.loads(callback_response["body"])
    access_token = body["access_token"]
    refresh_cookie = next(c for c in callback_response["cookies"] if c.startswith("refresh_token="))
    refresh_token = refresh_cookie.split("=", 1)[1].split(";")[0]
    assert len(repo.users) == 1
    user_id = next(iter(repo.users))
    assert ("sp-user", ) == (repo.users[user_id].spotify_id, )

    # 3. GET /me (simulate authorizer context)
    me_response = auth_handler.lambda_handler(
        {
            "version": "2.0",
            "requestContext": {
                "requestId": "3",
                "routeKey": "GET /me",
                "authorizer": {
                    "lambda": {
                        "user_id": user_id,
                        "session_id": next(iter(repo.sessions)),
                        "is_admin": False,
                    }
                },
            },
            "headers": {"x-correlation-id": "cid", "authorization": f"Bearer {access_token}"},
            "body": None,
        },
        _ctx(),
    )
    assert me_response["statusCode"] == 200
    me_body = json.loads(me_response["body"])
    assert me_body["spotify_id"] == "sp-user"
    assert len(me_body["sessions"]) == 1
    assert me_body["sessions"][0]["current"] is True

    # 4. POST /auth/refresh
    refresh_response = auth_handler.lambda_handler(
        {
            "version": "2.0",
            "requestContext": {"requestId": "4", "routeKey": "POST /auth/refresh"},
            "headers": {"x-correlation-id": "cid"},
            "cookies": [f"refresh_token={refresh_token}"],
            "body": "",
        },
        _ctx(),
    )
    assert refresh_response["statusCode"] == 200
    refresh_body = json.loads(refresh_response["body"])
    assert refresh_body["spotify_access_token"] == "AT-2"
    new_refresh_cookie = next(c for c in refresh_response["cookies"] if c.startswith("refresh_token="))
    new_refresh_token = new_refresh_cookie.split("=", 1)[1].split(";")[0]
    assert new_refresh_token != refresh_token

    # 5. Replay the OLD refresh token → family revoked
    replay_response = auth_handler.lambda_handler(
        {
            "version": "2.0",
            "requestContext": {"requestId": "5", "routeKey": "POST /auth/refresh"},
            "headers": {"x-correlation-id": "cid"},
            "cookies": [f"refresh_token={refresh_token}"],
            "body": "",
        },
        _ctx(),
    )
    assert replay_response["statusCode"] == 401
    assert json.loads(replay_response["body"])["error_code"] == "refresh_replay_detected"
    assert all(s.revoked_at is not None for s in repo.sessions.values())

    # 6. POST /auth/logout — even with old session-revoked state, returns 204
    logout_response = auth_handler.lambda_handler(
        {
            "version": "2.0",
            "requestContext": {"requestId": "6", "routeKey": "POST /auth/logout"},
            "headers": {"x-correlation-id": "cid"},
            "cookies": [f"refresh_token={new_refresh_token}"],
            "body": "",
        },
        _ctx(),
    )
    assert logout_response["statusCode"] == 204


def test_non_premium_blocks_at_callback(monkeypatch) -> None:
    now = datetime(2026, 4, 26, 12, 0, tzinfo=timezone.utc)
    repo = FakeRepo()
    oauth = FakeOAuth()
    oauth.get_me = lambda *, access_token: SpotifyProfile(
        spotify_id="sp-free", display_name=None,
        email=None, product="free",
    )
    kms = FakeKms()
    _wire(monkeypatch, repo=repo, oauth=oauth, kms=kms, now=now)

    response = auth_handler.lambda_handler(
        {
            "version": "2.0",
            "requestContext": {"requestId": "1", "routeKey": "GET /auth/callback"},
            "headers": {"x-correlation-id": "cid"},
            "queryStringParameters": {"code": "X", "state": "S"},
            "cookies": ["oauth_state=S", "oauth_verifier=V"],
            "body": None,
        },
        _ctx(),
    )

    assert response["statusCode"] == 403
    assert json.loads(response["body"])["error_code"] == "premium_required"
    assert repo.users == {}
    assert repo.sessions == {}
    assert repo.vendor_tokens == {}

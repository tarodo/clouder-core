"""Auth Lambda settings + secret resolution."""

from __future__ import annotations

import functools
import os
import time
from dataclasses import dataclass

# The key is re-read this often, so a rotation (scripts/rotate_jwt_key.py) reaches warm
# containers without a deploy.
JWT_KEY_TTL_SECONDS = 300.0
_jwt_key: tuple[str, float] | None = None  # (value, fetched at, time.monotonic)


@dataclass(frozen=True)
class AuthSettings:
    kms_user_tokens_key_arn: str
    spotify_oauth_redirect_uri: str
    allowed_frontend_redirects: frozenset[str]
    admin_spotify_ids: frozenset[str]
    access_token_ttl_seconds: int
    refresh_token_ttl_seconds: int

    def is_admin(self, spotify_id: str) -> bool:
        return spotify_id in self.admin_spotify_ids

    def allows_redirect(self, path: str) -> bool:
        return path in self.allowed_frontend_redirects


def _parse_csv(raw: str) -> frozenset[str]:
    return frozenset(part.strip() for part in raw.split(",") if part.strip())


@functools.lru_cache(maxsize=1)
def get_auth_settings() -> AuthSettings:
    return AuthSettings(
        kms_user_tokens_key_arn=os.environ["KMS_USER_TOKENS_KEY_ARN"],
        spotify_oauth_redirect_uri=os.environ["SPOTIFY_OAUTH_REDIRECT_URI"],
        allowed_frontend_redirects=_parse_csv(os.environ.get("ALLOWED_FRONTEND_REDIRECTS", "")),
        admin_spotify_ids=_parse_csv(os.environ.get("ADMIN_SPOTIFY_IDS", "")),
        access_token_ttl_seconds=int(os.environ.get("JWT_ACCESS_TOKEN_TTL_SECONDS", "1800")),
        refresh_token_ttl_seconds=int(os.environ.get("JWT_REFRESH_TOKEN_TTL_SECONDS", "604800")),
    )


def reset_auth_settings_cache() -> None:
    global _jwt_key
    get_auth_settings.cache_clear()
    _jwt_key = None


def resolve_jwt_signing_key() -> str:
    global _jwt_key
    from collector import secrets

    direct = os.environ.get("JWT_SIGNING_KEY", "").strip()
    if direct:
        return direct
    ssm_name = os.environ.get("JWT_SIGNING_KEY_SSM_PARAMETER", "").strip()
    if ssm_name:
        now = time.monotonic()
        if _jwt_key is None or now - _jwt_key[1] >= JWT_KEY_TTL_SECONDS:
            _jwt_key = (secrets.fetch_ssm_parameter(ssm_name), now)
        return _jwt_key[0]
    raise RuntimeError(
        "JWT signing key not configured: set JWT_SIGNING_KEY or JWT_SIGNING_KEY_SSM_PARAMETER"
    )


def resolve_oauth_client_credentials() -> tuple[str, str]:
    from collector import secrets

    cid = os.environ.get("SPOTIFY_OAUTH_CLIENT_ID", "").strip()
    csec = os.environ.get("SPOTIFY_OAUTH_CLIENT_SECRET", "").strip()
    if cid and csec:
        return cid, csec

    ssm_id = os.environ.get("SPOTIFY_OAUTH_CLIENT_ID_SSM_PARAMETER", "").strip()
    ssm_sec = os.environ.get("SPOTIFY_OAUTH_CLIENT_SECRET_SSM_PARAMETER", "").strip()
    if ssm_id and ssm_sec:
        return (
            cid or secrets._fetch_ssm_parameter(ssm_id),
            csec or secrets._fetch_ssm_parameter(ssm_sec),
        )

    raise RuntimeError(
        "Spotify OAuth credentials not configured: set "
        "SPOTIFY_OAUTH_CLIENT_ID/SECRET or *_SSM_PARAMETER pair"
    )


def resolve_ytmusic_oauth_credentials() -> tuple[str, str]:
    from collector import secrets

    cid = os.environ.get("YTMUSIC_OAUTH_CLIENT_ID", "").strip()
    csec = os.environ.get("YTMUSIC_OAUTH_CLIENT_SECRET", "").strip()
    if cid and csec:
        return cid, csec

    ssm_id = os.environ.get("YTMUSIC_OAUTH_CLIENT_ID_SSM_PARAMETER", "").strip()
    ssm_sec = os.environ.get("YTMUSIC_OAUTH_CLIENT_SECRET_SSM_PARAMETER", "").strip()
    if ssm_id and ssm_sec:
        return (
            cid or secrets._fetch_ssm_parameter(ssm_id),
            csec or secrets._fetch_ssm_parameter(ssm_sec),
        )

    raise RuntimeError(
        "YouTube Music OAuth credentials not configured: set "
        "YTMUSIC_OAUTH_CLIENT_ID/SECRET or *_SSM_PARAMETER pair"
    )

"""Auth Lambda settings + secret resolution."""

from __future__ import annotations

import functools
import os
from dataclasses import dataclass


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
        allowed_frontend_redirects=_parse_csv(os.environ["ALLOWED_FRONTEND_REDIRECTS"]),
        admin_spotify_ids=_parse_csv(os.environ.get("ADMIN_SPOTIFY_IDS", "")),
        access_token_ttl_seconds=int(
            os.environ.get("JWT_ACCESS_TOKEN_TTL_SECONDS", "1800")
        ),
        refresh_token_ttl_seconds=int(
            os.environ.get("JWT_REFRESH_TOKEN_TTL_SECONDS", "604800")
        ),
    )


def reset_auth_settings_cache() -> None:
    get_auth_settings.cache_clear()


def resolve_jwt_signing_key() -> str:
    from collector import secrets

    direct = os.environ.get("JWT_SIGNING_KEY", "").strip()
    if direct:
        return direct
    ssm_name = os.environ.get("JWT_SIGNING_KEY_SSM_PARAMETER", "").strip()
    if ssm_name:
        return secrets._fetch_ssm_parameter(ssm_name)
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

"""Spotify OAuth client (authorization-code + PKCE, /me, refresh-grant)."""

from __future__ import annotations

import base64
import json
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any, Callable

from urllib.error import HTTPError, URLError


TOKEN_URL = "https://accounts.spotify.com/api/token"
ME_URL = "https://api.spotify.com/v1/me"


class SpotifyOAuthError(Exception):
    pass


class SpotifyTokenRevokedError(SpotifyOAuthError):
    """Raised when Spotify returns invalid_grant on refresh — user must re-OAuth."""


@dataclass(frozen=True)
class SpotifyTokenSet:
    access_token: str
    refresh_token: str
    expires_in: int
    scope: str | None


@dataclass(frozen=True)
class SpotifyProfile:
    spotify_id: str
    display_name: str | None
    email: str | None
    product: str  # "premium" | "free" | "open"


class SpotifyOAuthClient:
    def __init__(
        self,
        *,
        client_id: str,
        client_secret: str,
        redirect_uri: str,
        timeout_seconds: float = 15.0,
        urlopen: Callable[[urllib.request.Request, float], Any] | None = None,
    ) -> None:
        self._client_id = client_id
        self._client_secret = client_secret
        self._redirect_uri = redirect_uri
        self._timeout = timeout_seconds
        self._urlopen = urlopen or (lambda req, timeout: urllib.request.urlopen(req, timeout=timeout))

    def authorize_url(self, *, state: str, code_challenge: str, scopes: str) -> str:
        params = {
            "response_type": "code",
            "client_id": self._client_id,
            "redirect_uri": self._redirect_uri,
            "state": state,
            "code_challenge_method": "S256",
            "code_challenge": code_challenge,
            "scope": scopes,
        }
        return "https://accounts.spotify.com/authorize?" + urllib.parse.urlencode(params)

    def exchange_code(self, *, code: str, code_verifier: str) -> SpotifyTokenSet:
        body = urllib.parse.urlencode(
            {
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": self._redirect_uri,
                "code_verifier": code_verifier,
            }
        )
        payload = self._post_token(body)
        return self._token_set_from_payload(payload, fallback_refresh=None)

    def refresh(self, *, refresh_token: str) -> SpotifyTokenSet:
        body = urllib.parse.urlencode(
            {"grant_type": "refresh_token", "refresh_token": refresh_token}
        )
        payload = self._post_token(body)
        return self._token_set_from_payload(payload, fallback_refresh=refresh_token)

    def get_me(self, *, access_token: str) -> SpotifyProfile:
        request = urllib.request.Request(
            url=ME_URL,
            method="GET",
            headers={
                "Authorization": f"Bearer {access_token}",
                "Accept": "application/json",
            },
        )
        try:
            with self._urlopen(request, self._timeout) as response:
                status = getattr(response, "status", 200)
                body = response.read().decode("utf-8")
        except (HTTPError, URLError, TimeoutError) as exc:
            raise SpotifyOAuthError(f"spotify /me request failed: {exc}") from exc

        if status != 200:
            raise SpotifyOAuthError(f"spotify /me returned HTTP {status}: {body[:200]}")

        try:
            parsed = json.loads(body)
        except json.JSONDecodeError as exc:
            raise SpotifyOAuthError("spotify /me returned non-JSON") from exc

        return SpotifyProfile(
            spotify_id=str(parsed["id"]),
            display_name=parsed.get("display_name"),
            email=parsed.get("email"),
            product=str(parsed.get("product", "open")),
        )

    def _post_token(self, body: str) -> dict:
        credentials = base64.b64encode(
            f"{self._client_id}:{self._client_secret}".encode()
        ).decode()
        request = urllib.request.Request(
            url=TOKEN_URL,
            data=body.encode("utf-8"),
            method="POST",
            headers={
                "Authorization": f"Basic {credentials}",
                "Content-Type": "application/x-www-form-urlencoded",
                "Accept": "application/json",
            },
        )
        try:
            with self._urlopen(request, self._timeout) as response:
                status = getattr(response, "status", 200)
                raw = response.read().decode("utf-8")
        except (HTTPError, URLError, TimeoutError) as exc:
            raise SpotifyOAuthError(f"spotify token request failed: {exc}") from exc

        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise SpotifyOAuthError("spotify token response was not JSON") from exc

        if status != 200:
            error_code = parsed.get("error") if isinstance(parsed, dict) else None
            if error_code == "invalid_grant":
                raise SpotifyTokenRevokedError(
                    f"spotify token endpoint reported invalid_grant: {parsed}"
                )
            raise SpotifyOAuthError(
                f"spotify token endpoint returned HTTP {status}: {parsed}"
            )

        return parsed

    def _token_set_from_payload(
        self, payload: dict, fallback_refresh: str | None
    ) -> SpotifyTokenSet:
        access = payload.get("access_token")
        if not isinstance(access, str) or not access:
            raise SpotifyOAuthError("spotify token response missing access_token")
        refresh = payload.get("refresh_token") or fallback_refresh
        if not isinstance(refresh, str) or not refresh:
            raise SpotifyOAuthError("spotify token response missing refresh_token")
        return SpotifyTokenSet(
            access_token=access,
            refresh_token=refresh,
            expires_in=int(payload.get("expires_in", 3600)),
            scope=payload.get("scope"),
        )

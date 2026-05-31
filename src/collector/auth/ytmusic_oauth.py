"""Google device-flow OAuth client for YouTube Music (ytmusicapi auth).

Uses the OAuth 2.0 flow for "TVs and Limited Input devices" — the same flow
ytmusicapi expects. We drive Google's endpoints directly (urllib) so the poll
endpoint can return a clean 202 on authorization_pending instead of blocking.
Modeled on collector.auth.spotify_oauth.
"""

from __future__ import annotations

import json
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any, Callable
from urllib.error import HTTPError, URLError

DEVICE_CODE_URL = "https://oauth2.googleapis.com/device/code"
TOKEN_URL = "https://oauth2.googleapis.com/token"
YTMUSIC_SCOPE = "https://www.googleapis.com/auth/youtube"
DEVICE_GRANT = "urn:ietf:params:oauth:grant-type:device_code"


class YtmusicAuthError(Exception):
    """Generic / unrecoverable device-flow error."""


class YtmusicAuthPending(YtmusicAuthError):
    """User has not yet approved — caller should keep polling."""


class YtmusicAuthSlowDown(YtmusicAuthError):
    """Google asked us to poll less frequently."""


class YtmusicAuthDenied(YtmusicAuthError):
    """User denied the consent screen."""


class YtmusicAuthExpired(YtmusicAuthError):
    """device_code expired — restart the flow."""


@dataclass(frozen=True)
class YtmusicDeviceCode:
    device_code: str
    user_code: str
    verification_url: str
    interval: int
    expires_in: int


@dataclass(frozen=True)
class YtmusicTokenSet:
    access_token: str
    refresh_token: str
    expires_in: int
    scope: str | None


class YtmusicOAuthClient:
    def __init__(
        self,
        *,
        client_id: str,
        client_secret: str,
        timeout_seconds: float = 15.0,
        urlopen: Callable[[urllib.request.Request, float], Any] | None = None,
    ) -> None:
        self._client_id = client_id
        self._client_secret = client_secret
        self._timeout = timeout_seconds
        self._urlopen = urlopen or (
            lambda req, timeout: urllib.request.urlopen(req, timeout=timeout)
        )

    def request_device_code(self) -> YtmusicDeviceCode:
        body = urllib.parse.urlencode(
            {"client_id": self._client_id, "scope": YTMUSIC_SCOPE}
        )
        payload = self._post(DEVICE_CODE_URL, body)
        return YtmusicDeviceCode(
            device_code=str(payload["device_code"]),
            user_code=str(payload["user_code"]),
            verification_url=str(
                payload.get("verification_url")
                or payload.get("verification_uri")
            ),
            interval=int(payload.get("interval", 5)),
            expires_in=int(payload.get("expires_in", 1800)),
        )

    def exchange_device_code(self, *, device_code: str) -> YtmusicTokenSet:
        body = urllib.parse.urlencode(
            {
                "client_id": self._client_id,
                "client_secret": self._client_secret,
                "device_code": device_code,
                "grant_type": DEVICE_GRANT,
            }
        )
        payload = self._post(TOKEN_URL, body, allow_error=True)
        self._raise_for_flow_error(payload)
        return self._token_set(payload, fallback_refresh=None)

    def refresh(self, *, refresh_token: str) -> YtmusicTokenSet:
        body = urllib.parse.urlencode(
            {
                "client_id": self._client_id,
                "client_secret": self._client_secret,
                "refresh_token": refresh_token,
                "grant_type": "refresh_token",
            }
        )
        payload = self._post(TOKEN_URL, body, allow_error=True)
        self._raise_for_flow_error(payload)
        return self._token_set(payload, fallback_refresh=refresh_token)

    # ---- internals -----------------------------------------------------

    def _raise_for_flow_error(self, payload: dict) -> None:
        err = payload.get("error")
        if not err:
            return
        if err == "authorization_pending":
            raise YtmusicAuthPending(err)
        if err == "slow_down":
            raise YtmusicAuthSlowDown(err)
        if err == "access_denied":
            raise YtmusicAuthDenied(err)
        if err in ("expired_token", "token_expired"):
            raise YtmusicAuthExpired(err)
        raise YtmusicAuthError(f"google oauth error: {payload}")

    def _token_set(
        self, payload: dict, *, fallback_refresh: str | None
    ) -> YtmusicTokenSet:
        access = payload.get("access_token")
        if not isinstance(access, str) or not access:
            raise YtmusicAuthError("token response missing access_token")
        refresh = payload.get("refresh_token") or fallback_refresh
        if not isinstance(refresh, str) or not refresh:
            raise YtmusicAuthError("token response missing refresh_token")
        return YtmusicTokenSet(
            access_token=access,
            refresh_token=refresh,
            expires_in=int(payload.get("expires_in", 3599)),
            scope=payload.get("scope"),
        )

    def _post(self, url: str, body: str, *, allow_error: bool = False) -> dict:
        request = urllib.request.Request(
            url=url,
            data=body.encode("utf-8"),
            method="POST",
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Accept": "application/json",
            },
        )
        try:
            with self._urlopen(request, self._timeout) as response:
                raw = response.read().decode("utf-8")
        except HTTPError as exc:
            # Google returns 4xx with a JSON {"error": ...} body for flow
            # states (authorization_pending/slow_down/...). Parse it.
            raw = exc.read().decode("utf-8") if hasattr(exc, "read") else ""
            if not allow_error:
                raise YtmusicAuthError(
                    f"google oauth HTTP {exc.code}: {raw[:200]}"
                ) from exc
        except (URLError, TimeoutError) as exc:
            raise YtmusicAuthError(f"google oauth request failed: {exc}") from exc
        try:
            return json.loads(raw) if raw else {}
        except json.JSONDecodeError as exc:
            raise YtmusicAuthError("google oauth response was not JSON") from exc

"""Beatport access token from the owner's credentials (docs/data/auto-ingest.md).

API v4 flow, no browser: log in (session cookie) → authorize (a redirect carrying
a code) → exchange the code for an access token. The token lives in memory for
one run; nothing here logs, stores or chains an error that could carry a token
or a password (CLAUDE.md #5).
"""

from __future__ import annotations

import http.client
import http.cookiejar
import json
import os
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

API = "https://api.beatport.com/v4"
REDIRECT_URI = f"{API}/auth/o/post-message/"
_REDIRECTS = (301, 302, 303, 307, 308)


class BeatportAuthError(Exception):
    """A login step failed; carries the step and the HTTP status only."""

    def __init__(self, step: str, status: int | str) -> None:
        super().__init__(f"Beatport login failed at {step} (status {status})")
        self.step = step
        self.status = status


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    # The authorize redirect carries the code: surface it instead of following it.
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _default_opener() -> Any:
    return urllib.request.build_opener(
        urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()), _NoRedirect()
    )


def _call(opener: Any, step: str, request: urllib.request.Request, timeout: float,
          *, redirect: bool = False) -> tuple[int, Any, bytes]:
    try:
        response = opener.open(request, timeout=timeout)
        return response.status, response.headers, response.read()
    except urllib.error.HTTPError as exc:
        if redirect and exc.code in _REDIRECTS:
            return exc.code, exc.headers, b""
        raise BeatportAuthError(step, exc.code) from None
    except (urllib.error.URLError, OSError, http.client.HTTPException):
        # Includes a body cut short or a read timeout: still a reported step.
        raise BeatportAuthError(step, "network") from None


def read_credentials() -> tuple[str, str]:
    """Username and password from the SSM parameters named in the Lambda env."""
    from . import secrets

    return (
        secrets._fetch_ssm_parameter(os.environ["BEATPORT_USERNAME_SSM_PARAMETER"]),
        secrets._fetch_ssm_parameter(os.environ["BEATPORT_PASSWORD_SSM_PARAMETER"]),
    )


def fetch_access_token(
    username: str,
    password: str,
    *,
    client_id: str | None = None,
    opener: Any = None,
    timeout: float = 20.0,
) -> str:
    # Login and authorize share a cookie session; the token exchange runs outside
    # it, exactly like the tested reference (HP/bp_t/bp_token_api.py).
    # The public OAuth client id of Beatport's API docs page comes from config only
    # (GitHub secret BEATPORT_CLIENT_ID → Lambda env), so a rotated id needs no code change.
    client_id = client_id or os.environ.get("BEATPORT_CLIENT_ID")
    if not client_id:
        raise BeatportAuthError("client_id", "missing")
    session = opener or _default_opener()
    plain = opener or urllib.request.build_opener()

    _call(session, "login", urllib.request.Request(
        f"{API}/auth/login/",
        data=json.dumps({"username": username, "password": password}).encode(),
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    ), timeout)

    query = urllib.parse.urlencode(
        {"response_type": "code", "client_id": client_id, "redirect_uri": REDIRECT_URI}
    )
    status, headers, _ = _call(session, "authorize", urllib.request.Request(
        f"{API}/auth/o/authorize/?{query}",
    ), timeout, redirect=True)
    location = headers.get("Location", "") if status in _REDIRECTS else ""
    code = urllib.parse.parse_qs(urllib.parse.urlparse(location).query).get("code", [None])[0]
    if not code:
        raise BeatportAuthError("authorize", status)

    status, _, body = _call(plain, "token", urllib.request.Request(
        f"{API}/auth/o/token/",
        data=urllib.parse.urlencode({
            "client_id": client_id,
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": REDIRECT_URI,
        }).encode(),
        headers={"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"},
        method="POST",
    ), timeout)
    try:
        token = json.loads(body).get("access_token")
    except (ValueError, AttributeError):
        token = None
    if not isinstance(token, str) or not token:
        raise BeatportAuthError("token", status)
    return token

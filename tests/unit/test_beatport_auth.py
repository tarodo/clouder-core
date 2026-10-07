from __future__ import annotations

import io
import json
import urllib.error
import urllib.parse
from email.message import Message

import pytest

from collector.beatport_auth import BeatportAuthError, fetch_access_token

PASSWORD = "s3cret-pass"
TOKEN = "TOKEN-123"


class Response:
    def __init__(self, status: int, body: bytes = b"", headers: dict | None = None) -> None:
        self.status = status
        self._body = body
        self.headers = Message()
        for k, v in (headers or {}).items():
            self.headers[k] = v

    def read(self) -> bytes:
        return self._body


def _http_error(url: str, code: int, headers: dict | None = None, body: bytes = b"") -> urllib.error.HTTPError:
    msg = Message()
    for k, v in (headers or {}).items():
        msg[k] = v
    return urllib.error.HTTPError(url, code, "x", msg, io.BytesIO(body))


class Opener:
    """Answers by path: 'login', 'authorize', 'token' -> Response or exception."""

    def __init__(self, **answers) -> None:
        self.answers = answers
        self.requests: list = []

    def open(self, request, timeout=None):
        self.requests.append(request)
        path = urllib.parse.urlparse(request.full_url).path
        step = "login" if path.endswith("/auth/login/") else "authorize" if "authorize" in path else "token"
        answer = self.answers[step]
        if isinstance(answer, Exception):
            raise answer
        return answer


def _redirect(code="abc"):
    return _http_error(
        "https://api.beatport.com/v4/auth/o/authorize/", 302,
        {"Location": f"https://api.beatport.com/v4/auth/o/post-message/?code={code}"},
    )


def _token_ok():
    return Response(200, json.dumps({"access_token": TOKEN, "expires_in": 36000}).encode())


def test_three_step_flow_returns_the_access_token() -> None:
    opener = Opener(login=Response(200, b"{}"), authorize=_redirect(), token=_token_ok())

    assert fetch_access_token("user", PASSWORD, opener=opener) == TOKEN

    login, authorize, token = opener.requests
    assert json.loads(login.data) == {"username": "user", "password": PASSWORD}
    query = urllib.parse.parse_qs(urllib.parse.urlparse(authorize.full_url).query)
    assert query["response_type"] == ["code"] and query["client_id"] and query["redirect_uri"]
    form = urllib.parse.parse_qs(token.data.decode())
    assert form["grant_type"] == ["authorization_code"] and form["code"] == ["abc"]


@pytest.mark.parametrize(
    "step, answers",
    [
        ("login", {"login": _http_error("u", 401, body=b'{"detail": "bad"}')}),
        ("token", {"login": Response(200), "authorize": _redirect(),
                   "token": _http_error("u", 400, body=TOKEN.encode())}),
    ],
)
def test_each_failing_step_is_named_without_secrets(step, answers) -> None:
    with pytest.raises(BeatportAuthError) as caught:
        fetch_access_token("user", PASSWORD, opener=Opener(**answers))

    error = caught.value
    assert error.step == step and isinstance(error.status, int)
    assert PASSWORD not in str(error) and TOKEN not in str(error)
    assert error.__cause__ is None


def test_authorize_without_redirect_fails() -> None:
    opener = Opener(login=Response(200), authorize=Response(200, b"<html>login</html>"))

    with pytest.raises(BeatportAuthError) as caught:
        fetch_access_token("user", PASSWORD, opener=opener)

    assert caught.value.step == "authorize"


def test_network_error_is_reported_as_network() -> None:
    opener = Opener(login=urllib.error.URLError("unreachable"))

    with pytest.raises(BeatportAuthError) as caught:
        fetch_access_token("user", PASSWORD, opener=opener)

    assert (caught.value.step, caught.value.status) == ("login", "network")

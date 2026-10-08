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


@pytest.fixture(autouse=True)
def _client_id(monkeypatch):
    monkeypatch.setenv("BEATPORT_CLIENT_ID", "test-client")


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
    assert error.__suppress_context__  # the HTTPError (and its body) is not chained


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


class _Truncated(Response):
    def read(self) -> bytes:
        import http.client

        raise http.client.IncompleteRead(b"par", 10)


def test_truncated_body_is_reported_as_network() -> None:
    with pytest.raises(BeatportAuthError) as caught:
        fetch_access_token("user", PASSWORD, opener=Opener(login=_Truncated(200)))

    assert (caught.value.step, caught.value.status) == ("login", "network")


def test_real_opener_carries_the_session_and_reads_the_redirect(monkeypatch) -> None:
    # The two mechanisms the flow depends on, through the real urllib handlers:
    # the login cookie reaches authorize, and the 302 is read instead of followed.
    import http.server
    import threading

    from collector import beatport_auth

    seen: dict = {}

    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def _send(self, code, headers=None, body=b""):
            self.send_response(code)
            for k, v in (headers or {}).items():
                self.send_header(k, v)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self):
            self.rfile.read(int(self.headers.get("Content-Length", 0)))
            if self.path == "/v4/auth/login/":
                self._send(200, {"Set-Cookie": "sessionid=S1; Path=/; HttpOnly"}, b"{}")
            else:
                seen["token_cookie"] = self.headers.get("Cookie")
                self._send(200, {"Content-Type": "application/json"},
                           json.dumps({"access_token": TOKEN}).encode())

        def do_GET(self):
            if self.path.startswith("/v4/auth/o/post-message/"):
                self._send(200, {"Content-Type": "text/html"}, b"<html>done</html>")  # like Beatport
                return
            seen["authorize_cookie"] = self.headers.get("Cookie")
            self._send(302, {"Location": f"{api}/auth/o/post-message/?code=abc"})

    server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
    api = f"http://127.0.0.1:{server.server_port}/v4"
    threading.Thread(target=server.serve_forever, daemon=True).start()
    monkeypatch.setattr(beatport_auth, "API", api)
    monkeypatch.setattr(beatport_auth, "REDIRECT_URI", f"{api}/auth/o/post-message/")
    try:
        assert fetch_access_token("user", PASSWORD) == TOKEN
    finally:
        server.shutdown()

    assert seen["authorize_cookie"] == "sessionid=S1"
    assert seen["token_cookie"] is None  # like the tested reference: token call outside the session



def test_client_id_comes_from_the_environment(monkeypatch) -> None:
    monkeypatch.setenv("BEATPORT_CLIENT_ID", "custom-id")
    opener = Opener(login=Response(200, b"{}"), authorize=_redirect(), token=_token_ok())

    fetch_access_token("user", PASSWORD, opener=opener)

    _, authorize, token = opener.requests
    assert urllib.parse.parse_qs(urllib.parse.urlparse(authorize.full_url).query)["client_id"] == ["custom-id"]
    assert urllib.parse.parse_qs(token.data.decode())["client_id"] == ["custom-id"]


@pytest.mark.parametrize("env", ["", None])
def test_missing_client_id_fails_before_any_request(monkeypatch, env) -> None:
    # No id in code: the GitHub secret BEATPORT_CLIENT_ID is the only source.
    if env is None:
        monkeypatch.delenv("BEATPORT_CLIENT_ID", raising=False)
    else:
        monkeypatch.setenv("BEATPORT_CLIENT_ID", env)
    opener = Opener(login=Response(200, b"{}"), authorize=_redirect(), token=_token_ok())

    with pytest.raises(BeatportAuthError) as caught:
        fetch_access_token("user", PASSWORD, opener=opener)

    assert (caught.value.step, caught.value.status) == ("client_id", "missing")
    assert opener.requests == []

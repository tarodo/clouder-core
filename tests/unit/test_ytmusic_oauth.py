import json
import io
from urllib.error import HTTPError

import pytest

from collector.auth.ytmusic_oauth import (
    YtmusicAuthDenied,
    YtmusicAuthError,
    YtmusicAuthExpired,
    YtmusicAuthPending,
    YtmusicOAuthClient,
)


class FakeResp:
    def __init__(self, status, body):
        self.status = status
        self._body = json.dumps(body).encode("utf-8")

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _raising_client(status, body):
    """Return a client whose urlopen always raises HTTPError with a JSON body."""
    def fake_urlopen(req, timeout):
        raise HTTPError(
            url="https://oauth2.googleapis.com/token",
            code=status,
            msg="error",
            hdrs=None,
            fp=io.BytesIO(json.dumps(body).encode("utf-8")),
        )
    return YtmusicOAuthClient(client_id="cid", client_secret="csec", urlopen=fake_urlopen)


def make_client(responses):
    """responses: list of (status, body) returned in order."""
    seq = list(responses)

    def fake_urlopen(req, timeout):
        status, body = seq.pop(0)
        return FakeResp(status, body)

    return YtmusicOAuthClient(
        client_id="cid", client_secret="csec", urlopen=fake_urlopen
    )


def test_request_device_code():
    client = make_client([
        (200, {
            "device_code": "dc", "user_code": "ABCD-EFGH",
            "verification_url": "https://www.google.com/device",
            "expires_in": 1800, "interval": 5,
        }),
    ])
    code = client.request_device_code()
    assert code.device_code == "dc"
    assert code.user_code == "ABCD-EFGH"
    assert code.verification_url == "https://www.google.com/device"
    assert code.interval == 5
    assert code.expires_in == 1800


def test_exchange_pending_raises_pending():
    client = make_client([(428, {"error": "authorization_pending"})])
    with pytest.raises(YtmusicAuthPending):
        client.exchange_device_code(device_code="dc")


def test_exchange_expired_raises_expired():
    client = make_client([(400, {"error": "expired_token"})])
    with pytest.raises(YtmusicAuthExpired):
        client.exchange_device_code(device_code="dc")


def test_exchange_success_returns_tokens():
    client = make_client([
        (200, {
            "access_token": "at", "refresh_token": "rt",
            "expires_in": 3599, "scope": "https://www.googleapis.com/auth/youtube",
            "token_type": "Bearer",
        }),
    ])
    tokens = client.exchange_device_code(device_code="dc")
    assert tokens.access_token == "at"
    assert tokens.refresh_token == "rt"
    assert tokens.expires_in == 3599


def test_refresh_keeps_old_refresh_token_when_absent():
    client = make_client([
        (200, {"access_token": "at2", "expires_in": 3599,
                "scope": "s", "token_type": "Bearer"}),
    ])
    tokens = client.refresh(refresh_token="rt-old")
    assert tokens.access_token == "at2"
    assert tokens.refresh_token == "rt-old"


def test_access_denied_raises_denied():
    client = make_client([(403, {"error": "access_denied"})])
    with pytest.raises(YtmusicAuthDenied):
        client.exchange_device_code(device_code="dc")


def test_unknown_error_raises_autherror():
    client = make_client([(403, {"error": "some_unexpected_thing"})])
    with pytest.raises(YtmusicAuthError):
        client.exchange_device_code(device_code="dc")


def test_exchange_httperror_pending_is_parsed():
    # Real urllib raises HTTPError for 4xx; with allow_error=True the body is
    # parsed and the flow error is surfaced.
    client = _raising_client(428, {"error": "authorization_pending"})
    with pytest.raises(YtmusicAuthPending):
        client.exchange_device_code(device_code="dc")


def test_device_code_httperror_without_allow_error_raises_autherror():
    # request_device_code uses allow_error=False, so an HTTPError becomes a
    # generic YtmusicAuthError.
    client = _raising_client(400, {"error": "invalid_client"})
    with pytest.raises(YtmusicAuthError):
        client.request_device_code()

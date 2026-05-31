import json
from unittest.mock import patch

from collector import auth_handler
from collector.auth.ytmusic_oauth import (
    YtmusicAuthPending,
    YtmusicDeviceCode,
    YtmusicTokenSet,
)


def _event(route, body=None, user_id="u1"):
    return {
        "requestContext": {
            "routeKey": route,
            "authorizer": {"lambda": {"user_id": user_id, "session_id": "s1"}},
        },
        "body": json.dumps(body) if body is not None else None,
    }


class FakeOAuth:
    def __init__(self, *, code=None, exchange=None, raises=None):
        self._code = code
        self._exchange = exchange
        self._raises = raises

    def request_device_code(self):
        return self._code

    def exchange_device_code(self, *, device_code):
        if self._raises:
            raise self._raises
        return self._exchange


class FakeRepo:
    def __init__(self):
        self.upserts = []
        self.deleted = []

    def upsert_vendor_token(self, cmd):
        self.upserts.append(cmd)

    def delete_vendor_token(self, *, user_id, vendor):
        self.deleted.append((user_id, vendor))


class _FakeEnvelope:
    def encrypt(self, b):
        from collector.auth.kms_envelope import EnvelopePayload
        return EnvelopePayload(data_key_enc=b"k", nonce=b"0" * 12, ciphertext=b)


def test_device_code_returns_user_code():
    code = YtmusicDeviceCode(
        device_code="dc", user_code="ABCD-EFGH",
        verification_url="https://www.google.com/device",
        interval=5, expires_in=1800,
    )
    with patch.object(auth_handler, "resolve_ytmusic_oauth_credentials",
                      return_value=("cid", "csec")), \
         patch.object(auth_handler, "YtmusicOAuthClient",
                      return_value=FakeOAuth(code=code)):
        resp = auth_handler._handle_ytmusic_device_code(
            _event("POST /auth/ytmusic/device-code"), "corr"
        )
    assert resp["statusCode"] == 200
    body = json.loads(resp["body"])
    assert body["user_code"] == "ABCD-EFGH"
    assert body["device_code"] == "dc"
    assert body["interval"] == 5


def test_poll_pending_returns_202():
    with patch.object(auth_handler, "resolve_ytmusic_oauth_credentials",
                      return_value=("cid", "csec")), \
         patch.object(auth_handler, "YtmusicOAuthClient",
                      return_value=FakeOAuth(raises=YtmusicAuthPending("pending"))):
        resp = auth_handler._handle_ytmusic_poll(
            _event("POST /auth/ytmusic/poll", {"device_code": "dc"}), "corr"
        )
    assert resp["statusCode"] == 202
    assert json.loads(resp["body"])["status"] == "authorization_pending"


def test_poll_success_stores_token_and_returns_200():
    tokens = YtmusicTokenSet(
        access_token="at", refresh_token="rt", expires_in=3599, scope="s"
    )
    repo = FakeRepo()
    with patch.object(auth_handler, "resolve_ytmusic_oauth_credentials",
                      return_value=("cid", "csec")), \
         patch.object(auth_handler, "YtmusicOAuthClient",
                      return_value=FakeOAuth(exchange=tokens)), \
         patch.object(auth_handler, "_build_auth_repository", return_value=repo), \
         patch.object(auth_handler, "_build_kms_envelope",
                      return_value=_FakeEnvelope()):
        resp = auth_handler._handle_ytmusic_poll(
            _event("POST /auth/ytmusic/poll", {"device_code": "dc"}), "corr"
        )
    assert resp["statusCode"] == 200
    assert json.loads(resp["body"])["connected"] is True
    assert len(repo.upserts) == 1
    assert repo.upserts[0].vendor == "ytmusic"

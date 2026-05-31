import base64
from datetime import datetime, timedelta, timezone

from collector.auth.kms_envelope import EnvelopePayload
from collector.curation import YtmusicNotAuthorizedError
from collector.curation.ytmusic_token_resolver import YtmusicTokenResolver


class FakeEnvelope:
    def encrypt(self, b):
        return EnvelopePayload(data_key_enc=b"k", nonce=b"0" * 12, ciphertext=b)

    def decrypt(self, payload):
        return payload.ciphertext


def _enc(value: str) -> str:
    payload = EnvelopePayload(
        data_key_enc=b"k", nonce=b"0" * 12, ciphertext=value.encode("utf-8")
    )
    return base64.b64encode(payload.serialize()).decode("ascii")


class FakeDataApi:
    def __init__(self, rows):
        self.rows = rows
        self.updates = []

    def execute(self, sql, params=None):
        if sql.strip().upper().startswith("UPDATE"):
            self.updates.append(params)
            return []
        return self.rows


class FakeOAuth:
    def __init__(self, new_access="fresh"):
        self.new_access = new_access
        self.refreshed = False

    def refresh(self, *, refresh_token):
        from collector.auth.ytmusic_oauth import YtmusicTokenSet
        self.refreshed = True
        return YtmusicTokenSet(
            access_token=self.new_access, refresh_token=refresh_token,
            expires_in=3599, scope="s",
        )


def test_no_token_raises():
    resolver = YtmusicTokenResolver(
        data_api=FakeDataApi(rows=[]), envelope=FakeEnvelope(), oauth_client=FakeOAuth()
    )
    try:
        resolver.resolve(user_id="u1")
        assert False
    except YtmusicNotAuthorizedError:
        pass


def test_valid_token_no_refresh():
    future = datetime.now(timezone.utc) + timedelta(hours=1)
    rows = [{
        "access_token_enc": _enc("AT"),
        "refresh_token_enc": _enc("RT"),
        "data_key_enc": "", "expires_at": future,
    }]
    oauth = FakeOAuth()
    resolver = YtmusicTokenResolver(
        data_api=FakeDataApi(rows), envelope=FakeEnvelope(), oauth_client=oauth
    )
    token = resolver.resolve(user_id="u1")
    assert token.token_dict["access_token"] == "AT"
    assert oauth.refreshed is False


def test_expired_token_refreshes_and_persists():
    past = datetime.now(timezone.utc) - timedelta(minutes=1)
    rows = [{
        "access_token_enc": _enc("OLD"),
        "refresh_token_enc": _enc("RT"),
        "data_key_enc": "", "expires_at": past,
    }]
    api = FakeDataApi(rows)
    oauth = FakeOAuth(new_access="NEW")
    resolver = YtmusicTokenResolver(
        data_api=api, envelope=FakeEnvelope(), oauth_client=oauth
    )
    token = resolver.resolve(user_id="u1")
    assert token.token_dict["access_token"] == "NEW"
    assert oauth.refreshed is True
    assert len(api.updates) == 1


def test_token_dict_has_all_ytmusicapi_oauth_keys():
    # ytmusicapi 1.12 OAuthToken.is_oauth requires ALL of Token.members():
    # scope, token_type, access_token, refresh_token, expires_at, expires_in.
    # Omitting expires_in (the original bug) made ytmusicapi treat the dict as
    # browser headers -> YT Music writes failed with HTTP 400 "invalid argument".
    future = datetime.now(timezone.utc) + timedelta(hours=1)
    rows = [{
        "access_token_enc": _enc("AT"),
        "refresh_token_enc": _enc("RT"),
        "data_key_enc": "", "expires_at": future,
    }]
    resolver = YtmusicTokenResolver(
        data_api=FakeDataApi(rows), envelope=FakeEnvelope(), oauth_client=FakeOAuth()
    )
    td = resolver.resolve(user_id="u1").token_dict
    required = {
        "scope", "token_type", "access_token",
        "refresh_token", "expires_at", "expires_in",
    }
    assert required <= set(td.keys())
    assert isinstance(td["expires_in"], int) and td["expires_in"] > 0

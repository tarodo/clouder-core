"""The analysis service token: accepted only on /v1/analysis/*, never logged."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from collector import auth_authorizer
from collector.auth import auth_settings
from collector.auth.auth_settings import reset_auth_settings_cache
from collector.auth.jwt_utils import issue_access_token

SECRET = "0" * 32
TOKEN = "svc_" + "A1b2" * 11
HASH = hashlib.sha256(TOKEN.encode()).hexdigest()
NOW = datetime(2026, 10, 16, 3, tzinfo=UTC)


class FakeSsm:
    def __init__(self, value: str | None):
        self.value, self.calls = value, 0

    def __call__(self, name: str) -> str:
        self.calls += 1
        assert name == "/clouder/auth/analysis_service_token_sha256"
        if self.value is None:
            raise RuntimeError("ParameterNotFound")
        return self.value


@pytest.fixture
def ssm(monkeypatch):
    fake = FakeSsm(HASH.upper() + "\n")  # stored hex may carry case / a newline
    monkeypatch.setenv("JWT_SIGNING_KEY", SECRET)
    monkeypatch.setenv(
        "ANALYSIS_TOKEN_SHA256_SSM_PARAMETER", "/clouder/auth/analysis_service_token_sha256"
    )
    monkeypatch.setattr("collector.secrets.fetch_ssm_parameter", fake)
    monkeypatch.setattr(auth_authorizer, "_now", lambda: NOW)
    reset_auth_settings_cache()
    yield fake
    reset_auth_settings_cache()


def _call(route: str, header: str) -> dict:
    event = {"type": "REQUEST", "routeKey": route, "headers": {"Authorization": header}}
    return auth_authorizer.lambda_handler(event, SimpleNamespace(aws_request_id="A"))


def _jwt() -> str:
    return issue_access_token(
        secret=SECRET, user_id="u1", session_id="s1", is_admin=True, ttl_seconds=1800, now=NOW
    )


@pytest.mark.parametrize("route", ["POST /v1/analysis/claim", "POST /v1/analysis/results"])
def test_service_token_opens_the_analysis_routes(ssm, route) -> None:
    assert _call(route, f"Bearer {TOKEN}") == {
        "isAuthorized": True,
        "context": {"service": "analyzer"},
    }


def test_wrong_service_token_is_denied(ssm) -> None:
    assert _call("POST /v1/analysis/claim", "Bearer svc_wrong") == {"isAuthorized": False}


def test_user_jwt_is_denied_on_analysis_routes(ssm) -> None:
    assert _call("POST /v1/analysis/claim", f"Bearer {_jwt()}") == {"isAuthorized": False}


def test_service_token_is_denied_on_user_routes(ssm) -> None:
    assert _call("GET /me", f"Bearer {TOKEN}") == {"isAuthorized": False}
    assert _call("GET /admin/analysis/status", f"Bearer {TOKEN}") == {"isAuthorized": False}


def test_missing_hash_denies_and_is_fetched_once_per_ttl(ssm) -> None:
    ssm.value = None
    assert _call("POST /v1/analysis/claim", f"Bearer {TOKEN}") == {"isAuthorized": False}
    assert _call("POST /v1/analysis/claim", f"Bearer {TOKEN}") == {"isAuthorized": False}
    assert ssm.calls == 1


def test_hash_is_cached_within_the_ttl(ssm) -> None:
    for _ in range(3):
        _call("POST /v1/analysis/claim", f"Bearer {TOKEN}")
    assert ssm.calls == 1


def test_hash_refetch_after_the_ttl(ssm, monkeypatch) -> None:
    clock = [1000.0]
    monkeypatch.setattr(auth_settings.time, "monotonic", lambda: clock[0])
    _call("POST /v1/analysis/claim", f"Bearer {TOKEN}")
    clock[0] += auth_settings.JWT_KEY_TTL_SECONDS + 1
    _call("POST /v1/analysis/claim", f"Bearer {TOKEN}")
    assert ssm.calls == 2


def test_neither_token_nor_hash_is_logged(ssm, capsys) -> None:
    _call("POST /v1/analysis/claim", "Bearer svc_wrong")
    _call("POST /v1/analysis/claim", f"Bearer {TOKEN}")
    ssm.value = None
    reset_auth_settings_cache()
    _call("POST /v1/analysis/claim", f"Bearer {TOKEN}")
    out = capsys.readouterr()
    logged = out.out + out.err
    assert TOKEN not in logged and HASH not in logged and HASH.upper() not in logged
    assert "svc_wrong" not in logged

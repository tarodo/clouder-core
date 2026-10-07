from __future__ import annotations

import pytest

from collector import auto_ingest_handler as handler
from collector.beatport_auth import BeatportAuthError

TOKEN = "TOKEN-xyz"


@pytest.fixture()
def events(monkeypatch):
    captured: list = []
    monkeypatch.setattr(
        handler, "log_event", lambda level, message, **fields: captured.append((message, fields))
    )
    return captured


def test_auth_check_ok(monkeypatch, events) -> None:
    monkeypatch.setattr(handler, "_read_credentials", lambda: ("user", "pw"))
    monkeypatch.setattr(handler, "fetch_access_token", lambda u, p: TOKEN)

    result = handler.lambda_handler({"action": "auth_check"}, None)

    assert result == {"ok": True}
    assert TOKEN not in repr(events) and "pw" not in repr(events)


def test_auth_check_reports_failed_step(monkeypatch, events) -> None:
    monkeypatch.setattr(handler, "_read_credentials", lambda: ("user", "pw"))

    def fail(u, p):
        raise BeatportAuthError("token", 400)

    monkeypatch.setattr(handler, "fetch_access_token", fail)

    assert handler.lambda_handler({"action": "auth_check"}, None) == {
        "ok": False, "step": "token", "status": 400,
    }


def test_auth_check_reports_missing_credentials(monkeypatch, events) -> None:
    monkeypatch.setenv("BEATPORT_USERNAME_SSM_PARAMETER", "/clouder/beatport/username")
    monkeypatch.setenv("BEATPORT_PASSWORD_SSM_PARAMETER", "/clouder/beatport/password")

    def missing(name):
        raise RuntimeError("ParameterNotFound")

    monkeypatch.setattr(handler.secrets, "_fetch_ssm_parameter", missing)

    assert handler.lambda_handler({"action": "auth_check"}, None) == {
        "ok": False, "step": "credentials", "status": None,
    }


def test_unknown_action_raises() -> None:
    with pytest.raises(ValueError):
        handler.lambda_handler({"action": "drop"}, None)

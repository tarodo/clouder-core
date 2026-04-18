from __future__ import annotations

from unittest.mock import MagicMock

import pytest


def test_fetch_ssm_parameter_decrypts_and_returns_string(monkeypatch) -> None:
    from collector import secrets

    fake_client = MagicMock()
    fake_client.get_parameter.return_value = {
        "Parameter": {"Value": "secret-value"}
    }
    monkeypatch.setattr(secrets, "_ssm_client", lambda: fake_client)
    secrets._fetch_ssm_parameter.cache_clear()

    result = secrets._fetch_ssm_parameter("/clouder/test/key")

    assert result == "secret-value"
    fake_client.get_parameter.assert_called_once_with(
        Name="/clouder/test/key", WithDecryption=True
    )


def test_fetch_ssm_parameter_is_cached(monkeypatch) -> None:
    from collector import secrets

    fake_client = MagicMock()
    fake_client.get_parameter.return_value = {
        "Parameter": {"Value": "cached-value"}
    }
    monkeypatch.setattr(secrets, "_ssm_client", lambda: fake_client)
    secrets._fetch_ssm_parameter.cache_clear()

    secrets._fetch_ssm_parameter("/clouder/test/key2")
    secrets._fetch_ssm_parameter("/clouder/test/key2")

    assert fake_client.get_parameter.call_count == 1


def test_fetch_ssm_parameter_rejects_empty_value(monkeypatch) -> None:
    from collector import secrets

    fake_client = MagicMock()
    fake_client.get_parameter.return_value = {"Parameter": {"Value": ""}}
    monkeypatch.setattr(secrets, "_ssm_client", lambda: fake_client)
    secrets._fetch_ssm_parameter.cache_clear()

    with pytest.raises(RuntimeError, match="empty"):
        secrets._fetch_ssm_parameter("/clouder/empty")


def test_fetch_ssm_parameter_rejects_missing_parameter_field(monkeypatch) -> None:
    from collector import secrets

    fake_client = MagicMock()
    fake_client.get_parameter.return_value = {}
    monkeypatch.setattr(secrets, "_ssm_client", lambda: fake_client)
    secrets._fetch_ssm_parameter.cache_clear()

    with pytest.raises(RuntimeError, match="malformed"):
        secrets._fetch_ssm_parameter("/clouder/missing")

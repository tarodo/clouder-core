from __future__ import annotations

from unittest.mock import MagicMock

import pytest


def test_iam_mode_uses_generate_db_auth_token(monkeypatch) -> None:
    from collector import migration_handler as mh
    from collector import settings as s

    monkeypatch.setenv("AURORA_AUTH_MODE", "iam")
    monkeypatch.setenv("AURORA_WRITER_ENDPOINT", "writer.example")
    monkeypatch.setenv("AURORA_PORT", "5432")
    monkeypatch.setenv("AURORA_DATABASE", "clouder")
    monkeypatch.setenv("AURORA_DB_USER", "clouder_migrator")
    monkeypatch.setenv("AURORA_SECRET_ARN", "arn:aws:secretsmanager:::dummy")
    s.reset_settings_cache()

    fake_rds = MagicMock()
    fake_rds.generate_db_auth_token.return_value = "iam-token-value"
    monkeypatch.setattr(mh, "_rds_client", lambda: fake_rds)

    url = mh._build_alembic_database_url()

    assert "iam-token-value" in url
    assert "clouder_migrator" in url
    fake_rds.generate_db_auth_token.assert_called_once_with(
        DBHostname="writer.example",
        Port=5432,
        DBUsername="clouder_migrator",
    )
    s.reset_settings_cache()


def test_password_mode_falls_back_to_secrets_manager(monkeypatch) -> None:
    from collector import migration_handler as mh
    from collector import settings as s

    monkeypatch.setenv("AURORA_AUTH_MODE", "password")
    monkeypatch.setenv("AURORA_WRITER_ENDPOINT", "writer.example")
    monkeypatch.setenv("AURORA_PORT", "5432")
    monkeypatch.setenv("AURORA_DATABASE", "clouder")
    monkeypatch.setenv("AURORA_SECRET_ARN", "arn:aws:secretsmanager:::real")
    s.reset_settings_cache()

    def fake_read_secret(arn: str) -> dict:
        assert arn == "arn:aws:secretsmanager:::real"
        return {"username": "master", "password": "pw"}

    monkeypatch.setattr(mh, "_read_secret", fake_read_secret)

    url = mh._build_alembic_database_url()

    assert "master" in url
    assert "pw" in url
    s.reset_settings_cache()


def test_default_mode_is_password(monkeypatch) -> None:
    from collector import migration_handler as mh
    from collector import settings as s

    monkeypatch.delenv("AURORA_AUTH_MODE", raising=False)
    monkeypatch.setenv("AURORA_WRITER_ENDPOINT", "writer.example")
    monkeypatch.setenv("AURORA_PORT", "5432")
    monkeypatch.setenv("AURORA_DATABASE", "clouder")
    monkeypatch.setenv("AURORA_SECRET_ARN", "arn:aws:secretsmanager:::real")
    s.reset_settings_cache()

    def fake_read_secret(_arn: str) -> dict:
        return {"username": "master", "password": "pw"}

    monkeypatch.setattr(mh, "_read_secret", fake_read_secret)

    url = mh._build_alembic_database_url()
    assert "master" in url
    s.reset_settings_cache()


def test_iam_mode_missing_db_user_raises(monkeypatch) -> None:
    from collector import migration_handler as mh
    from collector import settings as s

    monkeypatch.setenv("AURORA_AUTH_MODE", "iam")
    monkeypatch.setenv("AURORA_WRITER_ENDPOINT", "writer.example")
    monkeypatch.setenv("AURORA_PORT", "5432")
    monkeypatch.setenv("AURORA_DATABASE", "clouder")
    monkeypatch.setenv("AURORA_SECRET_ARN", "arn:aws:secretsmanager:::dummy")
    monkeypatch.delenv("AURORA_DB_USER", raising=False)
    s.reset_settings_cache()

    with pytest.raises(RuntimeError, match="AURORA_DB_USER"):
        mh._build_alembic_database_url()

    s.reset_settings_cache()


def test_password_mode_missing_secret_arn_raises(monkeypatch) -> None:
    from collector import migration_handler as mh
    from collector import settings as s

    monkeypatch.setenv("AURORA_AUTH_MODE", "password")
    monkeypatch.setenv("AURORA_WRITER_ENDPOINT", "writer.example")
    monkeypatch.setenv("AURORA_PORT", "5432")
    monkeypatch.setenv("AURORA_DATABASE", "clouder")
    monkeypatch.delenv("AURORA_SECRET_ARN", raising=False)
    s.reset_settings_cache()

    with pytest.raises(RuntimeError, match="AURORA_SECRET_ARN"):
        mh._build_alembic_database_url()

    s.reset_settings_cache()

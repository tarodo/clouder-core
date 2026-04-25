from __future__ import annotations

import importlib.util
from pathlib import Path


def _load_migration(filename: str):
    path = Path(__file__).resolve().parents[2] / "alembic" / "versions" / filename
    spec = importlib.util.spec_from_file_location("migration_under_test", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _read_source(filename: str) -> str:
    return (
        Path(__file__).resolve().parents[2]
        / "alembic"
        / "versions"
        / filename
    ).read_text()


def test_revision_metadata() -> None:
    mig = _load_migration("20260426_12_user_sessions.py")
    assert mig.revision == "20260426_12"
    assert mig.down_revision == "20260426_11"


def test_upgrade_creates_user_sessions_table() -> None:
    src = _read_source("20260426_12_user_sessions.py")
    assert 'create_table(\n        "user_sessions"' in src
    assert '"refresh_token_hash"' in src
    assert '"revoked_at"' in src
    assert "idx_user_sessions_user" in src
    assert "idx_user_sessions_expires" in src
    assert 'ForeignKeyConstraint(["user_id"], ["users.id"])' in src

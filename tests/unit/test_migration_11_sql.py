"""Test that the users migration creates the expected schema."""

from __future__ import annotations

import importlib.util
from pathlib import Path


def _load_migration_module():
    path = Path("alembic/versions/20260426_11_users.py")
    spec = importlib.util.spec_from_file_location("mig11", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_revision_metadata() -> None:
    mig = _load_migration_module()
    assert mig.revision == "20260426_11"
    assert mig.down_revision == "20260421_10"


def test_upgrade_creates_users_table() -> None:
    mig = _load_migration_module()
    src = Path("alembic/versions/20260426_11_users.py").read_text()
    assert 'create_table(\n        "users"' in src
    assert '"spotify_id"' in src
    assert '"is_admin"' in src
    assert "idx_users_spotify_id" in src
    assert "unique=True" in src

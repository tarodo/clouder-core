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
    mig = _load_migration("20260426_13_user_vendor_tokens.py")
    assert mig.revision == "20260426_13"
    assert mig.down_revision == "20260426_12"


def test_upgrade_creates_user_vendor_tokens_table() -> None:
    src = _read_source("20260426_13_user_vendor_tokens.py")
    assert 'create_table(\n        "user_vendor_tokens"' in src
    assert '"access_token_enc"' in src
    assert '"refresh_token_enc"' in src
    assert '"data_key_enc"' in src
    assert 'PrimaryKeyConstraint("user_id", "vendor"' in src
    assert 'ForeignKeyConstraint(["user_id"], ["users.id"])' in src

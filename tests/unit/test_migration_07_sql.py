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


def test_migration_07_revision_chain() -> None:
    module = _load_migration("20260419_07_bootstrap_iam_auth.py")
    assert module.revision == "20260419_07"
    assert module.down_revision == "20260315_06"


def test_migration_07_creates_role_and_grants_rds_iam() -> None:
    path = (
        Path(__file__).resolve().parents[2]
        / "alembic"
        / "versions"
        / "20260419_07_bootstrap_iam_auth.py"
    )
    text = path.read_text()
    assert "clouder_migrator" in text
    assert "rds_iam" in text
    assert "LOGIN" in text or "CREATE USER" in text

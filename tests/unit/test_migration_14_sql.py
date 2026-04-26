# tests/unit/test_migration_14_sql.py
"""Test that the categories migration creates the expected schema."""

from __future__ import annotations

import importlib.util
from pathlib import Path


def _load_migration_module():
    path = Path("alembic/versions/20260427_14_categories.py")
    spec = importlib.util.spec_from_file_location("mig14", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_revision_metadata() -> None:
    mig = _load_migration_module()
    assert mig.revision == "20260427_14"
    assert mig.down_revision == "20260426_13"


def test_upgrade_creates_categories_table() -> None:
    src = Path("alembic/versions/20260427_14_categories.py").read_text()
    assert 'create_table(\n        "categories"' in src
    assert '"normalized_name"' in src
    assert '"position"' in src
    assert '"deleted_at"' in src
    assert "uq_categories_user_style_normname" in src
    assert "deleted_at IS NULL" in src
    assert "idx_categories_user_style_position" in src
    assert "idx_categories_user_created" in src


def test_upgrade_creates_category_tracks_table() -> None:
    src = Path("alembic/versions/20260427_14_categories.py").read_text()
    assert 'create_table(\n        "category_tracks"' in src
    assert '"source_triage_block_id"' in src
    assert "PrimaryKeyConstraint(\"category_id\", \"track_id\")" in src
    assert "idx_category_tracks_category_added" in src


def test_no_fk_on_source_triage_block_id() -> None:
    """spec-D adds the FK; spec-C must not."""
    src = Path("alembic/versions/20260427_14_categories.py").read_text()
    # No FK constraint targeting triage_blocks in this migration.
    assert "triage_blocks" not in src

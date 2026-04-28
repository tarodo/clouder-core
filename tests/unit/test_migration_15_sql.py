"""Test that the triage migration creates the expected schema."""

from __future__ import annotations

import importlib.util
from pathlib import Path


def _load_migration_module():
    path = Path("alembic/versions/20260428_15_triage.py")
    spec = importlib.util.spec_from_file_location("mig15", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_revision_metadata() -> None:
    mig = _load_migration_module()
    assert mig.revision == "20260428_15"
    assert mig.down_revision == "20260427_14"


def test_upgrade_creates_triage_blocks() -> None:
    src = Path("alembic/versions/20260428_15_triage.py").read_text()
    assert 'create_table(\n        "triage_blocks"' in src
    assert "ck_triage_blocks_date_range" in src
    assert "ck_triage_blocks_status" in src
    assert "idx_triage_blocks_user_style_status" in src
    assert "idx_triage_blocks_user_created" in src


def test_upgrade_creates_triage_buckets() -> None:
    src = Path("alembic/versions/20260428_15_triage.py").read_text()
    assert 'create_table(\n        "triage_buckets"' in src
    assert "ck_triage_buckets_type" in src
    assert "ck_triage_buckets_staging_category" in src
    assert "uq_triage_buckets_block_category" in src
    assert "uq_triage_buckets_block_type_tech" in src
    # FK to categories must be RESTRICT not SET NULL (would break CHECK)
    assert 'ondelete="RESTRICT"' in src
    # FK to triage_blocks must CASCADE (hard-delete chain)
    assert 'ondelete="CASCADE"' in src


def test_upgrade_creates_triage_bucket_tracks() -> None:
    src = Path("alembic/versions/20260428_15_triage.py").read_text()
    assert 'create_table(\n        "triage_bucket_tracks"' in src
    assert 'PrimaryKeyConstraint("triage_bucket_id", "track_id")' in src
    assert "idx_triage_bucket_tracks_bucket_added" in src


def test_upgrade_adds_spotify_release_date() -> None:
    src = Path("alembic/versions/20260428_15_triage.py").read_text()
    assert 'add_column(\n        "clouder_tracks"' in src
    assert "spotify_release_date" in src
    assert "idx_tracks_spotify_release_date" in src


def test_upgrade_adds_deferred_fk_from_spec_c() -> None:
    src = Path("alembic/versions/20260428_15_triage.py").read_text()
    assert "fk_category_tracks_source_triage_block" in src
    assert 'ondelete="SET NULL"' in src


def test_upgrade_grants_to_clouder_app() -> None:
    src = Path("alembic/versions/20260428_15_triage.py").read_text()
    for table in ("triage_blocks", "triage_buckets", "triage_bucket_tracks"):
        assert f"GRANT SELECT, INSERT, UPDATE, DELETE ON {table}" in src

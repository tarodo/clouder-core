"""Test that the user style prefs migration creates the expected schema."""

from __future__ import annotations

import importlib.util
from pathlib import Path

_PATH = Path("alembic/versions/20260920_32_user_style_prefs.py")


def _load_migration_module():
    spec = importlib.util.spec_from_file_location("mig32", _PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_revision_metadata() -> None:
    mig = _load_migration_module()
    assert mig.revision == "20260920_32"
    assert mig.down_revision == "20260621_31"


def test_upgrade_creates_user_style_prefs() -> None:
    src = _PATH.read_text()
    assert 'create_table(\n        "clouder_user_style_prefs"' in src
    assert "pk_user_style_prefs" in src
    assert "idx_user_style_prefs_user_position" in src
    assert "ck_user_style_prefs_position_nonneg" in src
    # Both FKs cascade: dropping a user or a style must not strand pref rows.
    assert src.count('ondelete="CASCADE"') == 2
    # Check constraint must enforce non-negative position (0 is valid).
    assert '"position >= 0"' in src
    # Each FK bound to its correct table.
    assert '["user_id"], ["users.id"]' in src
    assert '["style_id"], ["clouder_styles.id"]' in src
    # Index includes both columns in correct order.
    assert '["user_id", "position"]' in src


def test_downgrade_drops_everything() -> None:
    src = _PATH.read_text()
    assert 'drop_index(\n        "idx_user_style_prefs_user_position"' in src
    assert 'drop_table("clouder_user_style_prefs")' in src

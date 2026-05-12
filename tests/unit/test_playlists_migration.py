"""Sanity check that migration 19 has a clean revision chain."""
from __future__ import annotations

import importlib.util
from pathlib import Path


def _load_migration(filename: str):
    path = Path(__file__).resolve().parents[2] / "alembic" / "versions" / filename
    spec = importlib.util.spec_from_file_location(filename, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_migration_19_chain() -> None:
    m = _load_migration("20260512_19_playlists.py")
    assert m.revision == "20260512_19"
    assert m.down_revision == "20260511_18"


def test_migration_19_upgrade_downgrade_callable() -> None:
    m = _load_migration("20260512_19_playlists.py")
    assert callable(m.upgrade)
    assert callable(m.downgrade)

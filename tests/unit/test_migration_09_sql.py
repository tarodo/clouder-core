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


def test_migration_09_revision_chain() -> None:
    module = _load_migration("20260420_09_release_type_and_ai_flag.py")
    assert module.revision == "20260420_09"
    assert module.down_revision == "20260419_08"


def test_migration_09_adds_expected_columns() -> None:
    path = (
        Path(__file__).resolve().parents[2]
        / "alembic"
        / "versions"
        / "20260420_09_release_type_and_ai_flag.py"
    )
    text = path.read_text()
    assert "clouder_tracks" in text and "release_type" in text
    assert "clouder_tracks" in text and "is_ai_suspected" in text
    assert "clouder_albums" in text and "release_type" in text
    assert "clouder_labels" in text and "is_ai_suspected" in text
    assert "clouder_artists" in text and "is_ai_suspected" in text

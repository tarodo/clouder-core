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


def test_migration_10_revision_chain() -> None:
    module = _load_migration("20260421_10_vendor_match_tables.py")
    assert module.revision == "20260421_10"
    assert module.down_revision == "20260420_09"


def test_migration_10_creates_tables() -> None:
    text = (
        Path(__file__).resolve().parents[2]
        / "alembic"
        / "versions"
        / "20260421_10_vendor_match_tables.py"
    ).read_text()
    for token in [
        "vendor_track_map",
        "match_review_queue",
        "clouder_track_id",
        "vendor_track_id",
        "match_type",
        "confidence",
        "candidates",
        "status",
        "pending",
        "idx_vtm_vendor_track",
        "uq_review_pending",
    ]:
        assert token in text, f"expected {token!r} in migration"

"""The keyset export SQL on real PostgreSQL: every row once, composite keys included."""

from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path

from collector.catalog_export_handler import _EXPORTS, export_catalog

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "demo_pipeline.py"


class FakeS3:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    def put_object(self, **kw):
        self.objects[kw["Key"]] = kw["Body"]
        return {}


def _fill(dsn: str) -> None:
    spec = importlib.util.spec_from_file_location("demo_pipeline", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.run(dsn, tracks=60)


def test_every_row_exported_once_with_small_pages(pg) -> None:
    _fill(os.environ["TEST_DATABASE_URL"])
    s3 = FakeS3()

    counts = export_catalog(pg, s3, "lake", "2026-10-11", page=7)

    for table, _, keys in _EXPORTS:
        expected = pg.execute(f"SELECT count(*) AS n FROM {table}")[0]["n"]
        rows = [
            json.loads(line)
            for key, body in s3.objects.items()
            if f"/{table}/" in key
            for line in body.decode().splitlines()
        ]
        assert counts[table] == expected == len(rows), table
        assert len({tuple(r[k] for k in keys) for r in rows}) == len(rows), table
    assert counts["clouder_tracks"] == 60
    assert counts["clouder_track_artists"] > 60  # several artists per track: composite key paged

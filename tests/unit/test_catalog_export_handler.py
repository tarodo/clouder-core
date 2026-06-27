import ast
import json
import pathlib
from datetime import date, datetime, timezone

import collector.catalog_export_handler as ceh
from collector.catalog_export_handler import export_catalog


class FakeS3:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    def put_object(self, **kw):
        self.objects[kw["Key"]] = kw["Body"]
        return {}


class FakeDataAPI:
    """Mimics DataAPIClient.execute with offset paging over canned rows."""

    def __init__(self, rows_by_table: dict[str, list[dict]]) -> None:
        self.rows_by_table = rows_by_table
        self.calls: list[tuple[str, dict]] = []

    def execute(self, sql, params=None, transaction_id=None):
        self.calls.append((sql, params))
        table = next(t for t in self.rows_by_table if f"FROM {t} " in sql)
        off, lim = params["offset"], params["limit"]
        return self.rows_by_table[table][off : off + lim]


def _empty_tables(except_for: dict[str, list[dict]]) -> dict[str, list[dict]]:
    tables = [
        "clouder_tracks", "clouder_artists", "clouder_track_artists",
        "clouder_labels", "clouder_albums", "categories", "category_tracks",
    ]
    out = {t: [] for t in tables}
    out.update(except_for)
    return out


def test_paging_writes_one_ndjson_part_per_page() -> None:
    tracks = [{"id": f"t{i}", "title": f"T{i}"} for i in range(5)]
    api = FakeDataAPI(_empty_tables({"clouder_tracks": tracks}))
    s3 = FakeS3()

    counts = export_catalog(api, s3, "lake", "2026-06-27", page=2)

    assert counts["clouder_tracks"] == 5
    keys = sorted(k for k in s3.objects if "clouder_tracks" in k)
    assert keys == [
        "bronze/catalog_export/snapshot_dt=2026-06-27/clouder_tracks/part-00000.json",
        "bronze/catalog_export/snapshot_dt=2026-06-27/clouder_tracks/part-00001.json",
        "bronze/catalog_export/snapshot_dt=2026-06-27/clouder_tracks/part-00002.json",
    ]
    assert s3.objects[keys[0]].decode().count("\n") == 2  # full page
    assert s3.objects[keys[2]].decode().count("\n") == 1  # leftover row


def test_default_page_is_data_api_safe() -> None:
    # The wired default page size must stay under the RDS Data API ~1MB
    # per-ExecuteStatement response cap for wide dims (clouder_tracks ~15 cols).
    # A 5000-row page of a wide dim would risk "Database response exceeded size
    # limit" at runtime; this pins the default so the green suite means the
    # production page size is actually checked, not just the page=2 test path.
    assert 0 < ceh._PAGE <= 1000


def test_empty_table_writes_no_object() -> None:
    api = FakeDataAPI(_empty_tables({}))
    s3 = FakeS3()

    counts = export_catalog(api, s3, "lake", "2026-06-27", page=2)

    assert counts == {
        "clouder_tracks": 0, "clouder_artists": 0, "clouder_track_artists": 0,
        "clouder_labels": 0, "clouder_albums": 0, "categories": 0,
        "category_tracks": 0,
    }
    assert s3.objects == {}


def test_ndjson_serializes_dates_via_default_str() -> None:
    rows = [{"id": "t1", "created_at": datetime(2026, 6, 27, tzinfo=timezone.utc),
             "publish_date": date(2026, 6, 1)}]
    api = FakeDataAPI(_empty_tables({"clouder_tracks": rows}))
    s3 = FakeS3()

    export_catalog(api, s3, "lake", "2026-06-27", page=10)

    key = "bronze/catalog_export/snapshot_dt=2026-06-27/clouder_tracks/part-00000.json"
    parsed = json.loads(s3.objects[key].decode().splitlines()[0])
    assert parsed["publish_date"] == "2026-06-01"
    assert parsed["created_at"].startswith("2026-06-27")


def test_categories_query_selects_deleted_at() -> None:
    # deleted_at must be exported so dbt can filter soft-deletes (recon gotcha).
    assert "deleted_at" in dict(ceh._EXPORTS)["categories"]


def test_no_psycopg_or_columnar_imports() -> None:
    tree = ast.parse(pathlib.Path(ceh.__file__).read_text())
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    assert imported & {
        "psycopg", "psycopg2", "pyarrow", "awswrangler", "pandas"
    } == set()

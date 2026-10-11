import ast
import json
import pathlib
from datetime import UTC, date, datetime

import collector.catalog_export_handler as ceh
from collector.catalog_export_handler import export_catalog


class FakeS3:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    def put_object(self, **kw):
        self.objects[kw["Key"]] = kw["Body"]
        return {}


class FakeDataAPI:
    """Mimics DataAPIClient.execute for keyset pages: WHERE (keys) > (:k0, …) ORDER BY keys."""

    def __init__(self, rows_by_table: dict[str, list[dict]]) -> None:
        self.rows_by_table = rows_by_table
        self.calls: list[tuple[str, dict]] = []
        self.after_call = None  # hook: (table, n_calls) -> None, to mutate rows mid-export

    def execute(self, sql, params=None, transaction_id=None):
        self.calls.append((sql, params))
        table = next(t for t in self.rows_by_table if f"FROM {t} " in sql)
        keys = next(k for t, _, k in ceh._EXPORTS if t == table)
        rows = sorted(self.rows_by_table[table], key=lambda r: tuple(r[k] for k in keys))
        if "WHERE" in sql:
            after = tuple(params[f"k{i}"] for i in range(len(keys)))
            rows = [r for r in rows if tuple(r[k] for k in keys) > after]
        page = rows[: params["limit"]]
        if self.after_call:
            self.after_call(table, len(self.calls))
        return page


def _empty_tables(except_for: dict[str, list[dict]]) -> dict[str, list[dict]]:
    tables = [
        "clouder_tracks",
        "clouder_artists",
        "clouder_track_artists",
        "clouder_labels",
        "clouder_albums",
        "categories",
        "category_tracks",
        "clouder_styles",
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
        "clouder_tracks": 0,
        "clouder_artists": 0,
        "clouder_track_artists": 0,
        "clouder_labels": 0,
        "clouder_albums": 0,
        "categories": 0,
        "category_tracks": 0,
        "clouder_styles": 0,
    }
    assert s3.objects == {}


def test_ndjson_serializes_dates_via_default_str() -> None:
    rows = [
        {
            "id": "t1",
            "created_at": datetime(2026, 6, 27, tzinfo=UTC),
            "publish_date": date(2026, 6, 1),
        }
    ]
    api = FakeDataAPI(_empty_tables({"clouder_tracks": rows}))
    s3 = FakeS3()

    export_catalog(api, s3, "lake", "2026-06-27", page=10)

    key = "bronze/catalog_export/snapshot_dt=2026-06-27/clouder_tracks/part-00000.json"
    parsed = json.loads(s3.objects[key].decode().splitlines()[0])
    assert parsed["publish_date"] == "2026-06-01"
    assert parsed["created_at"].startswith("2026-06-27")


def test_categories_query_selects_deleted_at() -> None:
    # deleted_at must be exported so dbt can filter soft-deletes (recon gotcha).
    columns = next(c for t, c, _ in ceh._EXPORTS if t == "categories")
    assert "deleted_at" in columns


def test_no_psycopg_or_columnar_imports() -> None:
    tree = ast.parse(pathlib.Path(ceh.__file__).read_text())
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    assert imported & {"psycopg", "psycopg2", "pyarrow", "awswrangler", "pandas"} == set()


def test_exported_tables_match_glue_tbl_enum():
    # A table missing from the Glue projection enum is written to S3 but
    # invisible to Athena — keep the two lists identical.
    import pathlib
    import re

    from collector.catalog_export_handler import _EXPORTS

    tf = (pathlib.Path(__file__).resolve().parents[2] / "infra" / "analytics_export.tf").read_text()
    enum = re.search(r'"projection\.tbl\.values"\s*=\s*"([^"]+)"', tf).group(1)
    assert set(enum.split(",")) == {t for t, _, _ in _EXPORTS}


def test_pages_by_key_never_by_offset() -> None:
    tracks = [{"id": f"t{i}", "title": f"T{i}"} for i in range(5)]
    api = FakeDataAPI(_empty_tables({"clouder_tracks": tracks}))

    export_catalog(api, FakeS3(), "lake", "2026-10-11", page=2)

    track_calls = [(sql, p) for sql, p in api.calls if "FROM clouder_tracks " in sql]
    assert all("OFFSET" not in sql for sql, _ in api.calls)
    assert "WHERE" not in track_calls[0][0]
    assert track_calls[1][1] == {"limit": 2, "k0": "t1"}  # last id of page one
    assert track_calls[2][1] == {"limit": 2, "k0": "t3"}


def test_composite_keys_compare_every_key_column() -> None:
    rows = [
        {"track_id": "a", "artist_id": "x", "role": "main"},
        {"track_id": "a", "artist_id": "x", "role": "remixer"},
        {"track_id": "a", "artist_id": "y", "role": "main"},
        {"track_id": "b", "artist_id": "x", "role": "main"},
    ]
    api = FakeDataAPI(_empty_tables({"clouder_track_artists": rows}))

    counts = export_catalog(api, FakeS3(), "lake", "2026-10-11", page=1)

    assert counts["clouder_track_artists"] == 4
    sql = next(s for s, p in api.calls if "FROM clouder_track_artists " in s and "WHERE" in s)
    assert "(track_id, artist_id, role) > (:k0, :k1, :k2)" in sql
    assert "ORDER BY track_id, artist_id, role" in sql


def test_rows_deleted_mid_export_are_not_skipped() -> None:
    # OFFSET paging skips a row when an earlier one is deleted between pages.
    tracks = [{"id": f"t{i}"} for i in range(6)]
    api = FakeDataAPI(_empty_tables({"clouder_tracks": tracks}))

    def delete_first_after_page_one(table, n_calls):
        if table == "clouder_tracks" and n_calls == 1:
            api.rows_by_table["clouder_tracks"].pop(0)  # t0, already exported

    api.after_call = delete_first_after_page_one
    s3 = FakeS3()

    export_catalog(api, s3, "lake", "2026-10-11", page=2)

    exported = [
        json.loads(line)["id"]
        for key in sorted(k for k in s3.objects if "clouder_tracks" in k)
        for line in s3.objects[key].decode().splitlines()
    ]
    assert exported == ["t0", "t1", "t2", "t3", "t4", "t5"]


def test_table_timing_survives_the_log_allow_list() -> None:
    import collector.logging_utils as lu

    for field in ("table_name", "total_count", "api_pages_fetched", "duration_ms"):
        assert field in lu.ALLOWED_LOG_FIELDS, field

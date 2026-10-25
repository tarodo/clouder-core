from __future__ import annotations

import pytest

from collector import user_export

UID = "11111111-1111-1111-1111-111111111111"
HEX = "11111111111111111111111111111111"  # users.id: auth mints uuid4().hex


def test_credentials_are_redacted() -> None:
    row = {
        "user_id": UID,
        "access_token_enc": b"x",
        "refresh_token_hash": "h",
        "data_key_enc": b"k",
        "scope": "playlist-read",
    }
    out = user_export.redact(row)
    assert out["access_token_enc"] == out["refresh_token_hash"] == out["data_key_enc"]
    assert out["access_token_enc"] == "[redacted]"
    assert out["scope"] == "playlist-read" and out["user_id"] == UID


class FakeAthena:
    def __init__(self, pages):
        self.pages = pages
        self.queries = []

    def start_query_execution(self, **kw):
        self.queries.append(kw)
        return {"QueryExecutionId": "q"}

    def get_query_execution(self, QueryExecutionId):
        return {"QueryExecution": {"Status": {"State": "SUCCEEDED"}}}

    def get_query_results(self, QueryExecutionId, NextToken=None, MaxResults=1000):
        i = int(NextToken or 0)
        nxt = i + 1
        extra = {"NextToken": str(nxt)} if nxt < len(self.pages) else {}
        return {"ResultSet": {"Rows": self.pages[i]}, **extra}


def _row(*values):
    return {"Data": [{"VarCharValue": v} for v in values]}


def test_events_page_through_athena_results() -> None:
    athena = FakeAthena(
        [
            [_row("event_id", "event_name"), _row("e1", "playback_play")],
            [_row("e2", "playback_pause")],
        ]
    )

    rows = user_export.export_events(athena, user_id=UID, workgroup="wg", sleep=lambda s: None)

    assert rows == [
        {"event_id": "e1", "event_name": "playback_play"},
        {"event_id": "e2", "event_name": "playback_pause"},
    ]
    sql = athena.queries[0]["QueryString"]
    assert f"user_id = '{HEX}'" in sql and "clouder_silver.events" in sql  # telemetry's spelling
    assert athena.queries[0]["WorkGroup"] == "wg"


def test_a_non_uuid_never_reaches_sql() -> None:
    with pytest.raises(ValueError):
        user_export.export_events(FakeAthena([[]]), user_id="x' OR '1'='1", workgroup="wg")


def _script():
    import importlib.util
    from pathlib import Path

    path = Path(__file__).resolve().parents[2] / "scripts" / "export_user.py"
    spec = importlib.util.spec_from_file_location("export_user", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_cli_writes_a_private_file_and_prints_no_personal_data(tmp_path, monkeypatch, capsys):
    import json
    import stat

    mod = _script()
    monkeypatch.setattr(mod, "export_aurora", lambda db, uid: {"users": [{"email": "me@x.io"}]})
    monkeypatch.setattr(mod, "list_covers", lambda s3, bucket, uid: ["covers/a/1.jpg"])
    monkeypatch.setattr(mod, "export_events", lambda athena, **kw: [{"event_id": "e1"}])
    out = tmp_path / "export.json"

    code = mod.main(
        [
            "--user-id",
            UID,
            "--out",
            str(out),
            "--cluster-arn",
            "c",
            "--secret-arn",
            "s",
            "--raw-bucket",
            "raw",
        ],
        db=object(),
        s3=object(),
        athena=object(),
    )

    assert code == 0
    assert stat.S_IMODE(out.stat().st_mode) == 0o600
    data = json.loads(out.read_text())
    assert data["user_id"] == HEX and data["aurora"]["users"][0]["email"] == "me@x.io"
    assert data["covers"] == ["covers/a/1.jpg"] and data["events"] == [{"event_id": "e1"}]
    printed = capsys.readouterr().out
    assert "me@x.io" not in printed and str(out) in printed


class CappedDataAPI:
    """Serves the catalog queries and pages one user table; fails like the Data API's 1 MiB
    cap on any read that would return more than 600 rows."""

    def __init__(self, user_tags: int, fks=()):
        self.rows = [{"id": f"t{i}", "user_id": UID} for i in range(user_tags)]
        self.fks = list(fks)
        self.statements: list[str] = []
        self.rolled_back = False

    def begin_transaction(self):
        return "tx"

    def rollback_transaction(self, tx):
        self.rolled_back = True

    def execute(self, sql, params=None, transaction_id=None):
        self.statements.append(sql)
        if "pg_constraint" in sql:
            return self.fks
        if "information_schema.columns" in sql:
            return [{"tbl": "user_tags", "col": "user_id"}]
        if sql.startswith("SET TRANSACTION"):
            return []
        if 'FROM "users"' in sql:
            return [{"id": UID}]
        if 'FROM "user_tags"' in sql:
            if "LIMIT" not in sql:
                rows = self.rows
            else:
                rows = self.rows[params["offset"] : params["offset"] + params["limit"]]
            if len(rows) > 600:
                raise RuntimeError("Database response exceeded size limit")
            return rows
        raise AssertionError(sql)


def test_export_pages_under_the_data_api_cap() -> None:
    db = CappedDataAPI(user_tags=1300)

    out = user_export.export_aurora(db, UID)

    assert len(out["user_tags"]) == 1300
    assert db.statements[0].startswith("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
    assert db.rolled_back  # read-only: nothing to commit


def test_a_multi_column_foreign_key_is_refused() -> None:
    # delete_user refuses them too: a silently incomplete export is worse than none.
    fk = {
        "child": "c",
        "child_col": "a",
        "parent": "users",
        "parent_col": "id",
        "on_delete": "c",
        "width": 2,
    }
    with pytest.raises(RuntimeError, match="multi-column"):
        user_export.export_aurora(CappedDataAPI(user_tags=1, fks=[fk]), UID)


class CatalogDB:
    def __init__(self):
        self.queries = []

    def execute(self, sql, params=None, transaction_id=None):
        self.queries.append((sql, params))
        ids = sorted(v for k, v in (params or {}).items() if k.startswith("i"))
        if "FROM clouder_tracks" in sql:
            return [{"id": i, "title": f"T {i}", "isrc": None, "artists": "A"} for i in ids]
        return [{"id": i, "name": f"N {i}"} for i in ids]


def test_catalog_names_the_ids_in_the_export() -> None:
    export = {
        "playlist_tracks": [{"playlist_id": "p", "track_id": "tr1"}],
        "track_tags": [{"track_id": "tr2", "tag_id": "g"}],
        "clouder_user_artist_prefs": [{"artist_id": "ar1"}],
        "clouder_user_label_prefs": [{"label_id": "lb1"}],
        "categories": [{"style_id": "st1"}],
    }

    catalog = user_export.resolve_catalog(CatalogDB(), export)

    assert set(catalog["tracks"]) == {"tr1", "tr2"} and catalog["tracks"]["tr1"]["title"] == "T tr1"
    assert catalog["artists"] == {"ar1": "N ar1"}
    assert catalog["labels"] == {"lb1": "N lb1"} and catalog["styles"] == {"st1": "N st1"}


def test_cli_refuses_an_existing_file_before_reading_anything(tmp_path, monkeypatch) -> None:
    mod = _script()
    called = []
    monkeypatch.setattr(mod, "export_aurora", lambda *a: called.append(1) or {})
    out = tmp_path / "export.json"
    out.write_text("old")

    code = mod.main(
        [
            "--user-id",
            UID,
            "--out",
            str(out),
            "--cluster-arn",
            "c",
            "--secret-arn",
            "s",
            "--raw-bucket",
            "raw",
        ],
        db=object(),
        s3=object(),
        athena=object(),
    )

    assert code == 2 and not called and out.read_text() == "old"

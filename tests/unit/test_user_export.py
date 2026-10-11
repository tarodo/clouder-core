from __future__ import annotations

import pytest

from collector import user_export

UID = "11111111-1111-1111-1111-111111111111"


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
    assert f"user_id = '{UID}'" in sql and "clouder_silver.events" in sql
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
    assert data["user_id"] == UID and data["aurora"]["users"][0]["email"] == "me@x.io"
    assert data["covers"] == ["covers/a/1.jpg"] and data["events"] == [{"event_id": "e1"}]
    printed = capsys.readouterr().out
    assert "me@x.io" not in printed and str(out) in printed

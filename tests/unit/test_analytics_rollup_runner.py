from __future__ import annotations

import datetime as dt
from unittest.mock import MagicMock

import pytest

from collector import analytics_rollup_runner as r


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("ATHENA_DATABASE", "clouder_analytics")
    monkeypatch.setenv("ATHENA_WORKGROUP", "wg")
    monkeypatch.setenv("ATHENA_OUTPUT_LOCATION", "s3://lake/athena-results/")
    monkeypatch.setenv("ANALYTICS_LAKE_BUCKET", "lake")


def _athena_ok():
    a = MagicMock()
    a.start_query_execution.return_value = {"QueryExecutionId": "q1"}
    a.get_query_execution.return_value = {"QueryExecution": {"Status": {"State": "SUCCEEDED"}}}
    return a


def test_target_dts_are_last_3_days():
    assert r._target_dts(dt.date(2026, 6, 30)) == ["2026-06-28", "2026-06-29", "2026-06-30"]


def test_lookback_start_is_one_day_before_window():
    assert r._lookback_start(dt.date(2026, 6, 30)) == "2026-06-27"


def test_run_overwrites_partitions_then_inserts():
    athena, s3 = _athena_ok(), MagicMock()
    s3.list_objects_v2.return_value = {"Contents": [{"Key": "marts/mart_user_daily/dt=2026-06-30/f.parquet"}]}
    r.run(dt.date(2026, 6, 30), athena_client=athena, s3_client=s3)

    # S3 partitions deleted before insert: 2 tables x 3 dts = 6 prefixes listed
    assert s3.list_objects_v2.call_count == 6
    assert s3.delete_objects.called
    # one INSERT per table (2), each mentioning INSERT INTO + a validated date + WHERE dt IN
    inserts = [c.kwargs["QueryString"] for c in athena.start_query_execution.call_args_list]
    assert len(inserts) == 2
    for q in inserts:
        assert q.strip().upper().startswith("INSERT INTO")
        # dt is a date-typed column: filters MUST use DATE literals. Trino will
        # not coerce date <-> varchar in an IN list (DuckDB silently would, which
        # is why the SQL tests missed this) — a bare-string IN fails at runtime.
        assert "DATE '2026-06-30'" in q          # target dt as DATE literal
        assert "DATE '2026-06-27'" in q          # lookback as DATE literal
        assert "IN ('2026-06-30'" not in q       # regression: no bare-string IN
        assert "?" not in q                       # no bound params (gotcha #13)


def test_bad_date_never_reaches_sql():
    # dates are Python-formatted, never user input — but assert the guard exists
    with pytest.raises(ValueError):
        r._validate_dt("2026-6-30")  # not zero-padded / not YYYY-MM-DD

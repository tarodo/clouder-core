"""Scheduled rollup runner: daily Athena INSERT INTO for fact_session + mart_user_daily.

Idempotent: deletes the last 3 dt partitions' S3 objects before each INSERT.
Bronze scan window is today-3 (4 days) to capture cross-midnight sessions.
All dates are inlined as validated literals — never bound via ExecutionParameters
(Athena mis-parses bound date strings as arithmetic; see gotcha #13).
"""
from __future__ import annotations

import os
import re
import time
from datetime import date, datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any

import boto3

from collector.analytics_rollup import (
    FACT_SESSION_COLUMNS,
    MART_USER_DAILY_COLUMNS,
    TRINO,
    mart_sql,
    sessions_sql,
)

if TYPE_CHECKING:
    pass

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _validate_dt(d: str) -> str:
    if not _DATE_RE.match(d):
        raise ValueError(f"Invalid date literal: {d!r} — must be YYYY-MM-DD with zero-padding")
    return d


def _target_dts(today: date) -> list[str]:
    """Return [today-2, today-1, today] as validated YYYY-MM-DD strings."""
    return [_validate_dt((today - timedelta(days=i)).strftime("%Y-%m-%d")) for i in (2, 1, 0)]


def _lookback_start(today: date) -> str:
    """Bronze scan start: today-3 (4-day window covers cross-midnight sessions)."""
    return _validate_dt((today - timedelta(days=3)).strftime("%Y-%m-%d"))


def _delete_partition(s3: Any, bucket: str, prefix: str) -> None:
    """Delete all S3 objects under prefix (paginated)."""
    kwargs: dict[str, Any] = {"Bucket": bucket, "Prefix": prefix}
    while True:
        resp = s3.list_objects_v2(**kwargs)
        keys = [o["Key"] for o in resp.get("Contents", [])]
        if keys:
            s3.delete_objects(
                Bucket=bucket,
                Delete={"Objects": [{"Key": k} for k in keys]},
            )
        if not resp.get("NextContinuationToken"):
            break
        kwargs["ContinuationToken"] = resp["NextContinuationToken"]


def _execute(athena: Any, sql: str) -> None:
    """Start an Athena query and poll until terminal state (no result fetch needed)."""
    started = athena.start_query_execution(
        QueryString=sql,
        QueryExecutionContext={"Database": os.environ["ATHENA_DATABASE"]},
        WorkGroup=os.environ["ATHENA_WORKGROUP"],
        ResultConfiguration={"OutputLocation": os.environ["ATHENA_OUTPUT_LOCATION"]},
    )
    qid = started["QueryExecutionId"]
    state = "QUEUED"
    for _ in range(240):
        ex = athena.get_query_execution(QueryExecutionId=qid)
        state = ex["QueryExecution"]["Status"]["State"]
        if state in ("SUCCEEDED", "FAILED", "CANCELLED"):
            break
        time.sleep(1)
    if state != "SUCCEEDED":
        raise RuntimeError(f"Athena INSERT failed with state {state} (query {qid})")


def create_default_athena_client() -> Any:
    return boto3.client("athena")


def create_default_s3_client() -> Any:
    return boto3.client("s3")


def run(today: date, *, athena_client: Any = None, s3_client: Any = None) -> None:
    athena = athena_client or create_default_athena_client()
    s3 = s3_client or create_default_s3_client()
    bucket = os.environ["ANALYTICS_LAKE_BUCKET"]

    dts = _target_dts(today)
    lookback = _lookback_start(today)
    # `dt` is a STRING partition in every analytics table (bronze + marts), matching
    # the serving layer's string-literal filters; the builders emit dt as varchar.
    # So compare against bare validated 'YYYY-MM-DD' literals — NOT DATE literals
    # (Trino won't compare varchar <-> date). Dates are validated, safe to inline (gotcha #13).
    source = f"(SELECT * FROM bronze_events WHERE dt >= '{lookback}')"
    dt_list = ", ".join(f"'{d}'" for d in dts)

    targets = [
        ("mart_user_daily", mart_sql(TRINO, source=source), MART_USER_DAILY_COLUMNS),
        ("fact_session",    sessions_sql(TRINO, source=source), FACT_SESSION_COLUMNS),
    ]
    for table, builder_sql_str, cols in targets:
        for d in dts:
            _delete_partition(s3, bucket, f"marts/{table}/dt={d}/")
        select = ", ".join(cols) + ", dt"
        insert = (
            f"INSERT INTO {table} "
            f"SELECT {select} FROM ({builder_sql_str}) WHERE dt IN ({dt_list})"
        )
        _execute(athena, insert)


def lambda_handler(event: Any, context: Any) -> dict[str, Any]:
    del event, context
    run(datetime.now(timezone.utc).date())
    return {"ok": True}

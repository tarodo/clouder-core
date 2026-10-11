"""Everything CLOUDER holds about one user, for an access or portability request.

Walks the same catalog-derived table graph as user_deletion (every `*user_id`
column, foreign-key children), so a new user-owned table is exported without code
changes. Credential columns are redacted: the export is for the person, not a key
backup. Adds the user's playlist cover keys and their telemetry from silver.
"""

from __future__ import annotations

import json
import re
import time
from collections.abc import Callable
from typing import Any

from collector.user_deletion import _FOREIGN_KEYS_SQL, _USER_COLUMNS_SQL, _checked

_SECRET = re.compile(r"(_enc$|token|hash|secret|password)")


def redact(row: dict[str, Any]) -> dict[str, Any]:
    return {k: ("[redacted]" if _SECRET.search(k) else v) for k, v in row.items()}


def export_aurora(data_api: Any, user_id: str) -> dict[str, list[dict[str, Any]]]:
    """Rows per table (children included); `table.column` keys hold audit references."""
    children: dict[str, list[tuple[str, str, str]]] = {}
    for fk in data_api.execute(_FOREIGN_KEYS_SQL):
        if fk["width"] == 1 and fk["on_delete"] != "n":
            children.setdefault(fk["parent"], []).append(
                (fk["child"], fk["child_col"], fk["parent_col"])
            )
    out: dict[str, list[dict[str, Any]]] = {}
    seen: dict[str, set[str]] = {}

    def collect(table: str, where: str) -> None:
        # A row can be reached twice: through its own user_id and as a child of another
        # user-owned row (track_tags of a user_tag, say). Keep each row once.
        rows = data_api.execute(f'SELECT * FROM "{table}" WHERE {where}', {"user_id": user_id})
        for row in rows:
            key = json.dumps(row, sort_keys=True, default=str)
            if key not in seen.setdefault(table, set()):
                seen[table].add(key)
                out.setdefault(table, []).append(redact(row))
        for child, col, ref in children.get(table, []):
            collect(child, f'"{col}" IN (SELECT "{ref}" FROM "{table}" WHERE {where})')

    collect("users", '"id" = :user_id')
    for r in data_api.execute(_USER_COLUMNS_SQL):
        table, col = r["tbl"], r["col"]
        if col.endswith("_by_user_id"):
            rows = data_api.execute(
                f'SELECT * FROM "{table}" WHERE "{col}" = :user_id', {"user_id": user_id}
            )
            if rows:
                out[f"{table}.{col}"] = [redact(x) for x in rows]
        else:
            collect(table, f'"{col}" = :user_id')
    return out


def list_covers(s3: Any, bucket: str, user_id: str) -> list[str]:
    prefix = f"covers/{_checked(user_id)}/"
    return [
        o["Key"]
        for page in s3.get_paginator("list_objects_v2").paginate(Bucket=bucket, Prefix=prefix)
        for o in page.get("Contents", [])
    ]


def export_events(
    athena: Any,
    *,
    user_id: str,
    workgroup: str,
    sleep: Callable[[float], None] = time.sleep,
) -> list[dict[str, Any]]:
    """The user's rows in clouder_silver.events, oldest first."""
    user_id = _checked(user_id)  # inlined below: validated, and Athena binds no strings here
    qid = athena.start_query_execution(
        QueryString=(
            "SELECT * FROM clouder_silver.events "
            f"WHERE user_id = '{user_id}' ORDER BY ts_client, event_id"
        ),
        WorkGroup=workgroup,
    )["QueryExecutionId"]
    while True:
        status = athena.get_query_execution(QueryExecutionId=qid)["QueryExecution"]["Status"]
        if status["State"] not in ("QUEUED", "RUNNING"):
            break
        sleep(2)
    if status["State"] != "SUCCEEDED":
        raise RuntimeError(f"Athena export of events {status['State']}")
    rows: list[dict[str, Any]] = []
    header: list[str] | None = None
    token: str | None = None
    while True:
        kwargs: dict[str, Any] = {"QueryExecutionId": qid, "MaxResults": 1000}
        if token:
            kwargs["NextToken"] = token
        page = athena.get_query_results(**kwargs)
        for raw in page["ResultSet"]["Rows"]:
            values = [d.get("VarCharValue") for d in raw["Data"]]
            if header is None:  # Athena puts the column names in the first row of page one
                header = values
                continue
            rows.append(dict(zip(header, values, strict=True)))
        token = page.get("NextToken")
        if not token:
            return rows

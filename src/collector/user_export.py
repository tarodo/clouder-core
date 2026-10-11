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


_PAGE = 500  # rows per Data API call: a response is capped at ~1 MiB (catalog_export_handler)


def export_aurora(data_api: Any, user_id: str) -> dict[str, list[dict[str, Any]]]:
    """Rows per table (children included); `table.column` keys hold audit references.

    Every read runs in one REPEATABLE READ transaction, so all pages of all tables come
    from one snapshot, and is paged under the Data API's response cap. Nothing is written;
    the transaction is rolled back.
    """
    tx = data_api.begin_transaction()
    try:
        data_api.execute(
            "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY", transaction_id=tx
        )
        return _export(data_api, user_id, tx)
    finally:
        data_api.rollback_transaction(tx)


def _export(data_api: Any, user_id: str, tx: str) -> dict[str, list[dict[str, Any]]]:
    children: dict[str, list[tuple[str, str, str]]] = {}
    for fk in data_api.execute(_FOREIGN_KEYS_SQL, transaction_id=tx):
        if fk["width"] != 1:  # as delete_user: an incomplete export is worse than none
            raise RuntimeError(f"multi-column foreign key on {fk['child']}: extend export_aurora")
        if fk["on_delete"] != "n":
            children.setdefault(fk["parent"], []).append(
                (fk["child"], fk["child_col"], fk["parent_col"])
            )
    out: dict[str, list[dict[str, Any]]] = {}
    seen: dict[str, set[str]] = {}

    def select(table: str, where: str) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        while True:
            page = data_api.execute(
                f'SELECT * FROM "{table}" WHERE {where} ORDER BY ctid LIMIT :limit OFFSET :offset',
                {"user_id": user_id, "limit": _PAGE, "offset": len(rows)},
                transaction_id=tx,
            )
            rows += page
            if len(page) < _PAGE:
                return rows

    def collect(table: str, where: str) -> None:
        # A row can be reached twice: through its own user_id and as a child of another
        # user-owned row (track_tags of a user_tag, say). Keep each row once.
        for row in select(table, where):
            key = json.dumps(row, sort_keys=True, default=str)
            if key not in seen.setdefault(table, set()):
                seen[table].add(key)
                out.setdefault(table, []).append(redact(row))
        for child, col, ref in children.get(table, []):
            collect(child, f'"{col}" IN (SELECT "{ref}" FROM "{table}" WHERE {where})')

    collect("users", '"id" = :user_id')
    for r in data_api.execute(_USER_COLUMNS_SQL, transaction_id=tx):
        table, col = r["tbl"], r["col"]
        if col.endswith("_by_user_id"):
            rows = select(table, f'"{col}" = :user_id')
            if rows:
                out[f"{table}.{col}"] = [redact(x) for x in rows]
        else:
            collect(table, f'"{col}" = :user_id')
    return out


_CATALOG_CHUNK = 100
_TRACKS_SQL = (
    "SELECT t.id, t.title, t.isrc, string_agg(a.name, ', ' ORDER BY a.name) AS artists "
    "FROM clouder_tracks t "
    "LEFT JOIN clouder_track_artists ta ON ta.track_id = t.id "
    "LEFT JOIN clouder_artists a ON a.id = ta.artist_id "
    "WHERE t.id IN ({marks}) GROUP BY t.id, t.title, t.isrc"
)


def resolve_catalog(data_api: Any, aurora: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    """Names for the catalog ids the user's rows point at, so the export is readable."""
    ids: dict[str, set[str]] = {
        "track_id": set(),
        "artist_id": set(),
        "label_id": set(),
        "style_id": set(),
    }
    for rows in aurora.values():
        for row in rows:
            for col, bucket in ids.items():
                if isinstance(row.get(col), str):
                    bucket.add(row[col])

    def chunks(values: set[str]):
        ordered = sorted(values)
        for i in range(0, len(ordered), _CATALOG_CHUNK):
            part = ordered[i : i + _CATALOG_CHUNK]
            marks = ", ".join(f":i{n}" for n in range(len(part)))
            yield marks, {f"i{n}": v for n, v in enumerate(part)}

    tracks: dict[str, Any] = {}
    for marks, params in chunks(ids["track_id"]):
        for r in data_api.execute(_TRACKS_SQL.format(marks=marks), params):
            tracks[r["id"]] = {"title": r["title"], "artists": r["artists"], "isrc": r["isrc"]}
    names: dict[str, dict[str, str]] = {}
    for key, table in (
        ("artist_id", "clouder_artists"),
        ("label_id", "clouder_labels"),
        ("style_id", "clouder_styles"),
    ):
        found: dict[str, str] = {}
        for marks, params in chunks(ids[key]):
            for r in data_api.execute(
                f"SELECT id, name FROM {table} WHERE id IN ({marks})", params
            ):
                found[r["id"]] = r["name"]
        names[key] = found
    return {
        "tracks": tracks,
        "artists": names["artist_id"],
        "labels": names["label_id"],
        "styles": names["style_id"],
    }


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
        reason = status.get("StateChangeReason", "")
        raise RuntimeError(f"Athena export of events {status['State']}: {reason}")
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

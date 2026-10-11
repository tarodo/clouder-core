"""Delete one user and everything they own, in one Aurora transaction.

The owned tables come from the catalog, not from a hand-kept list: every
`*user_id` column marks rows the user owns, foreign keys lead to their
children, and `*_by_user_id` audit columns are set to NULL (the audited row,
e.g. an enrichment run, stays). Children are deleted before their parents and
the `users` row goes last. A dry run performs the same statements and rolls
them back, so its counts are exact.
"""

from __future__ import annotations

import json
import time
import uuid
from collections.abc import Callable
from datetime import datetime
from typing import Any

TOMBSTONE_PREFIX = "governance/deleted_users/"
# Iceberg tables derived from telemetry; the dbt models anti-join the tombstones
# so a rebuild cannot bring the rows back. Bronze stays append-only (docs/privacy.md).
_LAKE_TABLES = ("clouder_silver.events", "clouder_gold.fct_play")

_FOREIGN_KEYS_SQL = """
SELECT ch.relname::text AS child, ca.attname::text AS child_col,
       pa.relname::text AS parent, pc.attname::text AS parent_col,
       c.confdeltype::text AS on_delete, cardinality(c.conkey) AS width
FROM pg_constraint c
JOIN pg_class ch ON ch.oid = c.conrelid
JOIN pg_class pa ON pa.oid = c.confrelid
JOIN pg_attribute ca ON ca.attrelid = c.conrelid AND ca.attnum = c.conkey[1]
JOIN pg_attribute pc ON pc.attrelid = c.confrelid AND pc.attnum = c.confkey[1]
WHERE c.contype = 'f' AND c.connamespace = 'public'::regnamespace
ORDER BY 1, 2
"""

_USER_COLUMNS_SQL = """
SELECT table_name::text AS tbl, column_name::text AS col
FROM information_schema.columns
WHERE table_schema = 'public' AND column_name ~ 'user_id$' AND table_name <> 'users'
ORDER BY 1, 2
"""


def delete_user(data_api: Any, user_id: str, *, dry_run: bool = False) -> dict[str, int]:
    """Return rows deleted per table and audit cells cleared per `table.column`."""
    children: dict[str, list[tuple[str, str, str]]] = {}
    for fk in data_api.execute(_FOREIGN_KEYS_SQL):
        if fk["width"] != 1:
            raise RuntimeError(f"multi-column foreign key on {fk['child']}: extend delete_user")
        if fk["on_delete"] != "n":  # ON DELETE SET NULL children keep their rows
            children.setdefault(fk["parent"], []).append(
                (fk["child"], fk["child_col"], fk["parent_col"])
            )
    columns = [(r["tbl"], r["col"]) for r in data_api.execute(_USER_COLUMNS_SQL)]

    counts: dict[str, int] = {}
    tx = data_api.begin_transaction()

    def run(sql: str) -> int:
        rows = data_api.execute(sql, {"user_id": user_id}, transaction_id=tx)
        return int(rows[0]["n"])

    def purge(table: str, where: str) -> None:
        for child, col, ref in children.get(table, []):
            purge(child, f'"{col}" IN (SELECT "{ref}" FROM "{table}" WHERE {where})')
        n = run(f'WITH d AS (DELETE FROM "{table}" WHERE {where} RETURNING 1) SELECT count(*) AS n FROM d')
        if n:
            counts[table] = counts.get(table, 0) + n

    try:
        for table, col in columns:
            if col.endswith("_by_user_id"):
                n = run(
                    f'WITH u AS (UPDATE "{table}" SET "{col}" = NULL WHERE "{col}" = :user_id'
                    " RETURNING 1) SELECT count(*) AS n FROM u"
                )
                if n:
                    counts[f"{table}.{col}"] = n
            else:
                purge(table, f'"{col}" = :user_id')
        purge("users", '"id" = :user_id')
    except Exception:
        data_api.rollback_transaction(tx)
        raise
    if dry_run:
        data_api.rollback_transaction(tx)
    else:
        data_api.commit_transaction(tx)
    return counts


def _checked(user_id: str) -> str:
    return str(uuid.UUID(user_id))  # ValueError for anything else: ids go into S3 prefixes


def delete_covers(s3: Any, bucket: str, user_id: str) -> int:
    """Delete every version (and delete marker) of the user's playlist covers."""
    prefix = f"covers/{_checked(user_id)}/"
    objects = [
        {"Key": v["Key"], "VersionId": v["VersionId"]}
        for page in s3.get_paginator("list_object_versions").paginate(Bucket=bucket, Prefix=prefix)
        for v in page.get("Versions", []) + page.get("DeleteMarkers", [])
    ]
    failed = []
    for i in range(0, len(objects), 1000):  # DeleteObjects takes at most 1000 keys
        resp = s3.delete_objects(Bucket=bucket, Delete={"Objects": objects[i:i + 1000], "Quiet": True})
        failed += [f"{e['Key']} ({e.get('Code')})" for e in resp.get("Errors", [])]
    if failed:  # per-key failures come back with HTTP 200
        raise RuntimeError(f"S3 kept {len(failed)} cover object versions: {', '.join(failed[:10])}")
    return len(objects)


def purge_lake(
    s3: Any,
    athena: Any,
    *,
    user_id: str,
    lake_bucket: str,
    workgroup: str,
    now: datetime,
    sleep: Callable[[float], None] = time.sleep,
) -> None:
    """Tombstone the user, then delete their rows from the Iceberg tables."""
    user_id = _checked(user_id)
    s3.put_object(
        Bucket=lake_bucket,
        Key=f"{TOMBSTONE_PREFIX}{user_id}.json",
        Body=json.dumps({"user_id": user_id, "deleted_at": now.isoformat()}),
        ContentType="application/json",
    )
    for table in _LAKE_TABLES:
        # Athena accepts ExecutionParameters only for SELECT, INSERT, CTAS and UNLOAD;
        # user_id is a validated UUID, so inlining it is safe.
        qid = athena.start_query_execution(
            QueryString=f"DELETE FROM {table} WHERE user_id = '{user_id}'",
            WorkGroup=workgroup,
        )["QueryExecutionId"]
        while True:
            state = athena.get_query_execution(QueryExecutionId=qid)["QueryExecution"]["Status"]["State"]
            if state not in ("QUEUED", "RUNNING"):
                break
            sleep(2)
        if state != "SUCCEEDED":
            raise RuntimeError(f"Athena DELETE on {table} {state}")

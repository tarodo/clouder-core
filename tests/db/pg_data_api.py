"""Real-Postgres stand-in for collector.data_api.DataAPIClient (tests and benchmarks only).

Mirrors the Data API behaviour the repository relies on:
- `:name` bind parameters (`::type` casts are left alone);
- each transaction id is its own connection, and calls without a transaction id
  run on a separate autocommit connection, so they cannot see uncommitted writes
  — the visibility rule that makes `transaction_id` mandatory inside a transaction;
- dict/list parameters are sent as JSON (Data API `typeHint=JSON`);
- str parameters are typed `varchar`, like the Data API's JDBC `setString`
  (psycopg's default `text` makes `col <> :p` and `THEN :p` disagree on the type).
psycopg stays out of src/collector (ADR-0001).
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Iterable, Iterator, Mapping
from contextlib import contextmanager
from typing import Any

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Json
from psycopg.types.string import StrBinaryDumperVarchar, StrDumperVarchar

CANONICAL_TABLES = (
    "identity_map",
    "source_relations",
    "source_entities",
    "clouder_track_artists",
    "clouder_tracks",
    "clouder_albums",
    "clouder_artists",
    "clouder_labels",
    "clouder_styles",
)

_PARAM = re.compile(r"(?<!:):([A-Za-z_][A-Za-z0-9_]*)")


def _to_pyformat(sql: str) -> str:
    return _PARAM.sub(r"%(\1)s", sql.replace("%", "%%"))


def _adapt(params: Mapping[str, Any] | None) -> dict[str, Any]:
    return {
        key: Json(value) if isinstance(value, (dict, list)) else value
        for key, value in (params or {}).items()
    }


def _connect(dsn: str, *, autocommit: bool) -> psycopg.Connection:
    conn = psycopg.connect(dsn, autocommit=autocommit, row_factory=dict_row)
    conn.adapters.register_dumper(str, StrDumperVarchar)
    conn.adapters.register_dumper(str, StrBinaryDumperVarchar)
    return conn


class PgDataAPIClient:
    def __init__(self, dsn: str) -> None:
        self._dsn = dsn
        self._autocommit = _connect(dsn, autocommit=True)
        self._tx: dict[str, psycopg.Connection] = {}

    def _conn(self, transaction_id: str | None) -> psycopg.Connection:
        return self._tx[transaction_id] if transaction_id else self._autocommit

    def execute(
        self,
        sql: str,
        params: Mapping[str, Any] | None = None,
        transaction_id: str | None = None,
    ) -> list[dict[str, Any]]:
        with self._conn(transaction_id).cursor() as cur:
            cur.execute(_to_pyformat(sql), _adapt(params))
            return list(cur.fetchall()) if cur.description else []

    def batch_execute(
        self,
        sql: str,
        parameter_sets: Iterable[Mapping[str, Any]],
        transaction_id: str | None = None,
    ) -> None:
        sets = [_adapt(params) for params in parameter_sets]
        if not sets:
            return
        with self._conn(transaction_id).cursor() as cur:
            cur.executemany(_to_pyformat(sql), sets)

    def begin_transaction(self) -> str:
        transaction_id = str(uuid.uuid4())
        self._tx[transaction_id] = _connect(self._dsn, autocommit=False)
        return transaction_id

    def commit_transaction(self, transaction_id: str) -> None:
        conn = self._tx.pop(transaction_id)
        conn.commit()
        conn.close()

    def rollback_transaction(self, transaction_id: str) -> None:
        conn = self._tx.pop(transaction_id)
        conn.rollback()
        conn.close()

    @contextmanager
    def transaction(self) -> Iterator[str]:
        transaction_id = self.begin_transaction()
        try:
            yield transaction_id
            self.commit_transaction(transaction_id)
        except Exception:
            self.rollback_transaction(transaction_id)
            raise

    def close(self) -> None:
        for conn in self._tx.values():
            conn.close()
        self._tx.clear()
        self._autocommit.close()


def truncate_canonical(client: PgDataAPIClient) -> None:
    # TRUNCATE ... CASCADE also empties every user-overlay table that references the
    # catalog, so refuse on anything that looks like a real (dev) database.
    if count_rows(client, "users"):
        raise RuntimeError(
            "refusing to TRUNCATE: the database has users — point TEST_DATABASE_URL "
            "or --database-url at a throwaway database"
        )
    client.execute(f"TRUNCATE ingest_runs, {', '.join(CANONICAL_TABLES)} CASCADE")


def seed_run(client: PgDataAPIClient, run_id: str) -> None:
    """Minimal ingest_runs row: source_entities/source_relations.last_run_id are FKs
    to it (in production the ingest handler creates it before canonicalization)."""
    client.execute(
        """
        INSERT INTO ingest_runs (run_id, source, style_id, raw_s3_key, status, started_at)
        VALUES (:run_id, 'beatport', 1, 'test', 'RAW_SAVED', now())
        ON CONFLICT (run_id) DO NOTHING
        """,
        {"run_id": run_id},
    )


def count_rows(client: PgDataAPIClient, table: str) -> int:
    return int(client.execute(f"SELECT count(*) AS n FROM {table}")[0]["n"])

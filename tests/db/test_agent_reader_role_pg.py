"""The agent's read-only role: reads the catalog, never secrets, never writes."""

from __future__ import annotations

import importlib.util
import os
import re
import sys
from pathlib import Path

import psycopg
import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
from create_agent_reader import ROLE, password_sql, role_sql

_spec = importlib.util.spec_from_file_location(
    "agent_role_migration", ROOT / "alembic/versions/20261021_41_agent_readonly_role.py"
)
assert _spec and _spec.loader
migration = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(migration)

# Columns that look like secrets or personal data; each must stay unreadable.
SENSITIVE = re.compile(r"token|secret|password|email|credential|_enc$|ip_address|user_agent")
PASSWORD = "s3cret-for-test"


def _one(pg, sql: str, params: dict | None = None):
    return pg.execute(sql, params or {})[0]


def _connect(**kw) -> psycopg.Connection:
    return psycopg.connect(psycopg.conninfo.make_conninfo(os.environ["TEST_DATABASE_URL"], **kw))


def test_reads_the_catalog(pg) -> None:
    row = _one(pg, "SELECT has_table_privilege(:r, 'clouder_tracks', 'SELECT') AS ok", {"r": ROLE})
    assert row["ok"] is True


@pytest.mark.parametrize("table", ["user_vendor_tokens", "user_sessions"])
def test_secret_tables_are_closed(pg, table) -> None:
    row = _one(pg, "SELECT has_table_privilege(:r, :t, 'SELECT') AS ok", {"r": ROLE, "t": table})
    assert row["ok"] is False


def test_users_without_email(pg) -> None:
    row = _one(
        pg,
        "SELECT has_column_privilege(:r, 'users', 'id', 'SELECT') AS id_ok,"
        " has_column_privilege(:r, 'users', 'email', 'SELECT') AS email_ok",
        {"r": ROLE},
    )
    assert (row["id_ok"], row["email_ok"]) == (True, False)


def test_no_sensitive_column_is_readable(pg) -> None:
    # A new table with a token or email column must be closed explicitly.
    rows = pg.execute(
        "SELECT table_name, column_name FROM information_schema.columns"
        " WHERE table_schema = 'public'"
    )
    sensitive = [r for r in rows if SENSITIVE.search(r["column_name"])]
    assert sensitive
    readable = [
        (r["table_name"], r["column_name"])
        for r in sensitive
        if _one(
            pg,
            "SELECT has_column_privilege(:r, :t, :c, 'SELECT') AS ok",
            {"r": ROLE, "t": r["table_name"], "c": r["column_name"]},
        )["ok"]
    ]
    assert readable == []


@pytest.mark.parametrize("privilege", ["INSERT", "UPDATE", "DELETE", "TRUNCATE"])
def test_never_writes(pg, privilege) -> None:
    rows = pg.execute(
        "SELECT c.relname FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace"
        " WHERE n.nspname = 'public' AND c.relkind IN ('r', 'p', 'v', 'm')"
        " AND has_table_privilege(:r, c.oid, :p)",
        {"r": ROLE, "p": privilege},
    )
    assert rows == []


def test_script_makes_the_login_read_only(pg) -> None:
    for sql in [*role_sql(), password_sql(PASSWORD)]:
        pg.execute(sql)
    with _connect(user=ROLE, password=PASSWORD) as conn:
        assert conn.execute("SELECT count(*) FROM clouder_tracks").fetchone() is not None
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute("SELECT email FROM users")
        conn.rollback()
        with pytest.raises(psycopg.errors.ReadOnlySqlTransaction):
            conn.execute("CREATE TEMP TABLE t (x int)")


def test_script_works_without_superuser() -> None:
    # Production's master user has CREATEROLE, not superuser.
    with _connect() as conn:
        conn.execute(f"DROP OWNED BY {ROLE}; DROP ROLE {ROLE}")
        conn.execute("CREATE ROLE t_master CREATEROLE")
        conn.execute("SET ROLE t_master")
        for sql in [*role_sql(), password_sql(PASSWORD)]:
            conn.execute(sql)
        conn.execute("RESET ROLE")
        (config,) = conn.execute(
            "SELECT rolconfig FROM pg_roles WHERE rolname = %s", (ROLE,)
        ).fetchone()
        assert "default_transaction_read_only=on" in config
        conn.rollback()


def test_migration_asks_for_the_script_where_roles_cannot_be_created() -> None:
    # Production's migrator owns the tables but has no CREATEROLE.
    with _connect() as conn:
        conn.execute(f"DROP OWNED BY {ROLE}; DROP ROLE {ROLE}")
        conn.execute("CREATE ROLE t_migrator NOCREATEROLE")
        conn.execute("SET ROLE t_migrator")
        with pytest.raises(psycopg.errors.RaiseException, match=r"create_agent_reader\.py"):
            conn.execute(migration.UPGRADE_SQL[0])
        conn.rollback()

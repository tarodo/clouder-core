"""Every raw SQL statement must parse with the real PostgreSQL grammar.

The rest of the suite asserts on SQL as *text* — `assert "RETURNING id" in sql`
— which passes just as happily on a statement Postgres would reject. Nothing
executes these statements until they reach Aurora, and there is no Postgres in
CI, so a syntax error ships silently and surfaces as a runtime failure in a
Lambda.

`pglast` wraps libpg_query, the actual PostgreSQL parser, so this is the same
grammar the server uses rather than an approximation of it. It is pinned to the
series whose grammar matches the Aurora major version (16) — a parser running
ahead of the server would happily accept syntax Aurora rejects, so
`test_parser_matches_the_deployed_engine` fails if the two drift apart.

Scope — what this does NOT cover, deliberately:

* SQL built with f-strings. Rendering one means inventing values for its
  interpolated fragments (a whole ORDER BY clause, a generated placeholder
  list), and guessing wrong produces a test that skips real statements while
  looking green. Those are left to the tests that exercise their methods.
* `analytics_rollup*` / `analytics_handler`. That SQL targets Athena/Trino and
  DuckDB, not Postgres, so the PG grammar is the wrong oracle for it.
"""

from __future__ import annotations

import ast
import pathlib
import re

import pytest

pglast = pytest.importorskip("pglast")

SOURCE_ROOT = pathlib.Path(__file__).resolve().parents[2] / "src" / "collector"

# Statements reaching a non-Postgres engine — wrong grammar for this check.
NON_POSTGRES_MODULES = {
    "analytics_rollup.py",
    "analytics_rollup_runner.py",
    "analytics_handler.py",
}

EXECUTE_METHODS = {"execute", "batch_execute"}

# `:name` is a Data API bind placeholder, which is not PG syntax. The negative
# lookbehind keeps `value::text` casts intact — substituting inside those turns
# valid SQL into a syntax error and would make this test lie.
BIND_PARAM = re.compile(r"(?<!:):([A-Za-z_][A-Za-z0-9_]*)")

# A floor, so the collector silently matching nothing (a rename of `execute`,
# a moved package) fails loudly instead of passing vacuously.
MINIMUM_EXPECTED_STATEMENTS = 150

# Aurora PostgreSQL major version this SQL actually runs against.
AURORA_POSTGRES_MAJOR = 16


def _collect_statements() -> list[tuple[pathlib.Path, int, str]]:
    """Literal SQL passed straight to execute()/batch_execute().

    Being the first argument of the call is what makes a string a *complete*
    statement: fragments get concatenated or formatted first, and route keys
    like "DELETE /me/sessions/{id}" never reach a cursor at all.
    """
    found: list[tuple[pathlib.Path, int, str]] = []
    for path in sorted(SOURCE_ROOT.rglob("*.py")):
        if path.name in NON_POSTGRES_MODULES:
            continue
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if not (isinstance(func, ast.Attribute) and func.attr in EXECUTE_METHODS):
                continue
            if not node.args:
                continue
            first = node.args[0]
            if isinstance(first, ast.Constant) and isinstance(first.value, str):
                found.append((path, first.lineno, first.value))
    return found


STATEMENTS = _collect_statements()


def test_parser_matches_the_deployed_engine() -> None:
    """A parser ahead of the server accepts syntax Aurora would reject."""
    major = pglast.get_postgresql_version()[0]
    assert major == AURORA_POSTGRES_MAJOR, (
        f"pglast {pglast.__version__} parses PostgreSQL {major}, but Aurora runs "
        f"{AURORA_POSTGRES_MAJOR}. Re-pin pglast in requirements-dev.txt, or "
        "update AURORA_POSTGRES_MAJOR if the cluster was upgraded."
    )


def test_collector_finds_the_sql_it_is_supposed_to_check() -> None:
    assert len(STATEMENTS) >= MINIMUM_EXPECTED_STATEMENTS, (
        f"only found {len(STATEMENTS)} raw statements under {SOURCE_ROOT}; "
        "the AST collector has probably stopped matching"
    )


@pytest.mark.parametrize(
    "path,lineno,sql",
    STATEMENTS,
    ids=[f"{p.relative_to(SOURCE_ROOT)}:{n}" for p, n, _ in STATEMENTS],
)
def test_statement_is_valid_postgres(path: pathlib.Path, lineno: int, sql: str) -> None:
    try:
        pglast.parse_sql(BIND_PARAM.sub("NULL", sql))
    except Exception as exc:  # pglast raises its own parse error types
        pytest.fail(f"{path}:{lineno} is not valid PostgreSQL: {exc}\n\n{sql}")

# Testing Guide

## Running Tests

```bash
# Install dev dependencies first
python -m pip install -r requirements-dev.txt

# Run all tests (quiet output)
pytest -q

# Single test file
pytest tests/unit/test_canonicalize.py -q

# Single test by name
pytest tests/unit/test_canonicalize.py::test_my_case -q
```

`pytest.ini` sets `pythonpath = src`, so `import collector` resolves from `src/collector/` without any manual `PYTHONPATH` export. For scripts run outside pytest (e.g., `python scripts/generate_openapi.py`), export `PYTHONPATH=src` manually.

On macOS, `python` is unavailable from Homebrew Python 3.14. Use `python3` for stdlib-only scripts. For project scripts that import dependencies (`pydantic`, `yaml`, etc.), use `.venv/bin/python`.

---

## Layout

```
tests/
  unit/          # Fast, no network, no DB. FakeDataAPI or direct function calls.
  integration/   # Uses FakeRepo / in-process fake dependencies. No real AWS.
  contract/      # Schema / contract checks (no network).
```

### Unit tests (`tests/unit/`)

Test individual functions and modules in isolation. Examples:

- `test_canonicalize.py` — canonicalization logic with a `FakeDataAPI`.
- `test_beatport_client.py` — HTTP client with mocked `requests`.
- `test_ai_flag_propagation.py` — `propagate_ai_flag` logic.
- `test_auth_handler_*.py` — auth handler routes with fake repository and JWT utils.

Unit tests do not need real Aurora, real AWS credentials, or real vendor API keys.

### Integration tests (`tests/integration/`)

Test a full handler invocation (Lambda event → response) using fake in-memory implementations of the repository and external clients. Example: `tests/integration/test_curation_handler.py` imports `lambda_handler` from `collector.curation_handler` and drives it with crafted API Gateway event dicts, using `FakeRepo` as the backing store.

These tests catch routing bugs, request parsing errors, and cross-component interactions that unit tests miss, without requiring real infrastructure.

---

## `FakeDataAPI` and `FakeRepo`

### `FakeDataAPI`

<!-- TODO: confirm the exact class name and location in tests/ if it exists as a shared fixture -->

Used in unit tests that exercise DB-touching code (e.g., `Canonicalizer`). The fake records SQL strings and returns pre-configured rows. It performs simple substring matching on SQL text; it does not parse or execute SQL.

**What it misses:** Real Postgres SQL semantics. In particular:

- **Correlated `EXISTS` after `GROUP BY`** (SQLState 42803) — Postgres rejects these; `FakeDataAPI` string-matches and will not catch the error. Correlated subqueries must be verified against real Postgres in integration or production.
- **Type coercion mismatches** — Postgres may reject a parameter that Python serializes as a string but the column expects as an integer; fake stores do not enforce column types.
- **Constraint violations** — unique indexes, foreign keys, and check constraints are not enforced by the fake.

Use real Postgres (integration tests or local Alembic + psycopg) to verify anything that depends on SQL correctness.

### `FakeRepo`

`tests/integration/test_curation_handler.py:FakeRepo` is an in-memory implementation of `CategoriesRepository` used exclusively in handler integration tests. It mirrors the real repository's method signatures and raises the same domain exceptions (`NotFoundError`, `NameConflictError`, `OrderMismatchError`).

**Critical maintenance rule:** When a new keyword argument is added to any real repository method, the corresponding `FakeRepo` method must be updated to accept the same signature. If they diverge, handler integration tests will receive a `TypeError` and report HTTP 500 even when unit tests pass. This is a known CI gate — see [CI beyond pytest](#ci-beyond-pytest) below.

---

## CI Beyond `pytest`

The CI pipeline (`.github/workflows/pr.yml`) runs additional checks that are not covered by `pytest -q`:

### `alembic-check`

Spins up an ephemeral Postgres container, runs `alembic upgrade head`, and checks that the migration chain is consistent. Catches migration file conflicts and broken migration scripts.

### `terraform` (fmt / validate / plan)

Runs `terraform fmt -check`, `terraform validate`, and `terraform plan` against the `infra/` directory. Does not apply changes.

### `tests` (`pytest -q`)

Standard Python test run.

### `frontend` (schema drift check)

`frontend/src/api/schema.d.ts` is auto-generated from `docs/api/openapi.yaml` by running `pnpm api:types` from the `frontend/` directory. The CI job regenerates the file and diffs it against the committed version. If the diff is non-empty, CI fails.

**After editing the OpenAPI spec** (`docs/api/openapi.yaml` or `scripts/generate_openapi.py:ROUTES`), run:

```bash
cd frontend && pnpm api:types
```

Commit the updated `schema.d.ts` along with the spec change, or the frontend CI job will fail.

### `FakeRepo` signature mirroring

As noted above, adding kwargs to real repository methods without updating `FakeRepo` causes integration tests to 500. The CI `tests` job catches this but only at the handler-integration level — it does not report which method diverged. When debugging a CI-only 500, start by comparing `FakeRepo` method signatures against the real `CategoriesRepository`.

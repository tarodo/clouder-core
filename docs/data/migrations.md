# Migrations

CLOUDER uses [Alembic](https://alembic.sqlalchemy.org/) for schema migrations against Aurora PostgreSQL.

Source files:
- `alembic.ini` — Alembic configuration; `script_location = alembic`
- `alembic/env.py` — uses `ALEMBIC_DATABASE_URL` env var; falls back to `sqlalchemy.url` in `alembic.ini`
- `alembic/versions/` — migration scripts; naming convention `YYYYMMDD_NN_<slug>.py`
- `src/collector/db_models.py` — SQLAlchemy models; source of truth for `--autogenerate`

---

## Local flow

Prerequisites: local PostgreSQL running on `localhost:5432`, `psycopg` installed (it is in `requirements-dev.txt`, not `requirements-lambda.txt`).

```bash
export PYTHONPATH=src
export ALEMBIC_DATABASE_URL='postgresql+psycopg://postgres:postgres@localhost:5432/postgres'

# Apply all pending migrations
alembic upgrade head

# Roll back one step
alembic downgrade -1

# Show current revision
alembic current

# Show pending revisions
alembic history --verbose
```

`PYTHONPATH=src` is required because `alembic/env.py` imports `collector.db_models`.

---

## Packaging

`scripts/package_lambda.sh` copies the local `alembic/` directory into the Lambda zip under the name `db_migrations`:

```bash
cp -R "$ROOT_DIR/alembic" "$BUILD_DIR/db_migrations"
```

The migration Lambda (`src/collector/migration_handler.py`) resolves the script location at runtime:

```python
script_location = root_dir / "db_migrations"
```

This rename is necessary because the Lambda zip flattens directories relative to `src/`, and `alembic` as a top-level directory would shadow the `alembic` pip package. Do not reference `alembic/` paths at Lambda runtime; use `db_migrations/`.

---

## Migration Lambda

`src/collector/migration_handler.py` exposes `lambda_handler`. It is invoked post-deploy by `deploy.yml` via a direct Lambda invoke (not via API Gateway).

**Invocation payload**:
```json
{"action": "upgrade", "revision": "head"}
```

Both fields have defaults; an empty payload (`{}`) is equivalent.

**Auth modes** (controlled by `AURORA_AUTH_MODE` env var):

| Mode | Required env | How it works |
|---|---|---|
| `password` (default) | `AURORA_SECRET_ARN`, `AURORA_WRITER_ENDPOINT`, `AURORA_PORT`, `AURORA_DATABASE` | Reads username/password from Secrets Manager |
| `iam` | `AURORA_DB_USER`, `AURORA_WRITER_ENDPOINT`, `AURORA_PORT`, `AURORA_DATABASE` | Generates an RDS IAM auth token via `boto3.client("rds").generate_db_auth_token` |

See ADR-0005 for the rationale behind IAM auth for migrations.

**Return value on success**:
```json
{
  "status": "ok",
  "action": "upgrade",
  "revision": "head",
  "started_at": "2026-05-12T10:00:00Z",
  "finished_at": "2026-05-12T10:00:01Z",
  "duration_ms": 1250
}
```

The handler raises `RuntimeError` if Alembic files are missing from the artifact (indicates a packaging issue) or if the secret/credentials are absent.

---

## Autogenerate workflow

Alembic's `--autogenerate` compares `db_models.py` models against the live schema.

```bash
export PYTHONPATH=src
export ALEMBIC_DATABASE_URL='postgresql+psycopg://postgres:postgres@localhost:5432/postgres'

# Apply current head first
alembic upgrade head

# Autogenerate a candidate migration
alembic revision --autogenerate -m "short_description"
```

After generating, always manually review the output in `alembic/versions/` before committing:

1. Check that `upgrade()` contains only the intended changes.
2. Verify `downgrade()` is correct and complete.
3. Confirm partial indexes (PostgreSQL-specific `postgresql_where=`) are preserved — autogenerate may not detect them.
4. Confirm `CheckConstraint` names match what is in `db_models.py` — mismatches cause silent drift.
5. Add `compare_type=True` and `compare_server_default=True` are already set in `alembic/env.py`; they catch column type and default changes.
6. Rename the file to follow the `YYYYMMDD_NN_<slug>.py` convention before committing.

Do not rely solely on autogenerate for complex changes (computed partial indexes, custom types, deferrable constraints). Write those by hand.

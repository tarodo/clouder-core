"""Real-Postgres fixtures. Skipped unless TEST_DATABASE_URL points at a migrated DB.

Local: docker run -d --rm --name canon-pg -p 55432:5432 -e POSTGRES_PASSWORD=postgres postgres:16
       then `alembic upgrade head` and
       export TEST_DATABASE_URL=postgresql://postgres:postgres@localhost:55432/postgres
CI:    the alembic-check job provides the database.
"""

from __future__ import annotations

import os

import pytest

from pg_data_api import PgDataAPIClient, truncate_canonical


@pytest.fixture
def pg():
    dsn = os.environ.get("TEST_DATABASE_URL")
    if not dsn:
        pytest.skip("TEST_DATABASE_URL not set")
    client = PgDataAPIClient(dsn)
    truncate_canonical(client)
    yield client
    client.close()

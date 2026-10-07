"""The test harness refuses to wipe a database that looks real."""

from __future__ import annotations

import pytest

from pg_data_api import truncate_canonical


def test_truncate_refuses_a_database_with_users(pg) -> None:
    pg.execute(
        "INSERT INTO users (id, spotify_id, created_at, updated_at) "
        "VALUES ('u-guard', 'sp-guard', now(), now())"
    )
    try:
        with pytest.raises(RuntimeError, match="users"):
            truncate_canonical(pg)
    finally:
        pg.execute("DELETE FROM users WHERE id = 'u-guard'")

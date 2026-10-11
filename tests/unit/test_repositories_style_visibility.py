"""ClouderRepository: admin style visibility (coverage flag + toggle)."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock

from collector.repositories import ClouderRepository

_NOW = datetime(2026, 10, 4, 12, 0, tzinfo=UTC)


def _repo(rows):
    fake = MagicMock()
    fake.execute.return_value = rows
    return ClouderRepository(data_api=fake), fake


def test_coverage_for_year_selects_hidden_flag() -> None:
    repo, fake = _repo([])

    repo.coverage_for_year(2026)

    sql, _ = fake.execute.call_args[0]
    assert "cs.is_hidden" in sql


def test_set_style_hidden_updates_flag_and_reports_found() -> None:
    repo, fake = _repo([{"id": "uuid-bf"}])

    assert repo.set_style_hidden("uuid-bf", True, _NOW) is True

    sql, params = fake.execute.call_args[0]
    assert "UPDATE clouder_styles" in sql
    assert "SET is_hidden = :is_hidden" in sql
    assert "updated_at = :now" in sql
    assert "WHERE id = :style_id" in sql
    assert "RETURNING id" in sql
    assert params == {"style_id": "uuid-bf", "is_hidden": True, "now": _NOW}


def test_set_style_hidden_unknown_style_returns_false() -> None:
    repo, _ = _repo([])

    assert repo.set_style_hidden("missing", False, _NOW) is False

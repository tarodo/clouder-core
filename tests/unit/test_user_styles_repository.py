"""UserStylesRepository: per-user style selection reads."""

from __future__ import annotations

from typing import Any

from collector.user_styles.repository import UserStylesRepository


class FakeDataApi:
    """Minimal stub: records (sql, params) per call, returns scripted rows."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.scripted: list[list[dict[str, Any]]] = []

    def script(self, *batches: list[dict[str, Any]]) -> None:
        self.scripted.extend(batches)

    def execute(
        self,
        sql: str,
        params: dict[str, Any] | None = None,
        transaction_id: str | None = None,
    ) -> list[dict[str, Any]]:
        self.calls.append((sql, dict(params or {})))
        if self.scripted:
            return self.scripted.pop(0)
        return []


def test_count_selection_counts_pref_rows_only():
    api = FakeDataApi()
    api.script([{"cnt": 3}])
    repo = UserStylesRepository(data_api=api)

    assert repo.count_selection("u-1") == 3

    sql, params = api.calls[0]
    assert "FROM clouder_user_style_prefs" in sql
    assert params == {"user_id": "u-1"}


def test_list_for_user_joins_and_orders_by_position():
    api = FakeDataApi()
    api.script([{"id": "sty-1", "name": "Drum & Bass"}])
    repo = UserStylesRepository(data_api=api)

    rows = repo.list_for_user(user_id="u-1", limit=50, offset=0, search=None)

    assert rows == [{"id": "sty-1", "name": "Drum & Bass"}]
    sql, params = api.calls[0]
    assert "JOIN clouder_styles s ON s.id = p.style_id" in sql
    assert "ORDER BY p.position" in sql
    assert params == {"user_id": "u-1", "limit": 50, "offset": 0}


def test_list_for_user_applies_search_lowercased():
    api = FakeDataApi()
    repo = UserStylesRepository(data_api=api)

    repo.list_for_user(user_id="u-1", limit=10, offset=0, search="DnB")

    sql, params = api.calls[0]
    assert "s.normalized_name LIKE :search" in sql
    assert params["search"] == "%dnb%"


def test_list_all_keeps_created_at_desc_order():
    api = FakeDataApi()
    repo = UserStylesRepository(data_api=api)

    repo.list_all(limit=50, offset=0, search=None)

    sql, _ = api.calls[0]
    assert "FROM clouder_styles" in sql
    assert "ORDER BY created_at DESC" in sql
    assert "clouder_user_style_prefs" not in sql


def test_list_catalog_projects_selected_and_position():
    api = FakeDataApi()
    api.script([
        {"id": "sty-1", "name": "Drum & Bass", "selected": True, "position": 0},
        {"id": "sty-2", "name": "House", "selected": False, "position": None},
    ])
    repo = UserStylesRepository(data_api=api)

    rows = repo.list_catalog(user_id="u-1", limit=200, offset=0, search=None)

    assert rows[0]["selected"] is True
    assert rows[1]["position"] is None
    sql, params = api.calls[0]
    assert "LEFT JOIN clouder_user_style_prefs p" in sql
    assert "ORDER BY (p.position IS NULL), p.position, s.name" in sql
    assert params["user_id"] == "u-1"

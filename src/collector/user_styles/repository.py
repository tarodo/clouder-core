"""Aurora Data API persistence for per-user style selection."""

from __future__ import annotations

from typing import Any

MAX_SELECTION = 100

_STYLE_COLUMNS = "s.id, s.name, s.normalized_name, s.created_at, s.updated_at"


class UserStylesRepository:
    def __init__(self, data_api: Any) -> None:
        self._data_api = data_api

    # ── reads ────────────────────────────────────────────────────────
    def count_selection(self, user_id: str) -> int:
        rows = self._data_api.execute(
            """
            SELECT count(*) AS cnt FROM clouder_user_style_prefs
            WHERE user_id = :user_id
            """,
            {"user_id": user_id},
        )
        return int(rows[0]["cnt"]) if rows else 0

    def list_for_user(
        self,
        *,
        user_id: str,
        limit: int,
        offset: int,
        search: str | None = None,
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {
            "user_id": user_id, "limit": limit, "offset": offset,
        }
        where = ""
        if search:
            where = " AND s.normalized_name LIKE :search"
            params["search"] = f"%{search.lower()}%"
        return self._data_api.execute(
            f"""
            SELECT {_STYLE_COLUMNS}
            FROM clouder_user_style_prefs p
            JOIN clouder_styles s ON s.id = p.style_id
            WHERE p.user_id = :user_id{where}
            ORDER BY p.position
            LIMIT :limit OFFSET :offset
            """,
            params,
        )

    def count_for_user(
        self, *, user_id: str, search: str | None = None
    ) -> int:
        params: dict[str, Any] = {"user_id": user_id}
        where = ""
        if search:
            where = " AND s.normalized_name LIKE :search"
            params["search"] = f"%{search.lower()}%"
        rows = self._data_api.execute(
            f"""
            SELECT count(*) AS cnt
            FROM clouder_user_style_prefs p
            JOIN clouder_styles s ON s.id = p.style_id
            WHERE p.user_id = :user_id{where}
            """,
            params,
        )
        return int(rows[0]["cnt"]) if rows else 0

    def list_all(
        self, *, limit: int, offset: int, search: str | None = None
    ) -> list[dict[str, Any]]:
        """Catalog in legacy order — the empty-selection fallback."""
        params: dict[str, Any] = {"limit": limit, "offset": offset}
        where = ""
        if search:
            where = "WHERE normalized_name LIKE :search"
            params["search"] = f"%{search.lower()}%"
        return self._data_api.execute(
            f"""
            SELECT id, name, normalized_name, created_at, updated_at
            FROM clouder_styles
            {where}
            ORDER BY created_at DESC
            LIMIT :limit OFFSET :offset
            """,
            params,
        )

    def count_all(self, search: str | None = None) -> int:
        params: dict[str, Any] = {}
        where = ""
        if search:
            where = "WHERE normalized_name LIKE :search"
            params["search"] = f"%{search.lower()}%"
        rows = self._data_api.execute(
            f"SELECT count(*) AS cnt FROM clouder_styles {where}", params
        )
        return int(rows[0]["cnt"]) if rows else 0

    def list_catalog(
        self,
        *,
        user_id: str,
        limit: int,
        offset: int,
        search: str | None = None,
    ) -> list[dict[str, Any]]:
        """Whole catalog annotated with the caller's selection."""
        params: dict[str, Any] = {
            "user_id": user_id, "limit": limit, "offset": offset,
        }
        where = ""
        if search:
            where = "WHERE s.normalized_name LIKE :search"
            params["search"] = f"%{search.lower()}%"
        return self._data_api.execute(
            f"""
            SELECT {_STYLE_COLUMNS},
                   (p.user_id IS NOT NULL) AS selected,
                   p.position AS position
            FROM clouder_styles s
            LEFT JOIN clouder_user_style_prefs p
                   ON p.style_id = s.id AND p.user_id = :user_id
            {where}
            ORDER BY (p.position IS NULL), p.position, s.name
            LIMIT :limit OFFSET :offset
            """,
            params,
        )

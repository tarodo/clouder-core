"""Aurora Data API repository for spec-C categories.

Tenancy: every method takes `user_id` and includes it in WHERE.
Cross-user access yields zero rows (mapped to 404 by the handler).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Mapping, Sequence

from collector.data_api import DataAPIClient
from collector.settings import get_data_api_settings

from . import (
    NameConflictError,
    NotFoundError,
    OrderMismatchError,
    PaginatedResult,
    utc_now,
)


@dataclass(frozen=True)
class CategoryRow:
    id: str
    user_id: str
    style_id: str
    style_name: str
    name: str
    normalized_name: str
    position: int
    track_count: int
    created_at: str  # ISO string from Data API
    updated_at: str


@dataclass(frozen=True)
class TrackInCategoryRow:
    track: Mapping[str, Any]
    added_at: str
    source_triage_block_id: str | None


class CategoriesRepository:
    def __init__(self, data_api: DataAPIClient) -> None:
        self._data_api = data_api

    def create(
        self,
        *,
        user_id: str,
        style_id: str,
        category_id: str,
        name: str,
        normalized_name: str,
        now: datetime,
    ) -> CategoryRow:
        with self._data_api.transaction() as tx_id:
            style_rows = self._data_api.execute(
                "SELECT id, name FROM clouder_styles WHERE id = :style_id",
                {"style_id": style_id},
                transaction_id=tx_id,
            )
            if not style_rows:
                raise NotFoundError("style_not_found", "Style not found")
            style_name = style_rows[0]["name"]

            max_rows = self._data_api.execute(
                """
                SELECT COALESCE(MAX(position), -1) AS max_pos
                FROM categories
                WHERE user_id = :user_id
                  AND style_id = :style_id
                  AND deleted_at IS NULL
                """,
                {"user_id": user_id, "style_id": style_id},
                transaction_id=tx_id,
            )
            position = int(max_rows[0]["max_pos"]) + 1

            try:
                rows = self._data_api.execute(
                    """
                    INSERT INTO categories (
                        id, user_id, style_id, name, normalized_name,
                        position, created_at, updated_at, deleted_at
                    ) VALUES (
                        :id, :user_id, :style_id, :name, :normalized_name,
                        :position, :created_at, :updated_at, NULL
                    )
                    RETURNING id, user_id, style_id, name, normalized_name,
                              position,
                              :style_name AS style_name,
                              0 AS track_count,
                              created_at, updated_at
                    """,
                    {
                        "id": category_id,
                        "user_id": user_id,
                        "style_id": style_id,
                        "name": name,
                        "normalized_name": normalized_name,
                        "position": position,
                        "style_name": style_name,
                        "created_at": now,
                        "updated_at": now,
                    },
                    transaction_id=tx_id,
                )
            except Exception as exc:
                msg = str(exc)
                if "uq_categories_user_style_normname" in msg:
                    raise NameConflictError(
                        "Category name already exists in this style"
                    ) from exc
                raise

            row = rows[0]
            return CategoryRow(
                id=row["id"],
                user_id=row["user_id"],
                style_id=row["style_id"],
                style_name=row["style_name"],
                name=row["name"],
                normalized_name=row["normalized_name"],
                position=int(row["position"]),
                track_count=int(row["track_count"]),
                created_at=str(row["created_at"]),
                updated_at=str(row["updated_at"]),
            )

    _CATEGORY_SELECT = """
        SELECT
            c.id, c.user_id, c.style_id, c.name, c.normalized_name,
            c.position, c.created_at, c.updated_at,
            s.name AS style_name,
            COALESCE(t.cnt, 0) AS track_count
        FROM categories c
        JOIN clouder_styles s ON s.id = c.style_id
        LEFT JOIN (
            SELECT category_id, COUNT(*) AS cnt
            FROM category_tracks
            GROUP BY category_id
        ) t ON t.category_id = c.id
    """

    def _row(self, raw: Mapping[str, Any]) -> CategoryRow:
        return CategoryRow(
            id=raw["id"],
            user_id=raw["user_id"],
            style_id=raw["style_id"],
            style_name=raw["style_name"],
            name=raw["name"],
            normalized_name=raw["normalized_name"],
            position=int(raw["position"]),
            track_count=int(raw["track_count"]),
            created_at=str(raw["created_at"]),
            updated_at=str(raw["updated_at"]),
        )

    def get(
        self, *, user_id: str, category_id: str
    ) -> CategoryRow | None:
        sql = (
            self._CATEGORY_SELECT
            + " WHERE c.id = :category_id"
              " AND c.user_id = :user_id"
              " AND c.deleted_at IS NULL"
        )
        rows = self._data_api.execute(
            sql,
            {"category_id": category_id, "user_id": user_id},
        )
        return self._row(rows[0]) if rows else None

    def list_by_style(
        self,
        *,
        user_id: str,
        style_id: str,
        limit: int,
        offset: int,
    ) -> PaginatedResult[CategoryRow]:
        sql = (
            self._CATEGORY_SELECT
            + " WHERE c.user_id = :user_id"
              " AND c.style_id = :style_id"
              " AND c.deleted_at IS NULL"
              " ORDER BY c.position ASC, c.created_at DESC, c.id ASC"
              " LIMIT :limit OFFSET :offset"
        )
        rows = self._data_api.execute(
            sql,
            {
                "user_id": user_id,
                "style_id": style_id,
                "limit": limit,
                "offset": offset,
            },
        )
        total_rows = self._data_api.execute(
            """
            SELECT COUNT(*) AS total
            FROM categories
            WHERE user_id = :user_id
              AND style_id = :style_id
              AND deleted_at IS NULL
            """,
            {"user_id": user_id, "style_id": style_id},
        )
        total = int(total_rows[0]["total"]) if total_rows else 0
        return PaginatedResult(
            items=[self._row(r) for r in rows],
            total=total,
            limit=limit,
            offset=offset,
        )

    def list_all(
        self, *, user_id: str, limit: int, offset: int
    ) -> PaginatedResult[CategoryRow]:
        sql = (
            self._CATEGORY_SELECT
            + " WHERE c.user_id = :user_id"
              " AND c.deleted_at IS NULL"
              " ORDER BY c.created_at DESC, c.id ASC"
              " LIMIT :limit OFFSET :offset"
        )
        rows = self._data_api.execute(
            sql,
            {"user_id": user_id, "limit": limit, "offset": offset},
        )
        total_rows = self._data_api.execute(
            """
            SELECT COUNT(*) AS total
            FROM categories
            WHERE user_id = :user_id
              AND deleted_at IS NULL
            """,
            {"user_id": user_id},
        )
        total = int(total_rows[0]["total"]) if total_rows else 0
        return PaginatedResult(
            items=[self._row(r) for r in rows],
            total=total,
            limit=limit,
            offset=offset,
        )

    # Remaining methods filled in by Tasks 8–13.


def create_default_categories_repository() -> CategoriesRepository | None:
    settings = get_data_api_settings()
    if not settings.is_configured:
        return None
    from collector.data_api import create_default_data_api_client

    data_api = create_default_data_api_client(
        resource_arn=str(settings.aurora_cluster_arn),
        secret_arn=str(settings.aurora_secret_arn),
        database=settings.aurora_database,
    )
    return CategoriesRepository(data_api=data_api)

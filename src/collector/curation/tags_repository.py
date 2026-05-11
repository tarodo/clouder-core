"""Aurora Data API repository for spec track-tags (2026-05-11).

Tenancy: every method takes `user_id` and includes it in WHERE.
Cross-user access yields zero rows (mapped to 404 by the handler).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from collector.data_api import DataAPIClient
from collector.settings import get_data_api_settings

from . import (
    PaginatedResult,
    TagNameConflictError,
    TagNotFoundError,
)


@dataclass(frozen=True)
class TagRow:
    id: str
    name: str
    color: str
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class TrackTagRow:
    track_id: str
    tag_id: str
    name: str
    color: str


def _row_to_tag(r: dict[str, Any]) -> TagRow:
    return TagRow(
        id=r["id"],
        name=r["name"],
        color=r["color"],
        created_at=str(r["created_at"]),
        updated_at=str(r["updated_at"]),
    )


class TagsRepository:
    def __init__(self, data_api: DataAPIClient) -> None:
        self._data_api = data_api

    # --- vocabulary CRUD --------------------------------------------------

    def create_tag(
        self,
        *,
        user_id: str,
        tag_id: str,
        name: str,
        normalized_name: str,
        color: str,
        now: datetime,
    ) -> TagRow:
        try:
            rows = self._data_api.execute(
                """
                INSERT INTO user_tags (
                    id, user_id, name, normalized_name, color, created_at, updated_at
                ) VALUES (
                    :id, :user_id, :name, :normalized_name, :color, :created_at, :updated_at
                )
                RETURNING id, name, color, created_at, updated_at
                """,
                {
                    "id": tag_id,
                    "user_id": user_id,
                    "name": name,
                    "normalized_name": normalized_name,
                    "color": color,
                    "created_at": now,
                    "updated_at": now,
                },
            )
        except Exception as exc:
            if "uq_user_tags_user_normalized_name" in str(exc):
                raise TagNameConflictError(
                    "Tag with this name already exists"
                ) from exc
            raise
        return _row_to_tag(rows[0])

    def list_tags(
        self,
        *,
        user_id: str,
        limit: int,
        offset: int,
        search: str | None,
    ) -> PaginatedResult[TagRow]:
        params: dict[str, Any] = {
            "user_id": user_id,
            "limit": limit,
            "offset": offset,
        }
        search_clause = ""
        if search and search.strip():
            search_clause = " AND normalized_name LIKE :search "
            params["search"] = f"{search.strip().lower()}%"
        rows = self._data_api.execute(
            f"""
            SELECT id, name, color, created_at, updated_at
            FROM user_tags
            WHERE user_id = :user_id {search_clause}
            ORDER BY normalized_name ASC
            LIMIT :limit OFFSET :offset
            """,
            params,
        )
        count_params: dict[str, Any] = {"user_id": user_id}
        count_clause = ""
        if "search" in params:
            count_clause = " AND normalized_name LIKE :search "
            count_params["search"] = params["search"]
        total_rows = self._data_api.execute(
            f"SELECT COUNT(*) AS total FROM user_tags WHERE user_id = :user_id {count_clause}",
            count_params,
        )
        total = int(total_rows[0]["total"]) if total_rows else 0
        items = [_row_to_tag(r) for r in rows]
        return PaginatedResult(items=items, total=total, limit=limit, offset=offset)

    def get_tag(self, *, user_id: str, tag_id: str) -> TagRow | None:
        rows = self._data_api.execute(
            """
            SELECT id, name, color, created_at, updated_at
            FROM user_tags
            WHERE user_id = :user_id AND id = :tag_id
            """,
            {"user_id": user_id, "tag_id": tag_id},
        )
        if not rows:
            return None
        return _row_to_tag(rows[0])

    def rename_tag(
        self,
        *,
        user_id: str,
        tag_id: str,
        name: str | None,
        normalized_name: str | None,
        color: str | None,
        now: datetime,
    ) -> TagRow:
        sets: list[str] = ["updated_at = :updated_at"]
        params: dict[str, Any] = {
            "user_id": user_id,
            "tag_id": tag_id,
            "updated_at": now,
        }
        if name is not None:
            sets.append("name = :name")
            params["name"] = name
            sets.append("normalized_name = :normalized_name")
            params["normalized_name"] = normalized_name
        if color is not None:
            sets.append("color = :color")
            params["color"] = color
        try:
            rows = self._data_api.execute(
                f"""
                UPDATE user_tags SET {", ".join(sets)}
                WHERE user_id = :user_id AND id = :tag_id
                RETURNING id, name, color, created_at, updated_at
                """,
                params,
            )
        except Exception as exc:
            if "uq_user_tags_user_normalized_name" in str(exc):
                raise TagNameConflictError(
                    "Tag with this name already exists"
                ) from exc
            raise
        if not rows:
            raise TagNotFoundError()
        return _row_to_tag(rows[0])

    def delete_tag(self, *, user_id: str, tag_id: str) -> bool:
        rows = self._data_api.execute(
            """
            DELETE FROM user_tags
            WHERE user_id = :user_id AND id = :tag_id
            RETURNING id
            """,
            {"user_id": user_id, "tag_id": tag_id},
        )
        return bool(rows)


def create_default_tags_repository() -> TagsRepository | None:
    settings = get_data_api_settings()
    if not settings.is_configured:
        return None
    from collector.data_api import create_default_data_api_client

    data_api = create_default_data_api_client(
        resource_arn=str(settings.aurora_cluster_arn),
        secret_arn=str(settings.aurora_secret_arn),
        database=settings.aurora_database,
    )
    return TagsRepository(data_api=data_api)

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
    TrackNotInAnyCategoryError,
)


@dataclass(frozen=True)
class TagRow:
    id: str
    name: str
    color: str | None
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class TrackTagRow:
    track_id: str
    tag_id: str
    name: str
    color: str | None


def _row_to_tag(r: dict[str, Any]) -> TagRow:
    return TagRow(
        id=r["id"],
        name=r["name"],
        color=r.get("color"),
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
        color: str | None,
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
        clear_color: bool = False,
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
        if color is not None or clear_color:
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

    # --- track-tag ops ----------------------------------------------------

    def _assert_track_in_any_active_category(
        self, *, user_id: str, track_id: str, transaction_id: str | None
    ) -> None:
        rows = self._data_api.execute(
            """
            SELECT 1
            FROM category_tracks ct
            JOIN categories c ON c.id = ct.category_id
            WHERE c.user_id = :user_id
              AND ct.track_id = :track_id
              AND c.deleted_at IS NULL
            LIMIT 1
            """,
            {"user_id": user_id, "track_id": track_id},
            transaction_id=transaction_id,
        )
        if not rows:
            raise TrackNotInAnyCategoryError(
                "Track is not in any of the user's categories",
            )

    def _assert_tag_ids_owned(
        self,
        *,
        user_id: str,
        tag_ids: list[str],
        transaction_id: str | None,
    ) -> None:
        if not tag_ids:
            return
        placeholders = ", ".join(f":tg{i}" for i in range(len(tag_ids)))
        params: dict[str, Any] = {f"tg{i}": tid for i, tid in enumerate(tag_ids)}
        params["user_id"] = user_id
        found = self._data_api.execute(
            f"SELECT id FROM user_tags WHERE user_id = :user_id AND id IN ({placeholders})",
            params,
            transaction_id=transaction_id,
        )
        found_ids = {r["id"] for r in found}
        missing = [t for t in tag_ids if t not in found_ids]
        if missing:
            raise TagNotFoundError(f"Unknown tag id: {missing[0]}")

    def _select_track_tags(
        self,
        *,
        user_id: str,
        track_id: str,
        transaction_id: str | None,
    ) -> list[TagRow]:
        rows = self._data_api.execute(
            """
            SELECT ut.id, ut.name, ut.color, ut.created_at, ut.updated_at
            FROM track_tags tt
            JOIN user_tags ut ON ut.id = tt.tag_id
            WHERE tt.user_id = :user_id AND tt.track_id = :track_id
            ORDER BY ut.normalized_name ASC
            """,
            {"user_id": user_id, "track_id": track_id},
            transaction_id=transaction_id,
        )
        return [_row_to_tag(r) for r in rows]

    def set_track_tags(
        self,
        *,
        user_id: str,
        track_id: str,
        tag_ids: list[str],
        now: datetime,
        transaction_id: str | None = None,
    ) -> list[TagRow]:
        # de-dup while preserving caller order
        ordered: list[str] = []
        seen: set[str] = set()
        for t in tag_ids:
            if t not in seen:
                ordered.append(t)
                seen.add(t)

        def _do(tx_id: str) -> list[TagRow]:
            self._assert_track_in_any_active_category(
                user_id=user_id, track_id=track_id, transaction_id=tx_id,
            )
            self._assert_tag_ids_owned(
                user_id=user_id, tag_ids=ordered, transaction_id=tx_id,
            )
            self._data_api.execute(
                "DELETE FROM track_tags WHERE user_id = :user_id AND track_id = :track_id",
                {"user_id": user_id, "track_id": track_id},
                transaction_id=tx_id,
            )
            if ordered:
                value_clauses: list[str] = []
                params: dict[str, Any] = {
                    "user_id": user_id,
                    "track_id": track_id,
                    "created_at": now,
                }
                for i, tid in enumerate(ordered):
                    value_clauses.append(
                        f"(:user_id, :track_id, :tg{i}, :created_at)"
                    )
                    params[f"tg{i}"] = tid
                self._data_api.execute(
                    f"""
                    INSERT INTO track_tags (user_id, track_id, tag_id, created_at)
                    VALUES {", ".join(value_clauses)}
                    """,
                    params,
                    transaction_id=tx_id,
                )
            return self._select_track_tags(
                user_id=user_id, track_id=track_id, transaction_id=tx_id,
            )

        if transaction_id is not None:
            return _do(transaction_id)
        with self._data_api.transaction() as tx_id:
            return _do(tx_id)

    def add_track_tag(
        self,
        *,
        user_id: str,
        track_id: str,
        tag_id: str,
        now: datetime,
        transaction_id: str | None = None,
    ) -> list[TagRow]:
        def _do(tx_id: str) -> list[TagRow]:
            self._assert_track_in_any_active_category(
                user_id=user_id, track_id=track_id, transaction_id=tx_id,
            )
            self._assert_tag_ids_owned(
                user_id=user_id, tag_ids=[tag_id], transaction_id=tx_id,
            )
            self._data_api.execute(
                """
                INSERT INTO track_tags (user_id, track_id, tag_id, created_at)
                VALUES (:user_id, :track_id, :tag_id, :created_at)
                ON CONFLICT (user_id, track_id, tag_id) DO NOTHING
                """,
                {
                    "user_id": user_id,
                    "track_id": track_id,
                    "tag_id": tag_id,
                    "created_at": now,
                },
                transaction_id=tx_id,
            )
            return self._select_track_tags(
                user_id=user_id, track_id=track_id, transaction_id=tx_id,
            )

        if transaction_id is not None:
            return _do(transaction_id)
        with self._data_api.transaction() as tx_id:
            return _do(tx_id)

    def remove_track_tag(
        self, *, user_id: str, track_id: str, tag_id: str
    ) -> bool:
        rows = self._data_api.execute(
            """
            DELETE FROM track_tags
            WHERE user_id = :user_id AND track_id = :track_id AND tag_id = :tag_id
            RETURNING tag_id
            """,
            {"user_id": user_id, "track_id": track_id, "tag_id": tag_id},
        )
        return bool(rows)

    def list_tags_for_tracks(
        self, *, user_id: str, track_ids: list[str]
    ) -> dict[str, list[TrackTagRow]]:
        if not track_ids:
            return {}
        placeholders = ", ".join(f":t{i}" for i in range(len(track_ids)))
        params: dict[str, Any] = {f"t{i}": tid for i, tid in enumerate(track_ids)}
        params["user_id"] = user_id
        rows = self._data_api.execute(
            f"""
            SELECT tt.track_id, ut.id, ut.name, ut.color
            FROM track_tags tt
            JOIN user_tags ut ON ut.id = tt.tag_id
            WHERE tt.user_id = :user_id AND tt.track_id IN ({placeholders})
            ORDER BY tt.track_id, ut.normalized_name ASC
            """,
            params,
        )
        grouped: dict[str, list[TrackTagRow]] = {}
        for r in rows:
            grouped.setdefault(r["track_id"], []).append(
                TrackTagRow(
                    track_id=r["track_id"],
                    tag_id=r["id"],
                    name=r["name"],
                    color=r["color"],
                )
            )
        return grouped

    def cleanup_orphaned_track_tags(
        self,
        *,
        user_id: str,
        track_ids: list[str],
        transaction_id: str,
    ) -> int:
        if not track_ids:
            return 0
        placeholders = ", ".join(f":t{i}" for i in range(len(track_ids)))
        params: dict[str, Any] = {f"t{i}": tid for i, tid in enumerate(track_ids)}
        params["user_id"] = user_id
        rows = self._data_api.execute(
            f"""
            DELETE FROM track_tags
            WHERE user_id = :user_id
              AND track_id IN ({placeholders})
              AND NOT EXISTS (
                  SELECT 1 FROM category_tracks ct
                  JOIN categories c ON c.id = ct.category_id
                  WHERE ct.track_id = track_tags.track_id
                    AND c.user_id = :user_id
                    AND c.deleted_at IS NULL
              )
            RETURNING track_id
            """,
            params,
            transaction_id=transaction_id,
        )
        return len(rows)


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

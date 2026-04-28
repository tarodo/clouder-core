"""Aurora Data API repository for spec-C categories.

Tenancy: every method takes `user_id` and includes it in WHERE.
Cross-user access yields zero rows (mapped to 404 by the handler).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Mapping, Sequence

from collector.data_api import DataAPIClient
from collector.logging_utils import log_event
from collector.settings import get_data_api_settings

from . import (
    NameConflictError,
    NotFoundError,
    OrderMismatchError,
    PaginatedResult,
    utc_now,
)
from .categories_service import validate_reorder_set


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
        correlation_id: str | None = None,
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
            # Spec-D side-effect (D7): snapshot the new category into every
            # active triage block of the same (user, style) so STAGING
            # buckets exist for it. Must run inside the same TX as the
            # INSERT above to keep the create atomic.
            from .triage_repository import TriageRepository

            triage_repo = TriageRepository(self._data_api)
            inserted_into_blocks = (
                triage_repo.snapshot_category_into_active_blocks(
                    user_id=user_id,
                    style_id=style_id,
                    category_id=row["id"],
                    transaction_id=tx_id,
                )
            )
            log_event(
                "INFO",
                "category_snapshot_created",
                correlation_id=correlation_id,
                user_id=user_id,
                category_id=row["id"],
                style_id=style_id,
                blocks_snapshot_into=inserted_into_blocks,
            )
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

    def rename(
        self,
        *,
        user_id: str,
        category_id: str,
        name: str,
        normalized_name: str,
        now: datetime,
    ) -> CategoryRow:
        try:
            updated = self._data_api.execute(
                """
                UPDATE categories
                SET name = :name,
                    normalized_name = :normalized_name,
                    updated_at = :now
                WHERE id = :category_id
                  AND user_id = :user_id
                  AND deleted_at IS NULL
                RETURNING id
                """,
                {
                    "category_id": category_id,
                    "user_id": user_id,
                    "name": name,
                    "normalized_name": normalized_name,
                    "now": now,
                },
            )
        except Exception as exc:
            if "uq_categories_user_style_normname" in str(exc):
                raise NameConflictError(
                    "Category name already exists in this style"
                ) from exc
            raise

        if not updated:
            raise NotFoundError(
                "category_not_found", "Category not found"
            )

        row = self.get(user_id=user_id, category_id=category_id)
        if row is None:
            # Race: another caller deleted it between UPDATE and SELECT.
            raise NotFoundError(
                "category_not_found", "Category not found"
            )
        return row

    def soft_delete(
        self,
        *,
        user_id: str,
        category_id: str,
        now: datetime,
        correlation_id: str | None = None,
    ) -> bool:
        with self._data_api.transaction() as tx_id:
            rows = self._data_api.execute(
                """
                UPDATE categories
                SET deleted_at = :now,
                    updated_at = :now
                WHERE id = :category_id
                  AND user_id = :user_id
                  AND deleted_at IS NULL
                RETURNING id
                """,
                {
                    "category_id": category_id,
                    "user_id": user_id,
                    "now": now,
                },
                transaction_id=tx_id,
            )
            if not rows:
                return False

            # Spec-D side-effect (D8): mark every STAGING bucket for this
            # category inactive across active triage blocks so move/transfer
            # routes reject them (`target_bucket_inactive`). Must run in the
            # same TX as the UPDATE above.
            from .triage_repository import TriageRepository

            triage_repo = TriageRepository(self._data_api)
            inactivated = triage_repo.mark_staging_inactive_for_category(
                user_id=user_id,
                category_id=category_id,
                transaction_id=tx_id,
            )
            log_event(
                "INFO",
                "category_staging_inactive",
                correlation_id=correlation_id,
                user_id=user_id,
                category_id=category_id,
                inactivated_buckets=inactivated,
            )
            return True

    def reorder(
        self,
        *,
        user_id: str,
        style_id: str,
        ordered_ids: Sequence[str],
        now: datetime,
    ) -> list[CategoryRow]:
        with self._data_api.transaction() as tx_id:
            style_rows = self._data_api.execute(
                "SELECT id FROM clouder_styles WHERE id = :style_id",
                {"style_id": style_id},
                transaction_id=tx_id,
            )
            if not style_rows:
                raise NotFoundError("style_not_found", "Style not found")

            current_rows = self._data_api.execute(
                """
                SELECT id FROM categories
                WHERE user_id = :user_id
                  AND style_id = :style_id
                  AND deleted_at IS NULL
                """,
                {"user_id": user_id, "style_id": style_id},
                transaction_id=tx_id,
            )
            actual_ids = {r["id"] for r in current_rows}
            validate_reorder_set(actual=actual_ids, requested=ordered_ids)

            for idx, cid in enumerate(ordered_ids):
                self._data_api.execute(
                    """
                    UPDATE categories
                    SET position = :position,
                        updated_at = :now
                    WHERE id = :category_id
                      AND user_id = :user_id
                      AND style_id = :style_id
                      AND deleted_at IS NULL
                    RETURNING id
                    """,
                    {
                        "position": idx,
                        "now": now,
                        "category_id": cid,
                        "user_id": user_id,
                        "style_id": style_id,
                    },
                    transaction_id=tx_id,
                )

            # Re-select with full shape, ordered.
            sql = (
                self._CATEGORY_SELECT
                + " WHERE c.user_id = :user_id"
                  " AND c.style_id = :style_id"
                  " AND c.deleted_at IS NULL"
                  " ORDER BY c.position ASC, c.created_at DESC, c.id ASC"
            )
            rows = self._data_api.execute(
                sql,
                {"user_id": user_id, "style_id": style_id},
                transaction_id=tx_id,
            )
            return [self._row(r) for r in rows]

    def add_tracks_bulk(
        self,
        *,
        user_id: str,
        category_id: str,
        items: Sequence[tuple[str, str | None]],
        now: datetime,
        transaction_id: str | None = None,
    ) -> int:
        """Insert (track, source_triage_block_id) pairs idempotently.

        Used by both the single-track HTTP path and spec-D's triage finalize.
        When called inside an existing transaction (spec-D), pass `transaction_id`
        so reads see in-flight writes (CLAUDE.md note on Aurora Data API).

        Returns the count of rows actually inserted (excludes existing).
        Raises NotFoundError("category_not_found" or "track_not_found").
        """
        cat_rows = self._data_api.execute(
            """
            SELECT id FROM categories
            WHERE id = :category_id
              AND user_id = :user_id
              AND deleted_at IS NULL
            """,
            {"category_id": category_id, "user_id": user_id},
            transaction_id=transaction_id,
        )
        if not cat_rows:
            raise NotFoundError("category_not_found", "Category not found")

        if not items:
            return 0

        track_ids = list({tid for tid, _ in items})
        # Build an IN-list parametrically (Data API forbids ANY/array on plain strings).
        placeholders = ", ".join(f":t{i}" for i in range(len(track_ids)))
        params: dict[str, Any] = {f"t{i}": tid for i, tid in enumerate(track_ids)}
        existing = self._data_api.execute(
            f"SELECT id FROM clouder_tracks WHERE id IN ({placeholders})",
            params,
            transaction_id=transaction_id,
        )
        existing_ids = {r["id"] for r in existing}
        missing = [tid for tid in track_ids if tid not in existing_ids]
        if missing:
            raise NotFoundError(
                "track_not_found", f"Track(s) not found: {missing[0]}"
            )

        # Dedup items by track_id (first-src-wins). Postgres aborts an
        # ON CONFLICT DO NOTHING statement if the same target row appears
        # twice in VALUES — happens if the caller passes the same track_id
        # twice with different source_triage_block_id.
        seen: set[str] = set()
        unique_items: list[tuple[str, str | None]] = []
        for tid, src in items:
            if tid in seen:
                continue
            seen.add(tid)
            unique_items.append((tid, src))

        # Build a multi-row INSERT.
        value_rows = []
        insert_params: dict[str, Any] = {
            "category_id": category_id,
            "now": now,
        }
        for i, (tid, src) in enumerate(unique_items):
            value_rows.append(
                f"(:category_id, :tid_{i}, :now, :src_{i})"
            )
            insert_params[f"tid_{i}"] = tid
            insert_params[f"src_{i}"] = src
        sql = f"""
            INSERT INTO category_tracks (
                category_id, track_id, added_at, source_triage_block_id
            ) VALUES {", ".join(value_rows)}
            ON CONFLICT (category_id, track_id) DO NOTHING
            RETURNING track_id
        """
        rows = self._data_api.execute(
            sql, insert_params, transaction_id=transaction_id
        )
        return len(rows)

    def add_track(
        self,
        *,
        user_id: str,
        category_id: str,
        track_id: str,
        source_triage_block_id: str | None,
        now: datetime,
    ) -> tuple[Mapping[str, Any], bool]:
        """Add one track to a category. Idempotent on (category_id, track_id).

        Returns ({added_at, source_triage_block_id}, was_newly_added).

        Always re-SELECTs after the bulk insert so both branches return the
        canonical stored values in the same Data API string format. (Without
        this, the newly-added branch returned `now.isoformat()` while the
        already-present branch returned the Data API's own format — inconsistent.)
        """
        inserted = self.add_tracks_bulk(
            user_id=user_id,
            category_id=category_id,
            items=[(track_id, source_triage_block_id)],
            now=now,
        )

        rows = self._data_api.execute(
            """
            SELECT added_at, source_triage_block_id
            FROM category_tracks
            WHERE category_id = :category_id
              AND track_id = :track_id
            """,
            {"category_id": category_id, "track_id": track_id},
        )
        if not rows:
            # Race: track was removed between INSERT and SELECT. Treat as
            # not present any more — the caller's add was effectively a no-op.
            raise NotFoundError(
                "track_not_in_category",
                "Track was not in category after insert (race)",
            )
        row = rows[0]
        return (
            {
                "added_at": str(row["added_at"]),
                "source_triage_block_id": row["source_triage_block_id"],
            },
            bool(inserted),
        )

    def remove_track(
        self, *, user_id: str, category_id: str, track_id: str
    ) -> bool:
        cat_rows = self._data_api.execute(
            """
            SELECT id FROM categories
            WHERE id = :category_id
              AND user_id = :user_id
              AND deleted_at IS NULL
            """,
            {"category_id": category_id, "user_id": user_id},
        )
        if not cat_rows:
            raise NotFoundError("category_not_found", "Category not found")

        rows = self._data_api.execute(
            """
            DELETE FROM category_tracks
            WHERE category_id = :category_id
              AND track_id = :track_id
            RETURNING track_id
            """,
            {"category_id": category_id, "track_id": track_id},
        )
        return bool(rows)

    def list_tracks(
        self,
        *,
        user_id: str,
        category_id: str,
        limit: int,
        offset: int,
        search: str | None,
    ) -> PaginatedResult[TrackInCategoryRow]:
        cat_rows = self._data_api.execute(
            """
            SELECT id FROM categories
            WHERE id = :category_id
              AND user_id = :user_id
              AND deleted_at IS NULL
            """,
            {"category_id": category_id, "user_id": user_id},
        )
        if not cat_rows:
            raise NotFoundError("category_not_found", "Category not found")

        params: dict[str, Any] = {
            "category_id": category_id,
            "limit": limit,
            "offset": offset,
        }
        search_clause = ""
        if search and search.strip():
            search_clause = " AND t.normalized_title ILIKE :search "
            params["search"] = f"%{search.strip().lower()}%"

        sql = f"""
            SELECT
                t.id, t.title, t.mix_name, t.isrc, t.bpm, t.length_ms,
                t.publish_date, t.spotify_id, t.release_type, t.is_ai_suspected,
                STRING_AGG(a.name, ',' ORDER BY cta.role, a.name) AS artist_names,
                ct.added_at, ct.source_triage_block_id
            FROM category_tracks ct
            JOIN clouder_tracks t ON t.id = ct.track_id
            LEFT JOIN clouder_track_artists cta ON cta.track_id = t.id
            LEFT JOIN clouder_artists a ON a.id = cta.artist_id
            WHERE ct.category_id = :category_id
              {search_clause}
            GROUP BY t.id, ct.added_at, ct.source_triage_block_id
            ORDER BY ct.added_at DESC, t.id ASC
            LIMIT :limit OFFSET :offset
        """
        rows = self._data_api.execute(sql, params)

        count_params: dict[str, Any] = {"category_id": category_id}
        count_clause = ""
        if "search" in params:
            count_clause = " AND t.normalized_title ILIKE :search "
            count_params["search"] = params["search"]
        total_rows = self._data_api.execute(
            f"""
            SELECT COUNT(*) AS total
            FROM category_tracks ct
            JOIN clouder_tracks t ON t.id = ct.track_id
            WHERE ct.category_id = :category_id
              {count_clause}
            """,
            count_params,
        )
        total = int(total_rows[0]["total"]) if total_rows else 0

        items = []
        for r in rows:
            artists_raw = r.pop("artist_names")
            track = dict(r)
            track["artists"] = (
                [n.strip() for n in artists_raw.split(",")] if artists_raw else []
            )
            added_at = track.pop("added_at")
            source_id = track.pop("source_triage_block_id")
            items.append(
                TrackInCategoryRow(
                    track=track,
                    added_at=str(added_at),
                    source_triage_block_id=source_id,
                )
            )
        return PaginatedResult(items=items, total=total, limit=limit, offset=offset)

    # Remaining methods filled in by Task 13.


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

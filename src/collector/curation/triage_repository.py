"""Aurora Data API repository for spec-D triage."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date as date_type, datetime
from typing import Any, Iterable, Mapping, Sequence
from uuid import uuid4

from collector.curation import (
    InactiveBucketError,
    InactiveStagingFinalizeError,
    InvalidStateError,
    NotFoundError,
    StyleMismatchError,
    TracksNotInSourceError,
    ValidationError,
    utc_now,
)
from collector.curation.triage_service import (
    BUCKET_TYPE_DISCARD,
    BUCKET_TYPE_NEW,
    BUCKET_TYPE_NOT,
    BUCKET_TYPE_OLD,
    BUCKET_TYPE_STAGING,
    BUCKET_TYPE_UNCLASSIFIED,
    TECHNICAL_BUCKET_DISPLAY_ORDER,
    TECHNICAL_BUCKET_TYPES,
    TRACK_IDS_MAX,
)
from collector.data_api import DataAPIClient


@dataclass(frozen=True)
class TriageBucketRow:
    id: str
    bucket_type: str
    category_id: str | None
    category_name: str | None
    inactive: bool
    track_count: int


@dataclass(frozen=True)
class TriageBlockRow:
    id: str
    user_id: str
    style_id: str
    style_name: str
    name: str
    date_from: str  # ISO YYYY-MM-DD as returned by Data API
    date_to: str
    status: str
    created_at: str  # ISO datetime
    updated_at: str
    finalized_at: str | None
    buckets: Sequence[TriageBucketRow] = field(default_factory=tuple)


@dataclass(frozen=True)
class TriageBlockSummaryRow:
    id: str
    user_id: str
    style_id: str
    style_name: str
    name: str
    date_from: str
    date_to: str
    status: str
    created_at: str
    updated_at: str
    finalized_at: str | None
    track_count: int


@dataclass(frozen=True)
class BucketTrackRowOut:
    """Row returned by GET /triage/blocks/{id}/buckets/{bucket_id}/tracks."""

    track_id: str
    title: str
    mix_name: str | None
    isrc: str | None
    bpm: int | None
    length_ms: int | None
    publish_date: str | None
    spotify_release_date: str | None
    spotify_id: str | None
    release_type: str | None
    is_ai_suspected: bool
    artists: tuple[str, ...]
    added_at: str


@dataclass(frozen=True)
class MoveResult:
    moved: int


@dataclass(frozen=True)
class TransferResult:
    transferred: int


@dataclass(frozen=True)
class FinalizeResult:
    block: TriageBlockRow
    promoted: dict[str, int]


class TriageRepository:
    def __init__(self, data_api: DataAPIClient) -> None:
        self._data_api = data_api

    # --- writes -------------------------------------------------------

    def create_block(
        self,
        *,
        user_id: str,
        style_id: str,
        name: str,
        date_from: date_type,
        date_to: date_type,
    ) -> TriageBlockRow:
        now = utc_now()

        with self._data_api.transaction() as tx_id:
            # 1. Verify style exists (and grab name for response shape).
            style_rows = self._data_api.execute(
                """
                SELECT id, name FROM clouder_styles WHERE id = :style_id
                """,
                {"style_id": style_id},
                transaction_id=tx_id,
            )
            if not style_rows:
                raise NotFoundError(
                    "style_not_found",
                    f"clouder_styles row not found: {style_id}",
                )
            style_name = style_rows[0]["name"]

            # 2. Insert triage_blocks row.
            block_id = str(uuid4())
            self._data_api.execute(
                """
                INSERT INTO triage_blocks (
                    id, user_id, style_id, name,
                    date_from, date_to, status,
                    created_at, updated_at
                ) VALUES (
                    :id, :user_id, :style_id, :name,
                    :date_from, :date_to, 'IN_PROGRESS',
                    :now, :now
                )
                """,
                {
                    "id": block_id,
                    "user_id": user_id,
                    "style_id": style_id,
                    "name": name,
                    "date_from": date_from,
                    "date_to": date_to,
                    "now": now,
                },
                transaction_id=tx_id,
            )

            # 3. Insert the 5 technical buckets in one statement and capture
            #    the resulting ids via RETURNING.
            tech_value_rows: list[str] = []
            tech_params: dict[str, Any] = {
                "block_id": block_id,
                "now": now,
            }
            for i, bucket_type in enumerate(TECHNICAL_BUCKET_TYPES):
                tech_value_rows.append(
                    f"(:tid_{i}, :block_id, :btype_{i}, NULL, FALSE, :now)"
                )
                tech_params[f"tid_{i}"] = str(uuid4())
                tech_params[f"btype_{i}"] = bucket_type
            tech_rows = self._data_api.execute(
                f"""
                INSERT INTO triage_buckets (
                    id, triage_block_id, bucket_type, category_id,
                    inactive, created_at
                ) VALUES {", ".join(tech_value_rows)}
                RETURNING id, bucket_type
                """,
                tech_params,
                transaction_id=tx_id,
            )
            tech_bucket_id_by_type: dict[str, str] = {
                r["bucket_type"]: r["id"] for r in tech_rows
            }

            # 4. Snapshot one staging bucket per alive category.
            categories = self._data_api.execute(
                """
                SELECT id FROM categories
                WHERE user_id = :user_id
                  AND style_id = :style_id
                  AND deleted_at IS NULL
                ORDER BY position ASC, created_at DESC, id ASC
                """,
                {"user_id": user_id, "style_id": style_id},
                transaction_id=tx_id,
            )
            if categories:
                stg_value_rows: list[str] = []
                stg_params: dict[str, Any] = {
                    "block_id": block_id,
                    "now": now,
                }
                for i, cat in enumerate(categories):
                    stg_value_rows.append(
                        f"(:sid_{i}, :block_id, 'STAGING', :cid_{i}, FALSE, :now)"
                    )
                    stg_params[f"sid_{i}"] = str(uuid4())
                    stg_params[f"cid_{i}"] = cat["id"]
                self._data_api.execute(
                    f"""
                    INSERT INTO triage_buckets (
                        id, triage_block_id, bucket_type, category_id,
                        inactive, created_at
                    ) VALUES {", ".join(stg_value_rows)}
                    """,
                    stg_params,
                    transaction_id=tx_id,
                )

            # 5. Classify and insert tracks (R4 in one INSERT FROM SELECT).
            self._data_api.execute(
                """
                INSERT INTO triage_bucket_tracks
                    (triage_bucket_id, track_id, added_at)
                SELECT
                    CASE
                        WHEN t.spotify_release_date IS NULL
                            THEN :unclassified_bucket_id
                        WHEN t.spotify_release_date < :date_from
                            THEN :old_bucket_id
                        WHEN t.release_type = 'compilation'
                            THEN :not_bucket_id
                        ELSE :new_bucket_id
                    END,
                    t.id,
                    :now
                FROM clouder_tracks t
                WHERE t.style_id = :style_id
                  AND t.publish_date BETWEEN :date_from AND :date_to
                  AND NOT EXISTS (
                    SELECT 1
                    FROM category_tracks ct
                    JOIN categories c ON ct.category_id = c.id
                    WHERE c.user_id = :user_id
                      AND c.style_id = :style_id
                      AND c.deleted_at IS NULL
                      AND ct.track_id = t.id
                  )
                """,
                {
                    "user_id": user_id,
                    "style_id": style_id,
                    "date_from": date_from,
                    "date_to": date_to,
                    "now": now,
                    "new_bucket_id": tech_bucket_id_by_type[BUCKET_TYPE_NEW],
                    "old_bucket_id": tech_bucket_id_by_type[BUCKET_TYPE_OLD],
                    "not_bucket_id": tech_bucket_id_by_type[BUCKET_TYPE_NOT],
                    "unclassified_bucket_id": tech_bucket_id_by_type[
                        BUCKET_TYPE_UNCLASSIFIED
                    ],
                },
                transaction_id=tx_id,
            )

            # 6. Re-fetch the assembled block detail (with style_name and
            #    buckets) inside the same TX so callers see consistent state.
            block = self._fetch_block_detail(
                user_id=user_id, block_id=block_id, transaction_id=tx_id
            )

        if block is None:  # pragma: no cover - we just inserted
            raise RuntimeError("create_block: post-insert fetch returned None")
        return block

    def move_tracks(
        self,
        *,
        user_id: str,
        block_id: str,
        from_bucket_id: str,
        to_bucket_id: str,
        track_ids: Sequence[str],
    ) -> MoveResult:
        raise NotImplementedError

    def transfer_tracks(
        self,
        *,
        user_id: str,
        src_block_id: str,
        target_bucket_id: str,
        track_ids: Sequence[str],
    ) -> TransferResult:
        raise NotImplementedError

    def finalize_block(
        self,
        *,
        user_id: str,
        block_id: str,
        categories_repository: Any,
    ) -> FinalizeResult:
        raise NotImplementedError

    def soft_delete_block(
        self, *, user_id: str, block_id: str
    ) -> bool:
        raise NotImplementedError

    def snapshot_category_into_active_blocks(
        self,
        *,
        user_id: str,
        style_id: str,
        category_id: str,
        transaction_id: str | None = None,
    ) -> int:
        raise NotImplementedError

    def mark_staging_inactive_for_category(
        self,
        *,
        user_id: str,
        category_id: str,
        transaction_id: str | None = None,
    ) -> int:
        raise NotImplementedError

    # --- reads --------------------------------------------------------

    def get_block(
        self, *, user_id: str, block_id: str
    ) -> TriageBlockRow | None:
        return self._fetch_block_detail(
            user_id=user_id, block_id=block_id, transaction_id=None
        )

    def list_blocks_by_style(
        self,
        *,
        user_id: str,
        style_id: str,
        limit: int,
        offset: int,
        status: str | None = None,
    ) -> tuple[list[TriageBlockSummaryRow], int]:
        style_rows = self._data_api.execute(
            "SELECT id FROM clouder_styles WHERE id = :style_id",
            {"style_id": style_id},
        )
        if not style_rows:
            raise NotFoundError(
                "style_not_found",
                f"clouder_styles row not found: {style_id}",
            )

        sql_filter = ""
        params: dict[str, Any] = {
            "user_id": user_id,
            "style_id": style_id,
            "limit": limit,
            "offset": offset,
        }
        if status is not None:
            sql_filter = " AND tb.status = :status"
            params["status"] = status

        rows = self._data_api.execute(
            f"""
            SELECT
                tb.id, tb.user_id, tb.style_id,
                cs.name AS style_name,
                tb.name,
                tb.date_from, tb.date_to,
                tb.status,
                tb.created_at, tb.updated_at, tb.finalized_at,
                COALESCE(tc.cnt, 0) AS track_count
            FROM triage_blocks tb
            JOIN clouder_styles cs ON tb.style_id = cs.id
            LEFT JOIN (
                SELECT tbk.triage_block_id, COUNT(*) AS cnt
                FROM triage_buckets tbk
                JOIN triage_bucket_tracks tbt
                  ON tbt.triage_bucket_id = tbk.id
                GROUP BY tbk.triage_block_id
            ) tc ON tc.triage_block_id = tb.id
            WHERE tb.user_id = :user_id
              AND tb.style_id = :style_id
              AND tb.deleted_at IS NULL
              {sql_filter}
            ORDER BY tb.created_at DESC, tb.id ASC
            LIMIT :limit OFFSET :offset
            """,
            params,
        )

        total_rows = self._data_api.execute(
            f"""
            SELECT COUNT(*) AS total
            FROM triage_blocks tb
            WHERE tb.user_id = :user_id
              AND tb.style_id = :style_id
              AND tb.deleted_at IS NULL
              {sql_filter}
            """,
            params,
        )
        total = int(total_rows[0]["total"]) if total_rows else 0

        items = [
            TriageBlockSummaryRow(
                id=r["id"],
                user_id=r["user_id"],
                style_id=r["style_id"],
                style_name=r["style_name"],
                name=r["name"],
                date_from=str(r["date_from"]),
                date_to=str(r["date_to"]),
                status=r["status"],
                created_at=str(r["created_at"]),
                updated_at=str(r["updated_at"]),
                finalized_at=(
                    str(r["finalized_at"])
                    if r["finalized_at"] is not None
                    else None
                ),
                track_count=int(r["track_count"]),
            )
            for r in rows
        ]
        return items, total

    def list_blocks_all(
        self,
        *,
        user_id: str,
        limit: int,
        offset: int,
        status: str | None = None,
    ) -> tuple[list[TriageBlockSummaryRow], int]:
        sql_filter = ""
        params: dict[str, Any] = {
            "user_id": user_id,
            "limit": limit,
            "offset": offset,
        }
        if status is not None:
            sql_filter = " AND tb.status = :status"
            params["status"] = status

        rows = self._data_api.execute(
            f"""
            SELECT
                tb.id, tb.user_id, tb.style_id,
                cs.name AS style_name,
                tb.name,
                tb.date_from, tb.date_to,
                tb.status,
                tb.created_at, tb.updated_at, tb.finalized_at,
                COALESCE(tc.cnt, 0) AS track_count
            FROM triage_blocks tb
            JOIN clouder_styles cs ON tb.style_id = cs.id
            LEFT JOIN (
                SELECT tbk.triage_block_id, COUNT(*) AS cnt
                FROM triage_buckets tbk
                JOIN triage_bucket_tracks tbt
                  ON tbt.triage_bucket_id = tbk.id
                GROUP BY tbk.triage_block_id
            ) tc ON tc.triage_block_id = tb.id
            WHERE tb.user_id = :user_id
              AND tb.deleted_at IS NULL
              {sql_filter}
            ORDER BY tb.created_at DESC, tb.id ASC
            LIMIT :limit OFFSET :offset
            """,
            params,
        )
        total_rows = self._data_api.execute(
            f"""
            SELECT COUNT(*) AS total
            FROM triage_blocks tb
            WHERE tb.user_id = :user_id
              AND tb.deleted_at IS NULL
              {sql_filter}
            """,
            params,
        )
        total = int(total_rows[0]["total"]) if total_rows else 0
        items = [
            TriageBlockSummaryRow(
                id=r["id"],
                user_id=r["user_id"],
                style_id=r["style_id"],
                style_name=r["style_name"],
                name=r["name"],
                date_from=str(r["date_from"]),
                date_to=str(r["date_to"]),
                status=r["status"],
                created_at=str(r["created_at"]),
                updated_at=str(r["updated_at"]),
                finalized_at=(
                    str(r["finalized_at"])
                    if r["finalized_at"] is not None
                    else None
                ),
                track_count=int(r["track_count"]),
            )
            for r in rows
        ]
        return items, total

    def list_bucket_tracks(
        self,
        *,
        user_id: str,
        block_id: str,
        bucket_id: str,
        limit: int,
        offset: int,
        search: str | None = None,
    ) -> tuple[list[BucketTrackRowOut], int]:
        raise NotImplementedError

    # --- internal helpers --------------------------------------------

    def _fetch_block_detail(
        self,
        *,
        user_id: str,
        block_id: str,
        transaction_id: str | None,
    ) -> TriageBlockRow | None:
        block_rows = self._data_api.execute(
            """
            SELECT
                tb.id, tb.user_id, tb.style_id,
                cs.name AS style_name,
                tb.name,
                tb.date_from, tb.date_to,
                tb.status,
                tb.created_at, tb.updated_at, tb.finalized_at
            FROM triage_blocks tb
            JOIN clouder_styles cs ON tb.style_id = cs.id
            WHERE tb.id = :block_id
              AND tb.user_id = :user_id
              AND tb.deleted_at IS NULL
            """,
            {"block_id": block_id, "user_id": user_id},
            transaction_id=transaction_id,
        )
        if not block_rows:
            return None
        b = block_rows[0]

        bucket_rows = self._data_api.execute(
            """
            SELECT
                tbk.id, tbk.bucket_type, tbk.category_id,
                c.name AS category_name,
                tbk.inactive,
                COALESCE(tc.cnt, 0) AS track_count
            FROM triage_buckets tbk
            LEFT JOIN categories c ON tbk.category_id = c.id
            LEFT JOIN (
                SELECT triage_bucket_id, COUNT(*) AS cnt
                FROM triage_bucket_tracks
                GROUP BY triage_bucket_id
            ) tc ON tc.triage_bucket_id = tbk.id
            WHERE tbk.triage_block_id = :block_id
            """,
            {"block_id": block_id},
            transaction_id=transaction_id,
        )

        # Sort: technical buckets in TECHNICAL_BUCKET_DISPLAY_ORDER,
        # then staging buckets ordered by category name (or id fallback).
        sort_index = {
            t: i for i, t in enumerate(TECHNICAL_BUCKET_DISPLAY_ORDER)
        }

        def sort_key(row: Mapping[str, Any]) -> tuple[int, str]:
            bt = row["bucket_type"]
            if bt == BUCKET_TYPE_STAGING:
                return (
                    len(TECHNICAL_BUCKET_DISPLAY_ORDER),
                    row.get("category_name") or row["id"],
                )
            return (sort_index.get(bt, 999), row["id"])

        bucket_rows_sorted = sorted(bucket_rows, key=sort_key)
        buckets = tuple(
            TriageBucketRow(
                id=r["id"],
                bucket_type=r["bucket_type"],
                category_id=r.get("category_id"),
                category_name=r.get("category_name"),
                inactive=bool(r["inactive"]),
                track_count=int(r["track_count"]),
            )
            for r in bucket_rows_sorted
        )

        return TriageBlockRow(
            id=b["id"],
            user_id=b["user_id"],
            style_id=b["style_id"],
            style_name=b["style_name"],
            name=b["name"],
            date_from=str(b["date_from"]),
            date_to=str(b["date_to"]),
            status=b["status"],
            created_at=str(b["created_at"]),
            updated_at=str(b["updated_at"]),
            finalized_at=(
                str(b["finalized_at"]) if b["finalized_at"] is not None else None
            ),
            buckets=buckets,
        )

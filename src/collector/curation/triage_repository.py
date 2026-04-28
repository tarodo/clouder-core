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
        guard = self._data_api.execute(
            """
            SELECT
                tb.status AS block_status,
                bf.id AS from_id, bf.inactive AS from_inactive,
                bt.id AS to_id, bt.inactive AS to_inactive
            FROM triage_blocks tb
            JOIN triage_buckets bf ON bf.triage_block_id = tb.id
            JOIN triage_buckets bt ON bt.triage_block_id = tb.id
            WHERE tb.id = :block_id
              AND tb.user_id = :user_id
              AND tb.deleted_at IS NULL
              AND bf.id = :from_id
              AND bt.id = :to_id
            """,
            {
                "block_id": block_id,
                "user_id": user_id,
                "from_id": from_bucket_id,
                "to_id": to_bucket_id,
            },
        )
        if not guard:
            raise NotFoundError(
                "bucket_not_in_block", "block or bucket not found"
            )
        row = guard[0]
        if row["block_status"] != "IN_PROGRESS":
            raise InvalidStateError(
                "triage block is not editable (status != IN_PROGRESS)"
            )
        if bool(row["to_inactive"]):
            raise InactiveBucketError(
                "target bucket is inactive (its category was soft-deleted)"
            )

        if from_bucket_id == to_bucket_id:
            return MoveResult(moved=0)

        present = self._data_api.execute(
            """
            SELECT track_id
            FROM triage_bucket_tracks
            WHERE triage_bucket_id = :from_id
              AND track_id = ANY(:track_ids)
            """,
            {
                "from_id": from_bucket_id,
                "track_ids": list(track_ids),
            },
        )
        present_ids = {r["track_id"] for r in present}
        missing = [t for t in track_ids if t not in present_ids]
        if missing:
            raise TracksNotInSourceError(
                f"{len(missing)} track(s) not present in source bucket",
                missing,
            )

        with self._data_api.transaction() as tx_id:
            self._data_api.execute(
                """
                DELETE FROM triage_bucket_tracks
                WHERE triage_bucket_id = :from_id
                  AND track_id = ANY(:track_ids)
                """,
                {
                    "from_id": from_bucket_id,
                    "track_ids": list(track_ids),
                },
                transaction_id=tx_id,
            )
            self._data_api.execute(
                """
                INSERT INTO triage_bucket_tracks
                    (triage_bucket_id, track_id, added_at)
                SELECT :to_id, t, :now
                FROM UNNEST(:track_ids::text[]) AS t
                ON CONFLICT (triage_bucket_id, track_id) DO NOTHING
                """,
                {
                    "to_id": to_bucket_id,
                    "track_ids": list(track_ids),
                    "now": utc_now(),
                },
                transaction_id=tx_id,
            )

        return MoveResult(moved=len(track_ids))

    def transfer_tracks(
        self,
        *,
        user_id: str,
        src_block_id: str,
        target_bucket_id: str,
        track_ids: Sequence[str],
    ) -> TransferResult:
        src_rows = self._data_api.execute(
            """
            SELECT id, style_id, status
            FROM triage_blocks
            WHERE id = :id
              AND user_id = :user_id
              AND deleted_at IS NULL
            """,
            {"id": src_block_id, "user_id": user_id},
        )
        if not src_rows:
            raise NotFoundError(
                "triage_block_not_found",
                f"source triage block not found: {src_block_id}",
            )
        src = src_rows[0]

        tgt_rows = self._data_api.execute(
            """
            SELECT
                tbk.id AS bucket_id,
                tbk.inactive AS bucket_inactive,
                tb.id AS block_id,
                tb.user_id AS block_user_id,
                tb.style_id AS block_style_id,
                tb.status AS block_status
            FROM triage_buckets tbk
            JOIN triage_blocks tb ON tbk.triage_block_id = tb.id
            WHERE tbk.id = :bucket_id
              AND tb.deleted_at IS NULL
            """,
            {"bucket_id": target_bucket_id},
        )
        if not tgt_rows or tgt_rows[0]["block_user_id"] != user_id:
            raise NotFoundError(
                "target_bucket_not_found",
                f"target bucket not found: {target_bucket_id}",
            )
        tgt = tgt_rows[0]

        if tgt["block_status"] != "IN_PROGRESS":
            raise InvalidStateError(
                "target triage block is not IN_PROGRESS"
            )
        if bool(tgt["bucket_inactive"]):
            raise InactiveBucketError(
                "target bucket is inactive (its category was soft-deleted)"
            )
        if src["style_id"] != tgt["block_style_id"]:
            raise StyleMismatchError(
                "source and target triage blocks belong to different styles"
            )

        present = self._data_api.execute(
            """
            SELECT DISTINCT tbt.track_id
            FROM triage_bucket_tracks tbt
            JOIN triage_buckets tbk ON tbk.id = tbt.triage_bucket_id
            WHERE tbk.triage_block_id = :src_block_id
              AND tbt.track_id = ANY(:track_ids)
            """,
            {
                "src_block_id": src_block_id,
                "track_ids": list(track_ids),
            },
        )
        present_ids = {r["track_id"] for r in present}
        missing = [t for t in track_ids if t not in present_ids]
        if missing:
            raise TracksNotInSourceError(
                f"{len(missing)} track(s) not present in source block",
                missing,
            )

        inserted_rows = self._data_api.execute(
            """
            INSERT INTO triage_bucket_tracks
                (triage_bucket_id, track_id, added_at)
            SELECT :tgt_id, t, :now
            FROM UNNEST(:track_ids::text[]) AS t
            ON CONFLICT (triage_bucket_id, track_id) DO NOTHING
            RETURNING track_id
            """,
            {
                "tgt_id": target_bucket_id,
                "track_ids": list(track_ids),
                "now": utc_now(),
            },
        )
        return TransferResult(transferred=len(inserted_rows))

    _FINALIZE_CHUNK_SIZE = 500

    def finalize_block(
        self,
        *,
        user_id: str,
        block_id: str,
        categories_repository: Any,
    ) -> FinalizeResult:
        now = utc_now()

        with self._data_api.transaction() as tx_id:
            # 1. Validate block status.
            block_rows = self._data_api.execute(
                """
                SELECT id, status FROM triage_blocks
                WHERE id = :id
                  AND user_id = :user_id
                  AND deleted_at IS NULL
                """,
                {"id": block_id, "user_id": user_id},
                transaction_id=tx_id,
            )
            if not block_rows:
                raise NotFoundError(
                    "triage_block_not_found",
                    f"triage block not found: {block_id}",
                )
            if block_rows[0]["status"] != "IN_PROGRESS":
                raise InvalidStateError(
                    "triage block is not editable (status != IN_PROGRESS)"
                )

            # 2. Reject if any inactive staging bucket has tracks.
            inactive_with_tracks = self._data_api.execute(
                """
                SELECT
                    tbk.id, tbk.category_id,
                    COUNT(tbt.track_id) AS track_count
                FROM triage_buckets tbk
                LEFT JOIN triage_bucket_tracks tbt
                  ON tbt.triage_bucket_id = tbk.id
                WHERE tbk.triage_block_id = :block_id
                  AND tbk.bucket_type = 'STAGING'
                  AND tbk.inactive = TRUE
                GROUP BY tbk.id, tbk.category_id
                HAVING COUNT(tbt.track_id) > 0
                """,
                {"block_id": block_id},
                transaction_id=tx_id,
            )
            if inactive_with_tracks:
                payload = [
                    {
                        "id": r["id"],
                        "category_id": r["category_id"],
                        "track_count": int(r["track_count"]),
                    }
                    for r in inactive_with_tracks
                ]
                raise InactiveStagingFinalizeError(
                    f"{len(payload)} inactive staging bucket(s) hold tracks",
                    payload,
                )

            # 3. Iterate active staging buckets; for each, fetch tracks
            #    and call add_tracks_bulk in chunks of 500.
            staging_rows = self._data_api.execute(
                """
                SELECT id, category_id
                FROM triage_buckets
                WHERE triage_block_id = :block_id
                  AND bucket_type = 'STAGING'
                  AND inactive = FALSE
                """,
                {"block_id": block_id},
                transaction_id=tx_id,
            )

            promoted: dict[str, int] = {}
            for sb in staging_rows:
                bucket_id = sb["id"]
                category_id = sb["category_id"]
                track_rows = self._data_api.execute(
                    """
                    SELECT track_id
                    FROM triage_bucket_tracks
                    WHERE triage_bucket_id = :bucket_id
                    ORDER BY added_at ASC, track_id ASC
                    """,
                    {"bucket_id": bucket_id},
                    transaction_id=tx_id,
                )
                track_ids = [r["track_id"] for r in track_rows]
                promoted[category_id] = len(track_ids)
                for start in range(
                    0, len(track_ids), self._FINALIZE_CHUNK_SIZE
                ):
                    chunk = track_ids[
                        start : start + self._FINALIZE_CHUNK_SIZE
                    ]
                    items = [(t, block_id) for t in chunk]
                    categories_repository.add_tracks_bulk(
                        user_id=user_id,
                        category_id=category_id,
                        items=items,
                        now=now,
                        transaction_id=tx_id,
                    )

            # 4. Flip status to FINALIZED.
            self._data_api.execute(
                """
                UPDATE triage_blocks
                SET status = 'FINALIZED',
                    finalized_at = :now,
                    updated_at = :now
                WHERE id = :id
                """,
                {"id": block_id, "now": now},
                transaction_id=tx_id,
            )

            # 5. Re-fetch detail inside the same TX.
            block = self._fetch_block_detail(
                user_id=user_id, block_id=block_id, transaction_id=tx_id
            )

        if block is None:  # pragma: no cover
            raise RuntimeError(
                "finalize_block: post-update fetch returned None"
            )
        return FinalizeResult(block=block, promoted=promoted)

    def soft_delete_block(
        self, *, user_id: str, block_id: str
    ) -> bool:
        rows = self._data_api.execute(
            """
            UPDATE triage_blocks
            SET deleted_at = :now,
                updated_at = :now
            WHERE id = :id
              AND user_id = :user_id
              AND deleted_at IS NULL
            RETURNING id
            """,
            {
                "id": block_id,
                "user_id": user_id,
                "now": utc_now(),
            },
        )
        return bool(rows)

    def snapshot_category_into_active_blocks(
        self,
        *,
        user_id: str,
        style_id: str,
        category_id: str,
        transaction_id: str | None = None,
    ) -> int:
        block_rows = self._data_api.execute(
            """
            SELECT id FROM triage_blocks
            WHERE user_id = :user_id
              AND style_id = :style_id
              AND status = 'IN_PROGRESS'
              AND deleted_at IS NULL
            """,
            {"user_id": user_id, "style_id": style_id},
            transaction_id=transaction_id,
        )

        inserted = 0
        now = utc_now()
        for br in block_rows:
            bid = str(uuid4())
            res = self._data_api.execute(
                """
                INSERT INTO triage_buckets (
                    id, triage_block_id, bucket_type, category_id,
                    inactive, created_at
                ) VALUES (
                    :id, :block_id, 'STAGING', :category_id,
                    FALSE, :now
                )
                ON CONFLICT (triage_block_id, category_id)
                  WHERE category_id IS NOT NULL
                  DO NOTHING
                RETURNING id
                """,
                {
                    "id": bid,
                    "block_id": br["id"],
                    "category_id": category_id,
                    "now": now,
                },
                transaction_id=transaction_id,
            )
            if res:
                inserted += 1
        return inserted

    def mark_staging_inactive_for_category(
        self,
        *,
        user_id: str,
        category_id: str,
        transaction_id: str | None = None,
    ) -> int:
        rows = self._data_api.execute(
            """
            UPDATE triage_buckets tbk
            SET inactive = TRUE
            FROM triage_blocks tb
            WHERE tbk.triage_block_id = tb.id
              AND tb.user_id = :user_id
              AND tbk.category_id = :category_id
              AND tbk.bucket_type = 'STAGING'
              AND tbk.inactive = FALSE
            RETURNING tbk.id
            """,
            {"user_id": user_id, "category_id": category_id},
            transaction_id=transaction_id,
        )
        return len(rows)

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
        guard = self._data_api.execute(
            """
            SELECT tb.id AS block_id, tbk.id AS bucket_id
            FROM triage_blocks tb
            JOIN triage_buckets tbk ON tbk.triage_block_id = tb.id
            WHERE tb.id = :block_id
              AND tb.user_id = :user_id
              AND tb.deleted_at IS NULL
              AND tbk.id = :bucket_id
            """,
            {
                "block_id": block_id,
                "user_id": user_id,
                "bucket_id": bucket_id,
            },
        )
        if not guard:
            raise NotFoundError(
                "bucket_not_in_block",
                f"bucket {bucket_id} not found in triage block {block_id}",
            )

        params: dict[str, Any] = {
            "bucket_id": bucket_id,
            "limit": limit,
            "offset": offset,
        }
        search_clause = ""
        if search and search.strip():
            term = "%" + search.strip().lower() + "%"
            params["search"] = term
            search_clause = " AND t.normalized_title ILIKE :search"

        rows = self._data_api.execute(
            f"""
            SELECT
                t.id AS track_id,
                t.title, t.mix_name, t.isrc, t.bpm, t.length_ms,
                t.publish_date, t.spotify_release_date,
                t.spotify_id, t.release_type, t.is_ai_suspected,
                tbt.added_at,
                COALESCE(
                    ARRAY_AGG(ca.name ORDER BY cta.role, ca.name)
                        FILTER (WHERE ca.id IS NOT NULL),
                    ARRAY[]::text[]
                ) AS artist_names
            FROM triage_bucket_tracks tbt
            JOIN clouder_tracks t ON t.id = tbt.track_id
            LEFT JOIN clouder_track_artists cta ON cta.track_id = t.id
            LEFT JOIN clouder_artists ca ON ca.id = cta.artist_id
            WHERE tbt.triage_bucket_id = :bucket_id
              {search_clause}
            GROUP BY
                t.id, t.title, t.mix_name, t.isrc, t.bpm, t.length_ms,
                t.publish_date, t.spotify_release_date,
                t.spotify_id, t.release_type, t.is_ai_suspected,
                tbt.added_at
            ORDER BY tbt.added_at DESC, t.id ASC
            LIMIT :limit OFFSET :offset
            """,
            params,
        )
        total_rows = self._data_api.execute(
            f"""
            SELECT COUNT(*) AS total
            FROM triage_bucket_tracks tbt
            JOIN clouder_tracks t ON t.id = tbt.track_id
            WHERE tbt.triage_bucket_id = :bucket_id
              {search_clause}
            """,
            params,
        )
        total = int(total_rows[0]["total"]) if total_rows else 0

        items = [
            BucketTrackRowOut(
                track_id=r["track_id"],
                title=r["title"],
                mix_name=r.get("mix_name"),
                isrc=r.get("isrc"),
                bpm=int(r["bpm"]) if r.get("bpm") is not None else None,
                length_ms=(
                    int(r["length_ms"])
                    if r.get("length_ms") is not None
                    else None
                ),
                publish_date=(
                    str(r["publish_date"])
                    if r.get("publish_date") is not None
                    else None
                ),
                spotify_release_date=(
                    str(r["spotify_release_date"])
                    if r.get("spotify_release_date") is not None
                    else None
                ),
                spotify_id=r.get("spotify_id"),
                release_type=r.get("release_type"),
                is_ai_suspected=bool(r.get("is_ai_suspected", False)),
                artists=tuple(r.get("artist_names") or ()),
                added_at=str(r["added_at"]),
            )
            for r in rows
        ]
        return items, total

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


def create_default_triage_repository() -> "TriageRepository | None":
    from collector.settings import get_data_api_settings

    settings = get_data_api_settings()
    if not settings.is_configured:
        return None
    from collector.data_api import create_default_data_api_client

    data_api = create_default_data_api_client(
        resource_arn=str(settings.aurora_cluster_arn),
        secret_arn=str(settings.aurora_secret_arn),
        database=settings.aurora_database,
    )
    return TriageRepository(data_api=data_api)

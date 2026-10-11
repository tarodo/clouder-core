"""What the collector API reads (lists, coverage, funnel, users) and the admin style toggle."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from ._base import RepositoryBase


class ApiViewsMixin(RepositoryBase):
    def list_tracks(
        self, limit: int, offset: int, search: str | None = None
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"limit": limit, "offset": offset}
        where = ""
        if search:
            where = "WHERE t.normalized_title LIKE :search"
            params["search"] = f"%{search.lower()}%"
        return self._data_api.execute(
            f"""
            SELECT t.id, t.title, t.mix_name, t.isrc, t.bpm, t.length_ms,
                   t.publish_date, t.album_id, t.style_id, t.created_at, t.updated_at,
                   a.title AS album_title,
                   l.name AS label_name,
                   s.name AS style_name,
                   string_agg(DISTINCT art.name, ', ' ORDER BY art.name) AS artist_names
            FROM clouder_tracks t
            LEFT JOIN clouder_albums a ON t.album_id = a.id
            LEFT JOIN clouder_labels l ON a.label_id = l.id
            LEFT JOIN clouder_styles s ON t.style_id = s.id
            LEFT JOIN clouder_track_artists ta ON ta.track_id = t.id
            LEFT JOIN clouder_artists art ON ta.artist_id = art.id
            {where}
            GROUP BY t.id, a.title, l.name, s.name
            ORDER BY t.created_at DESC
            LIMIT :limit OFFSET :offset
            """,
            params,
        )

    def count_tracks(self, search: str | None = None) -> int:
        params: dict[str, Any] = {}
        where = ""
        if search:
            where = "WHERE normalized_title LIKE :search"
            params["search"] = f"%{search.lower()}%"
        rows = self._data_api.execute(f"SELECT count(*) AS cnt FROM clouder_tracks {where}", params)
        return int(rows[0]["cnt"]) if rows else 0

    def list_artists(
        self, limit: int, offset: int, search: str | None = None
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"limit": limit, "offset": offset}
        where = ""
        if search:
            where = "WHERE normalized_name LIKE :search"
            params["search"] = f"%{search.lower()}%"
        return self._data_api.execute(
            f"""
            SELECT id, name, normalized_name, created_at, updated_at
            FROM clouder_artists
            {where}
            ORDER BY created_at DESC
            LIMIT :limit OFFSET :offset
            """,
            params,
        )

    def count_artists(self, search: str | None = None) -> int:
        params: dict[str, Any] = {}
        where = ""
        if search:
            where = "WHERE normalized_name LIKE :search"
            params["search"] = f"%{search.lower()}%"
        rows = self._data_api.execute(
            f"SELECT count(*) AS cnt FROM clouder_artists {where}", params
        )
        return int(rows[0]["cnt"]) if rows else 0

    def list_albums(
        self, limit: int, offset: int, search: str | None = None
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"limit": limit, "offset": offset}
        where = ""
        if search:
            where = "WHERE a.normalized_title LIKE :search"
            params["search"] = f"%{search.lower()}%"
        return self._data_api.execute(
            f"""
            SELECT a.id, a.title, a.normalized_title, a.release_date,
                   a.label_id, a.created_at, a.updated_at,
                   l.name AS label_name
            FROM clouder_albums a
            LEFT JOIN clouder_labels l ON a.label_id = l.id
            {where}
            ORDER BY a.created_at DESC
            LIMIT :limit OFFSET :offset
            """,
            params,
        )

    def count_albums(self, search: str | None = None) -> int:
        params: dict[str, Any] = {}
        where = ""
        if search:
            where = "WHERE normalized_title LIKE :search"
            params["search"] = f"%{search.lower()}%"
        rows = self._data_api.execute(f"SELECT count(*) AS cnt FROM clouder_albums {where}", params)
        return int(rows[0]["cnt"]) if rows else 0

    def coverage_for_year(self, week_year: int) -> list[dict[str, Any]]:
        return self._data_api.execute(
            """
            SELECT
                cs.id            AS clouder_style_id,
                cs.name          AS style_name,
                cs.is_hidden,
                im.external_id   AS beatport_style_id,
                r.run_id,
                r.week_number,
                r.status,
                r.item_count,
                r.is_custom_range,
                r.period_start,
                r.period_end,
                r.started_at,
                r.finished_at
            FROM clouder_styles cs
            INNER JOIN identity_map im
              ON im.source = 'beatport'
              AND im.entity_type = 'style'
              AND im.clouder_entity_type = 'style'
              AND im.clouder_id = cs.id
            LEFT JOIN LATERAL (
                SELECT
                    ir.run_id, ir.week_year, ir.week_number, ir.style_id,
                    ir.status, ir.item_count, ir.is_custom_range,
                    ir.period_start, ir.period_end,
                    ir.started_at, ir.finished_at
                FROM ingest_runs ir
                WHERE ir.week_year = :week_year
                  AND ir.style_id::text = im.external_id
                ORDER BY ir.week_number, ir.started_at DESC
            ) r ON TRUE
            -- r.run_id IS NULL when this style has no runs for the year (LEFT JOIN);
            -- include those rows so the matrix shows empty cells for that style.
            WHERE r.run_id IS NULL OR NOT EXISTS (
                SELECT 1
                FROM ingest_runs ir2
                WHERE ir2.week_year = r.week_year
                  AND ir2.style_id = r.style_id
                  AND ir2.week_number = r.week_number
                  AND ir2.started_at > r.started_at
            )
            ORDER BY cs.name ASC, r.week_number ASC NULLS LAST
            """,
            {"week_year": week_year},
        )

    def set_style_hidden(self, style_id: str, is_hidden: bool, now: datetime) -> bool:
        """Hide/show a style in the catalog and the coverage matrix. Returns
        False when the style does not exist."""
        rows = self._data_api.execute(
            """
            UPDATE clouder_styles
            SET is_hidden = :is_hidden,
                updated_at = :now
            WHERE id = :style_id
            RETURNING id
            """,
            {"style_id": style_id, "is_hidden": is_hidden, "now": now},
        )
        return bool(rows)

    def analytics_funnel(
        self,
        user_id: str,
        *,
        day_start: datetime,
        week_start: datetime,
        month_start: datetime,
    ) -> list[dict[str, Any]]:
        """Distinct tracks per curation stage, dated by when the work happened.

        Block creation stamps initial bucket rows with the block's created_at,
        and every move re-inserts with now, so added_at > created_at means the
        user moved it. triaged = moved anywhere but NEW (back to NEW = undo);
        categorized = moved to an active STAGING bucket (open or finalized
        block) + category adds outside triage (finalize's copies would re-date
        staged tracks); playlisted = added to a playlist.
        """
        return self._data_api.execute(
            """
            WITH moved AS (
                SELECT tb.bucket_type, tb.inactive, tbt.track_id, tbt.added_at AS at
                FROM triage_blocks b
                JOIN triage_buckets tb ON tb.triage_block_id = b.id
                JOIN triage_bucket_tracks tbt ON tbt.triage_bucket_id = tb.id
                WHERE b.user_id = :user_id AND b.deleted_at IS NULL
                  AND tbt.added_at > b.created_at
                  AND tbt.added_at >= :month_start
            ), s AS (
                SELECT 'triaged' AS stage, track_id, at
                FROM moved WHERE bucket_type <> 'NEW'
                UNION ALL
                SELECT 'categorized', track_id, at
                FROM moved WHERE bucket_type = 'STAGING' AND NOT inactive
                UNION ALL
                SELECT 'categorized', ct.track_id, ct.added_at
                FROM categories c
                JOIN category_tracks ct ON ct.category_id = c.id
                WHERE c.user_id = :user_id AND c.deleted_at IS NULL
                  AND ct.source_triage_block_id IS NULL
                  AND ct.added_at >= :month_start
                UNION ALL
                SELECT 'playlisted', pt.track_id, pt.added_at
                FROM playlists p
                JOIN playlist_tracks pt ON pt.playlist_id = p.id
                WHERE p.user_id = :user_id AND p.deleted_at IS NULL
                  AND pt.added_at >= :month_start
            )
            SELECT stage,
                   count(DISTINCT track_id) FILTER (WHERE at >= :day_start) AS day,
                   count(DISTINCT track_id) FILTER (WHERE at >= :week_start) AS week,
                   count(DISTINCT track_id) AS month
            FROM s
            GROUP BY stage
            """,
            {
                "user_id": user_id,
                "day_start": day_start,
                "week_start": week_start,
                "month_start": month_start,
            },
        )

    def list_users(self) -> list[dict[str, Any]]:
        return self._data_api.execute(
            """
            SELECT id, display_name
            FROM users
            ORDER BY display_name NULLS LAST, id
            """,
            {},
        )

"""Spotify search state: claims, results, not-found tracks, vendor bans."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

from ..saturday_week import first_saturday, weeks_in_year
from ._base import RepositoryBase, as_utc_datetime
from .commands import UpdateSpotifyResultCmd


class SpotifySearchMixin(RepositoryBase):
    def claim_tracks_for_spotify_search(
        self, limit: int, claimed_at: datetime
    ) -> list[dict[str, Any]]:
        """Stamp `spotify_searched_at` on the next *limit* candidates and return
        them, in one statement.

        Claiming inside the selecting statement is what keeps two concurrent
        workers off the same rows. The read-only query below left
        `spotify_searched_at` NULL until the whole batch had finished, so a
        worker starting mid-batch re-selected everything the first one was
        still searching — two ingests in a row meant every track was looked up
        on Spotify twice.

        `SKIP LOCKED` lets a parallel claim take a disjoint set instead of
        blocking on ours, and repeating the `IS NULL` predicate on the outer
        UPDATE closes the READ COMMITTED window between the sub-select picking
        ids and the lock actually being taken.

        A batch that dies after claiming would strand its rows as
        "searched, not found"; `release_spotify_search_claim` hands them back.
        """
        return self._data_api.execute(
            """
            WITH claimed AS (
                UPDATE clouder_tracks
                SET spotify_searched_at = :claimed_at,
                    updated_at = :claimed_at
                WHERE id IN (
                    SELECT id
                    FROM clouder_tracks
                    WHERE isrc IS NOT NULL
                      AND spotify_searched_at IS NULL
                    ORDER BY created_at DESC
                    LIMIT :limit
                    FOR UPDATE SKIP LOCKED
                )
                  AND spotify_searched_at IS NULL
                RETURNING id, isrc, title, normalized_title, length_ms, created_at
            )
            SELECT c.id, c.isrc, c.title, c.normalized_title, c.length_ms,
                   string_agg(DISTINCT a.name, ', ') AS artists
            FROM claimed c
            LEFT JOIN clouder_track_artists ta ON ta.track_id = c.id
            LEFT JOIN clouder_artists a ON ta.artist_id = a.id
            GROUP BY c.id, c.isrc, c.title, c.normalized_title,
                     c.length_ms, c.created_at
            ORDER BY c.created_at DESC
            """,
            {"limit": limit, "claimed_at": claimed_at},
        )

    def get_vendor_blocked_until(self, vendor: str) -> datetime | None:
        rows = self._data_api.execute(
            "SELECT blocked_until FROM vendor_rate_limits WHERE vendor = :vendor",
            {"vendor": vendor},
        )
        return as_utc_datetime(rows[0]["blocked_until"]) if rows else None

    def set_vendor_blocked_until(self, vendor: str, until: datetime, now: datetime) -> None:
        """Record a ban; a shorter one never cuts an existing ban short."""
        self._data_api.execute(
            """
            INSERT INTO vendor_rate_limits (vendor, blocked_until, updated_at)
            VALUES (:vendor, :until, :now)
            ON CONFLICT (vendor) DO UPDATE SET
                blocked_until = GREATEST(vendor_rate_limits.blocked_until, EXCLUDED.blocked_until),
                updated_at = EXCLUDED.updated_at
            """,
            {"vendor": vendor, "until": until, "now": now},
        )

    def release_spotify_search_claim(
        self, claimed_at: datetime, now: datetime
    ) -> int:
        """Hand back rows claimed at *claimed_at* that never got a result.

        Rows the batch did manage to persist carry the completion timestamp
        written by `batch_update_spotify_results`, not the claim timestamp, so
        they are left alone; only the stranded remainder is released for the
        SQS redelivery to pick up.
        """
        rows = self._data_api.execute(
            """
            UPDATE clouder_tracks
            SET spotify_searched_at = NULL,
                updated_at = :now
            WHERE spotify_searched_at = :claimed_at
              AND spotify_id IS NULL
            RETURNING id
            """,
            {"claimed_at": claimed_at, "now": now},
        )
        return len(rows)

    def find_tracks_needing_spotify_search(self, limit: int) -> list[dict[str, Any]]:
        """Read-only peek used to decide whether a follow-up batch is needed.

        Must stay non-claiming: `_enqueue_follow_up_if_needed` calls it with
        limit=1 purely to ask "is anything left?", and a claiming peek would
        strand that track.
        """
        return self._data_api.execute(
            """
            SELECT t.id, t.isrc, t.title, t.normalized_title, t.length_ms,
                   string_agg(DISTINCT a.name, ', ') AS artists
            FROM clouder_tracks t
            LEFT JOIN clouder_track_artists ta ON ta.track_id = t.id
            LEFT JOIN clouder_artists a ON ta.artist_id = a.id
            WHERE t.isrc IS NOT NULL
              AND t.spotify_searched_at IS NULL
            GROUP BY t.id, t.isrc, t.title, t.normalized_title,
                     t.length_ms, t.created_at
            ORDER BY t.created_at DESC
            LIMIT :limit
            """,
            {"limit": limit},
        )

    def find_tracks_not_found_on_spotify(
        self,
        limit: int,
        offset: int,
        search: str | None = None,
        publish_date_from: date | None = None,
        publish_date_to: date | None = None,
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"limit": limit, "offset": offset}
        where_extra = ""
        if search:
            where_extra += "AND t.normalized_title LIKE :search\n"
            params["search"] = f"%{search.lower()}%"
        if publish_date_from is not None:
            where_extra += "AND t.publish_date >= :date_from\n"
            params["date_from"] = publish_date_from
        if publish_date_to is not None:
            where_extra += "AND t.publish_date <= :date_to\n"
            params["date_to"] = publish_date_to
        return self._data_api.execute(
            f"""
            SELECT t.id, t.title, t.isrc, t.bpm, t.publish_date,
                   string_agg(DISTINCT a.name, ', ' ORDER BY a.name) AS artist_names
            FROM clouder_tracks t
            LEFT JOIN clouder_track_artists ta ON ta.track_id = t.id
            LEFT JOIN clouder_artists a ON ta.artist_id = a.id
            WHERE t.isrc IS NOT NULL
              AND t.spotify_searched_at IS NOT NULL
              AND t.spotify_id IS NULL
              {where_extra}
            GROUP BY t.id
            ORDER BY t.publish_date DESC NULLS LAST
            LIMIT :limit OFFSET :offset
            """,
            params,
        )

    def count_tracks_not_found_on_spotify(
        self,
        search: str | None = None,
        publish_date_from: date | None = None,
        publish_date_to: date | None = None,
    ) -> int:
        params: dict[str, Any] = {}
        where_extra = ""
        if search:
            where_extra += "AND normalized_title LIKE :search\n"
            params["search"] = f"%{search.lower()}%"
        if publish_date_from is not None:
            where_extra += "AND publish_date >= :date_from\n"
            params["date_from"] = publish_date_from
        if publish_date_to is not None:
            where_extra += "AND publish_date <= :date_to\n"
            params["date_to"] = publish_date_to
        rows = self._data_api.execute(
            f"""
            SELECT count(*) AS cnt
            FROM clouder_tracks
            WHERE isrc IS NOT NULL
              AND spotify_searched_at IS NOT NULL
              AND spotify_id IS NULL
              {where_extra}
            """,
            params,
        )
        return int(rows[0]["cnt"]) if rows else 0

    def reset_spotify_not_found(
        self,
        publish_date_from: date,
        publish_date_to: date,
        now: datetime,
    ) -> int:
        """Clear spotify_searched_at for not-found tracks in the publish-date
        range so the existing search worker picks them up again. Returns the
        number of tracks reset (via RETURNING — the Data API wrapper exposes
        rows, not numberOfRecordsUpdated)."""
        rows = self._data_api.execute(
            """
            UPDATE clouder_tracks
            SET spotify_searched_at = NULL,
                updated_at = :now
            WHERE isrc IS NOT NULL
              AND spotify_id IS NULL
              AND spotify_searched_at IS NOT NULL
              AND publish_date BETWEEN :date_from AND :date_to
            RETURNING id
            """,
            {
                "now": now,
                "date_from": publish_date_from,
                "date_to": publish_date_to,
            },
        )
        return len(rows)

    def count_spotify_pending_in_range(
        self,
        publish_date_from: date,
        publish_date_to: date,
    ) -> int:
        rows = self._data_api.execute(
            """
            SELECT count(*) AS cnt
            FROM clouder_tracks
            WHERE isrc IS NOT NULL
              AND spotify_searched_at IS NULL
              AND publish_date BETWEEN :date_from AND :date_to
            """,
            {"date_from": publish_date_from, "date_to": publish_date_to},
        )
        return int(rows[0]["cnt"]) if rows else 0

    def spotify_search_counts(self, since: datetime) -> dict[str, int]:
        """Tracks waiting for the Spotify search, searched without a match, and
        claimed or searched since *since* (a batch in progress counts as searched)."""
        (row,) = self._data_api.execute(
            """
            SELECT
                count(*) FILTER (WHERE spotify_searched_at IS NULL) AS waiting,
                count(*) FILTER (WHERE spotify_searched_at IS NOT NULL AND spotify_id IS NULL)
                    AS not_found,
                count(*) FILTER (WHERE spotify_searched_at >= :since) AS searched_recently
            FROM clouder_tracks
            WHERE isrc IS NOT NULL
            """,
            {"since": since},
        )
        return {key: int(row[key] or 0) for key in ("waiting", "not_found", "searched_recently")}

    def batch_update_spotify_results(
        self,
        commands: list[UpdateSpotifyResultCmd],
        transaction_id: str | None = None,
    ) -> None:
        if not commands:
            return
        self._data_api.batch_execute(
            """
            UPDATE clouder_tracks
            SET spotify_id = :spotify_id,
                spotify_searched_at = :searched_at,
                release_type = COALESCE(:release_type, release_type),
                spotify_release_date = COALESCE(
                    :spotify_release_date, spotify_release_date
                ),
                updated_at = :searched_at
            WHERE id = :track_id
            """,
            [
                {
                    "track_id": cmd.track_id,
                    "spotify_id": cmd.spotify_id,
                    "searched_at": cmd.searched_at,
                    "release_type": cmd.release_type,
                    "spotify_release_date": cmd.spotify_release_date,
                }
                for cmd in commands
            ],
            transaction_id=transaction_id,
        )

    def spotify_stats_for_year(self, week_year: int) -> list[dict[str, Any]]:
        """Per (beatport style, Saturday week of publish_date) Spotify-match
        counts for one Saturday-year. The four buckets are mutually exclusive
        and sum to total."""
        year_start = first_saturday(week_year)
        year_end = year_start + timedelta(days=weeks_in_year(week_year) * 7 - 1)
        return self._data_api.execute(
            """
            SELECT
                im.external_id                         AS beatport_style_id,
                (t.publish_date - :year_start) / 7 + 1 AS week_number,
                COUNT(*)                               AS total,
                COUNT(*) FILTER (WHERE t.spotify_id IS NOT NULL) AS found,
                COUNT(*) FILTER (WHERE t.spotify_id IS NULL
                                   AND t.spotify_searched_at IS NOT NULL)
                                                       AS not_found,
                COUNT(*) FILTER (WHERE t.isrc IS NOT NULL
                                   AND t.spotify_searched_at IS NULL)
                                                       AS pending,
                COUNT(*) FILTER (WHERE t.isrc IS NULL) AS no_isrc
            FROM clouder_tracks t
            JOIN clouder_styles cs ON cs.id = t.style_id
            JOIN identity_map im
              ON im.source = 'beatport'
              AND im.entity_type = 'style'
              AND im.clouder_entity_type = 'style'
              AND im.clouder_id = cs.id
            WHERE t.publish_date BETWEEN :year_start AND :year_end
            GROUP BY 1, 2
            """,
            {"year_start": year_start, "year_end": year_end},
        )

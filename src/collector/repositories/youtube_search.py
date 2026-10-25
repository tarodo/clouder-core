"""YouTube search state: which tracks to search, claims, done stamps, release."""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from typing import Any

from ..saturday_week import first_saturday, weeks_in_year
from ._base import RepositoryBase

# Owner's call: a second YouTube search later than four days would come too late.
SECOND_CHANCE_DAYS = 4


class YoutubeSearchMixin(RepositoryBase):
    def claim_tracks_for_youtube_search(
        self,
        limit: int,
        claimed_at: datetime,
    ) -> list[dict[str, Any]]:
        """Stamp the next *limit* unsearched tracks, newest release first over
        the whole catalog, with *claimed_at* and return their search inputs, in
        one statement (SKIP LOCKED in a materialized pick, repeated IS NULL on
        the update). Fresh ingests land on top by themselves. `has_ytmusic`
        marks tracks that already have a YT Music match, review or no_match
        row: only their video is still looked for."""
        return self._data_api.execute(
            """
            WITH picked AS MATERIALIZED (
                -- Materialized: run once. `IN (... LIMIT n FOR UPDATE SKIP
                -- LOCKED)` may be re-executed per row, each run locking the
                -- next row, and claim far more than n (seen once in tests).
                SELECT id FROM clouder_tracks
                WHERE youtube_searched_at IS NULL
                ORDER BY publish_date DESC NULLS LAST, created_at DESC, id
                LIMIT :limit
                FOR UPDATE SKIP LOCKED
            ),
            claimed AS (
                UPDATE clouder_tracks t
                SET youtube_searched_at = :claimed_at
                FROM picked
                WHERE t.id = picked.id
                  AND t.youtube_searched_at IS NULL
                RETURNING t.id, t.title, t.mix_name, t.length_ms, t.album_id, t.publish_date,
                          t.created_at
            )
            SELECT c.id, c.title, c.mix_name, c.length_ms, alb.title AS album_title,
                   COALESCE(:claimed_at < c.publish_date + :days * interval '1 day', FALSE)
                       AS early,
                   COALESCE(string_agg(DISTINCT a.name, ', '), '') AS artists,
                   (EXISTS (SELECT 1 FROM vendor_track_map v
                            WHERE v.clouder_track_id = c.id AND v.vendor = 'ytmusic')
                    OR EXISTS (SELECT 1 FROM match_review_queue q
                               WHERE q.clouder_track_id = c.id AND q.vendor = 'ytmusic'))
                       AS has_ytmusic
            FROM claimed c
            LEFT JOIN clouder_track_artists ta ON ta.track_id = c.id
            LEFT JOIN clouder_artists a ON a.id = ta.artist_id
            LEFT JOIN clouder_albums alb ON alb.id = c.album_id
            GROUP BY c.id, c.title, c.mix_name, c.length_ms, alb.title, c.publish_date,
                     c.created_at
            ORDER BY c.publish_date DESC NULLS LAST, c.created_at DESC, c.id
            """,
            {"limit": limit, "claimed_at": claimed_at, "days": SECOND_CHANCE_DAYS},
        )

    def mark_youtube_searched(self, track_id: str, at: datetime) -> None:
        """Done: replace the claim stamp so a release leaves this row alone."""
        self._data_api.execute(
            "UPDATE clouder_tracks SET youtube_searched_at = :at WHERE id = :id",
            {"id": track_id, "at": at},
        )

    def release_youtube_search_claim(self, claimed_at: datetime) -> int:
        """Hand back rows still carrying the claim stamp (ban, deadline, crash)."""
        rows = self._data_api.execute(
            """
            UPDATE clouder_tracks SET youtube_searched_at = NULL
            WHERE youtube_searched_at = :claimed_at
            RETURNING id
            """,
            {"claimed_at": claimed_at},
        )
        return len(rows)

    def youtube_search_counts(self, recent_since: datetime) -> dict[str, int]:
        """Backlog and outcomes behind the admin YouTube search status. Each
        catalog track lands in one bucket (a match wins over a review, a review
        over no_match), so matched + needs_review + not_found + error + waiting
        = total. A stamped track with no outcome row lost its write: an error."""
        rows = self._data_api.execute(
            """
            WITH t AS (
                SELECT t.youtube_searched_at,
                       m.clouder_track_id IS NOT NULL AS found,
                       coalesce(q.review, false) AS review,
                       coalesce(q.no_match, false) AS no_match
                FROM clouder_tracks t
                LEFT JOIN vendor_track_map m
                  ON m.clouder_track_id = t.id AND m.vendor = 'ytmusic'
                -- joins, not per-row EXISTS: hash joins over the catalog (6 s -> 1 s on prod)
                LEFT JOIN (
                    SELECT clouder_track_id,
                           bool_or(status = 'pending') AS review,
                           bool_or(status = 'no_match') AS no_match
                    FROM match_review_queue WHERE vendor = 'ytmusic'
                    GROUP BY clouder_track_id
                ) q ON q.clouder_track_id = t.id
            )
            SELECT
                count(*) AS total,
                count(*) FILTER (WHERE found) AS matched,
                count(*) FILTER (WHERE NOT found AND review) AS needs_review,
                count(*) FILTER (WHERE NOT found AND NOT review AND no_match) AS not_found,
                count(*) FILTER (WHERE NOT (found OR review OR no_match)
                                   AND youtube_searched_at IS NOT NULL) AS error,
                count(*) FILTER (WHERE NOT (found OR review OR no_match)
                                   AND youtube_searched_at IS NULL) AS waiting,
                count(*) FILTER (WHERE youtube_searched_at >= :recent_since)
                    AS searched_recently,
                (SELECT count(*) FROM vendor_track_map WHERE vendor = 'youtube') AS videos
            FROM t
            """,
            {"recent_since": recent_since},
        )
        return {k: int(v or 0) for k, v in rows[0].items()}

    def youtube_stats_for_year(self, week_year: int) -> list[dict[str, Any]]:
        """Per (beatport style, Saturday week of publish_date) YT Music outcome
        counts for one Saturday-year, as `spotify_stats_for_year` does for
        Spotify. The four buckets are mutually exclusive and sum to total."""
        year_start = first_saturday(week_year)
        year_end = year_start + timedelta(days=weeks_in_year(week_year) * 7 - 1)
        return self._data_api.execute(
            """
            WITH t AS (
                SELECT t.style_id, t.publish_date, t.youtube_searched_at,
                       EXISTS (SELECT 1 FROM vendor_track_map v
                               WHERE v.clouder_track_id = t.id AND v.vendor = 'ytmusic')
                           AS found,
                       EXISTS (SELECT 1 FROM match_review_queue q
                               WHERE q.clouder_track_id = t.id AND q.vendor = 'ytmusic'
                                 AND q.status = 'pending') AS review
                FROM clouder_tracks t
                WHERE t.publish_date BETWEEN :year_start AND :year_end
            )
            SELECT
                im.external_id                       AS beatport_style_id,
                (t.publish_date - :year_start) / 7 + 1 AS week_number,
                COUNT(*)                             AS total,
                COUNT(*) FILTER (WHERE t.found)      AS found,
                COUNT(*) FILTER (WHERE NOT t.found AND t.review) AS review,
                COUNT(*) FILTER (WHERE NOT t.found AND NOT t.review
                                   AND t.youtube_searched_at IS NOT NULL) AS not_found,
                COUNT(*) FILTER (WHERE NOT t.found AND NOT t.review
                                   AND t.youtube_searched_at IS NULL) AS pending
            FROM t
            JOIN identity_map im
              ON im.source = 'beatport'
              AND im.entity_type = 'style'
              AND im.clouder_entity_type = 'style'
              AND im.clouder_id = t.style_id
            GROUP BY 1, 2
            """,
            {"year_start": year_start, "year_end": year_end},
        )

    def youtube_review_tracks(
        self, *, beatport_style_id: str, date_from: date, date_to: date, limit: int = 200
    ) -> list[dict[str, Any]]:
        """Open YT Music reviews of one style's releases in [date_from, date_to],
        each with its candidates best first, trimmed to what the review page
        shows (no thumbnails: a page of reviews stays far under 1 MB)."""
        rows = self._data_api.execute(
            """
            SELECT t.id AS track_id, t.title, t.mix_name, t.length_ms, t.spotify_id,
                   cs.name AS style_name,
                   (SELECT string_agg(a.name, ', ' ORDER BY a.name)
                    FROM clouder_track_artists ta JOIN clouder_artists a ON a.id = ta.artist_id
                    WHERE ta.track_id = t.id) AS artists,
                   (SELECT jsonb_agg(jsonb_build_object(
                               'ref', jsonb_strip_nulls(jsonb_build_object(
                                   'videoId', e->'ref'->'videoId',
                                   'title', e->'ref'->'title',
                                   'artists', e->'ref'->'artists',
                                   'duration_seconds', e->'ref'->'duration_seconds',
                                   'album', e->'ref'->'album')),
                               'score', e->'score')
                           ORDER BY (e->>'score')::numeric DESC NULLS LAST)
                    FROM jsonb_array_elements(q.candidates) e) AS candidates
            FROM match_review_queue q
            JOIN clouder_tracks t ON t.id = q.clouder_track_id
            JOIN clouder_styles cs ON cs.id = t.style_id
            JOIN identity_map im
              ON im.source = 'beatport'
              AND im.entity_type = 'style'
              AND im.clouder_entity_type = 'style'
              AND im.clouder_id = cs.id
              AND im.external_id = :style
            WHERE q.vendor = 'ytmusic' AND q.status = 'pending'
              AND t.publish_date BETWEEN :date_from AND :date_to
              AND NOT EXISTS (SELECT 1 FROM vendor_track_map v
                              WHERE v.clouder_track_id = t.id AND v.vendor = 'ytmusic')
            ORDER BY t.publish_date DESC, t.title, t.id
            LIMIT :limit
            """,
            {
                "style": beatport_style_id,
                "date_from": date_from,
                "date_to": date_to,
                "limit": limit,
            },
        )
        for row in rows:
            if isinstance(row["candidates"], str):
                row["candidates"] = json.loads(row["candidates"])
            row["candidates"] = row["candidates"] or []
        return rows

    def close_youtube_reviews_without_spotify(self, *, now: datetime) -> int:
        """A DJ hears tracks through Spotify, so an open YT Music review of a
        track Spotify could not find is closed as not on YouTube. The
        candidates stay on the row: `reopen_youtube_for_spotify_found` undoes
        it if Spotify finds the track later."""
        rows = self._data_api.execute(
            """
            UPDATE match_review_queue q
            SET status = 'no_match', resolved_at = :now
            FROM clouder_tracks t
            WHERE t.id = q.clouder_track_id
              AND q.vendor = 'ytmusic' AND q.status = 'pending'
              AND t.spotify_id IS NULL AND t.spotify_searched_at IS NOT NULL
              AND NOT EXISTS (SELECT 1 FROM match_review_queue n
                              WHERE n.clouder_track_id = q.clouder_track_id
                                AND n.vendor = 'ytmusic' AND n.status = 'no_match')
            RETURNING q.id
            """,
            {"now": now},
        )
        return len(rows)

    def reopen_youtube_for_spotify_found(self) -> int:
        """Tracks closed as not on YouTube only because Spotify had missed them
        (a no_match row that kept its candidates) are searched on YouTube
        again once Spotify finds them: the row goes, the search stamp clears."""
        rows = self._data_api.execute(
            """
            WITH reopened AS (
                DELETE FROM match_review_queue q
                USING clouder_tracks t
                WHERE t.id = q.clouder_track_id
                  AND q.vendor = 'ytmusic' AND q.status = 'no_match'
                  AND jsonb_array_length(q.candidates) > 0
                  AND t.spotify_id IS NOT NULL
                RETURNING q.clouder_track_id
            )
            UPDATE clouder_tracks SET youtube_searched_at = NULL
            WHERE id IN (SELECT clouder_track_id FROM reopened)
            RETURNING id
            """
        )
        return len(rows)

    def reopen_youtube_second_chance(self, *, now: datetime) -> int:
        """A track searched within SECOND_CHANCE_DAYS of its release may not be
        on YouTube yet (distributors upload late, search indexes later still),
        so its open review is dropped and the track searched again
        SECOND_CHANCE_DAYS after the first search. The new search falls after
        that window, so it happens once."""
        rows = self._data_api.execute(
            """
            WITH due AS (
                DELETE FROM match_review_queue q
                USING clouder_tracks t
                WHERE t.id = q.clouder_track_id
                  AND q.vendor = 'ytmusic' AND q.status = 'pending'
                  AND q.created_at < t.publish_date + :days * interval '1 day'
                  AND q.created_at <= :now - :days * interval '1 day'
                RETURNING q.clouder_track_id
            )
            UPDATE clouder_tracks SET youtube_searched_at = NULL
            WHERE id IN (SELECT clouder_track_id FROM due)
            RETURNING id
            """,
            {"now": now, "days": SECOND_CHANCE_DAYS},
        )
        return len(rows)

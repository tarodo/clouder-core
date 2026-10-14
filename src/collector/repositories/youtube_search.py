"""YouTube search state: which tracks to search, claims, done stamps, release."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from ._base import RepositoryBase

# Tracks worth a YouTube search: new since the launch, or older ones a user is
# working with (a category, or a triage block still in progress). The archive
# is left alone. A UNION of three small id sets keeps the lookup off a scan of
# every unsearched archive row.
_CANDIDATE_IDS = """
    SELECT id FROM clouder_tracks
    WHERE youtube_searched_at IS NULL AND created_at >= :since
    UNION
    SELECT ct.track_id FROM category_tracks ct
    JOIN categories c ON c.id = ct.category_id
    WHERE c.deleted_at IS NULL
    UNION
    SELECT tbt.track_id FROM triage_bucket_tracks tbt
    JOIN triage_buckets b ON b.id = tbt.triage_bucket_id
    JOIN triage_blocks tb ON tb.id = b.triage_block_id
    WHERE tb.status = 'IN_PROGRESS' AND tb.deleted_at IS NULL
"""


class YoutubeSearchMixin(RepositoryBase):
    def claim_tracks_for_youtube_search(
        self, limit: int, claimed_at: datetime, since: datetime
    ) -> list[dict[str, Any]]:
        """Stamp the next *limit* candidates with *claimed_at* and return their
        search inputs, in one statement (SKIP LOCKED + repeated IS NULL, as the
        Spotify claim). `has_ytmusic` marks tracks that already have a YT Music
        match, review or no_match row: only their video is still looked for."""
        return self._data_api.execute(
            f"""
            WITH claimed AS (
                UPDATE clouder_tracks
                SET youtube_searched_at = :claimed_at
                WHERE id IN (
                    SELECT id FROM clouder_tracks
                    WHERE id IN ({_CANDIDATE_IDS})
                      AND youtube_searched_at IS NULL
                    ORDER BY created_at DESC
                    LIMIT :limit
                    FOR UPDATE SKIP LOCKED
                )
                  AND youtube_searched_at IS NULL
                RETURNING id, title, length_ms, album_id, created_at
            )
            SELECT c.id, c.title, c.length_ms, alb.title AS album_title,
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
            GROUP BY c.id, c.title, c.length_ms, alb.title, c.created_at
            ORDER BY c.created_at DESC
            """,
            {"limit": limit, "claimed_at": claimed_at, "since": since},
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

    def has_tracks_needing_youtube_search(self, since: datetime) -> bool:
        rows = self._data_api.execute(
            f"""
            SELECT 1 FROM clouder_tracks
            WHERE id IN ({_CANDIDATE_IDS}) AND youtube_searched_at IS NULL
            LIMIT 1
            """,
            {"since": since},
        )
        return bool(rows)

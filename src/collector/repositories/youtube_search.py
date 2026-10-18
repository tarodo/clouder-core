"""YouTube search state: which tracks to search, claims, done stamps, release."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from ._base import LABELED_TRACK_IDS, RepositoryBase

# Tracks worth a YouTube search: new since the launch, or older ones a user is
# working with (labeled: a category, or DISCARD in any block; or in a triage
# block still in progress). The rest of the archive is left alone. A UNION of
# small id sets keeps the lookup off a scan of every unsearched archive row.
_BASE_CANDIDATE_IDS = f"""
    SELECT id FROM clouder_tracks
    WHERE youtube_searched_at IS NULL AND created_at >= :since
    UNION
    {LABELED_TRACK_IDS}
    UNION
    SELECT tbt.track_id FROM triage_bucket_tracks tbt
    JOIN triage_buckets b ON b.id = tbt.triage_bucket_id
    JOIN triage_blocks tb ON tb.id = b.triage_block_id
    WHERE tb.status = 'IN_PROGRESS' AND tb.deleted_at IS NULL
"""
# Plus recent releases ingested before the launch (e.g. week 40, ingested early).
_PUBLISHED_IDS = """
    UNION
    SELECT id FROM clouder_tracks
    WHERE youtube_searched_at IS NULL AND publish_date >= :published_since
"""


def _candidates(published_since: date | None) -> tuple[str, dict[str, Any]]:
    if published_since is None:
        return _BASE_CANDIDATE_IDS, {}
    return _BASE_CANDIDATE_IDS + _PUBLISHED_IDS, {"published_since": published_since}


class YoutubeSearchMixin(RepositoryBase):
    def claim_tracks_for_youtube_search(
        self,
        limit: int,
        claimed_at: datetime,
        since: datetime,
        published_since: date | None = None,
    ) -> list[dict[str, Any]]:
        """Stamp the next *limit* candidates with *claimed_at* and return their
        search inputs, in one statement (SKIP LOCKED in a materialized pick,
        repeated IS NULL on the update). `has_ytmusic` marks tracks that already have a YT Music
        match, review or no_match row: only their video is still looked for."""
        candidate_ids, extra = _candidates(published_since)
        return self._data_api.execute(
            f"""
            WITH picked AS MATERIALIZED (
                -- Materialized: run once. `IN (... LIMIT n FOR UPDATE SKIP
                -- LOCKED)` may be re-executed per row, each run locking the
                -- next row, and claim far more than n (seen once in tests).
                SELECT id FROM clouder_tracks
                WHERE id IN ({candidate_ids})
                  AND youtube_searched_at IS NULL
                ORDER BY created_at DESC
                LIMIT :limit
                FOR UPDATE SKIP LOCKED
            ),
            claimed AS (
                UPDATE clouder_tracks t
                SET youtube_searched_at = :claimed_at
                FROM picked
                WHERE t.id = picked.id
                  AND t.youtube_searched_at IS NULL
                RETURNING t.id, t.title, t.mix_name, t.length_ms, t.album_id, t.created_at
            )
            SELECT c.id, c.title, c.mix_name, c.length_ms, alb.title AS album_title,
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
            GROUP BY c.id, c.title, c.mix_name, c.length_ms, alb.title, c.created_at
            ORDER BY c.created_at DESC
            """,
            {"limit": limit, "claimed_at": claimed_at, "since": since, **extra},
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

    def has_tracks_needing_youtube_search(
        self, since: datetime, published_since: date | None = None
    ) -> bool:
        candidate_ids, extra = _candidates(published_since)
        rows = self._data_api.execute(
            f"""
            SELECT 1 FROM clouder_tracks
            WHERE id IN ({candidate_ids}) AND youtube_searched_at IS NULL
            LIMIT 1
            """,
            {"since": since, **extra},
        )
        return bool(rows)

    def youtube_search_counts(
        self, since: datetime, recent_since: datetime, published_since: date | None = None
    ) -> dict[str, int]:
        """Backlog and outcomes behind the admin YouTube search status."""
        candidate_ids, extra = _candidates(published_since)
        rows = self._data_api.execute(
            f"""
            SELECT
                (SELECT count(*) FROM clouder_tracks
                 WHERE id IN ({candidate_ids}) AND youtube_searched_at IS NULL) AS waiting,
                (SELECT count(*) FROM clouder_tracks
                 WHERE youtube_searched_at >= :recent_since) AS searched_recently,
                (SELECT count(*) FROM clouder_tracks
                 WHERE youtube_searched_at IS NOT NULL) AS searched_total,
                (SELECT count(*) FROM vendor_track_map WHERE vendor = 'ytmusic') AS matched,
                (SELECT count(*) FROM match_review_queue
                 WHERE vendor = 'ytmusic' AND status = 'pending') AS needs_review,
                (SELECT count(*) FROM match_review_queue
                 WHERE vendor = 'ytmusic' AND status = 'no_match') AS not_found,
                (SELECT count(*) FROM vendor_track_map WHERE vendor = 'youtube') AS videos
            """,
            {"since": since, "recent_since": recent_since, **extra},
        )
        return {k: int(v or 0) for k, v in rows[0].items()}

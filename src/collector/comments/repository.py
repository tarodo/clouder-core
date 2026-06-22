"""Data-access for comment collections (RDS Data API, no psycopg)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import uuid4

from ..data_api import DataAPIClient, create_default_data_api_client
from ..providers.base import CollectedComment
from ..settings import get_data_api_settings


@dataclass(frozen=True)
class CollectionRow:
    id: str
    track_id: str
    platform: str
    external_video_id: str
    status: str
    comment_count: int
    collected_at: datetime | None


@dataclass(frozen=True)
class CommentRow:
    author_name: str
    author_avatar_url: str | None
    text: str
    like_count: int
    published_at: Any  # str|datetime from Data API; serialized as-is by the handler
    rank: int


@dataclass(frozen=True)
class TrackMeta:
    track_id: str
    artist: str
    title: str
    duration_ms: int | None


class CommentsRepository:
    def __init__(self, data_api: DataAPIClient) -> None:
        self._data_api = data_api

    def start_collection(
        self, *, track_id: str, platform: str, video_id: str, now: datetime
    ) -> str | None:
        """Insert/refresh a pending collection. Returns the collection id, or
        None if a completed collection already exists (for any video when
        video_id is empty, otherwise for the same video)."""
        # Best-effort skip guard: two concurrent dispatchers can both pass this
        # SELECT, but the INSERT ... ON CONFLICT below keeps the write safe (last
        # writer wins, same id returned); worst case is a redundant re-collection,
        # which is acceptable given the worker's 1-request budget.
        existing = self._data_api.execute(
            "SELECT id, external_video_id, status FROM comment_collections "
            "WHERE track_id = :t AND platform = :p",
            {"t": track_id, "p": platform},
        )
        if existing:
            row = existing[0]
            if row["status"] == "collected" and (
                not video_id or row["external_video_id"] == video_id
            ):
                return None

        rows = self._data_api.execute(
            """
            INSERT INTO comment_collections
                (id, track_id, platform, external_video_id, status, comment_count, created_at, updated_at)
            VALUES (:id, :t, :p, :v, 'pending', 0, :now, :now)
            ON CONFLICT (track_id, platform) DO UPDATE SET
                external_video_id = EXCLUDED.external_video_id,
                status = 'pending',
                comment_count = 0,
                error = NULL,
                collected_at = NULL,
                updated_at = EXCLUDED.updated_at
            RETURNING id
            """,
            {"id": str(uuid4()), "t": track_id, "p": platform, "v": video_id, "now": now},
        )
        return rows[0]["id"] if rows else None

    def store_comments(
        self,
        *,
        collection_id: str,
        platform: str,
        comments: list[CollectedComment],
        status: str,
        now: datetime,
        error: str | None = None,
        external_video_id: str | None = None,
    ) -> None:
        with self._data_api.transaction() as tx:
            self._data_api.execute(
                "DELETE FROM external_comments WHERE collection_id = :c",
                {"c": collection_id},
                transaction_id=tx,
            )
            if comments:
                self._data_api.batch_execute(
                    """
                    INSERT INTO external_comments
                        (id, collection_id, platform, external_comment_id, author_name,
                         author_avatar_url, text, like_count, published_at, rank, created_at)
                    VALUES (:id, :c, :p, :eid, :an, :av, :txt, :lk, :pub, :rk, :now)
                    """,
                    [
                        {
                            "id": str(uuid4()),
                            "c": collection_id,
                            "p": platform,
                            "eid": cm.external_id,
                            "an": cm.author_name,
                            "av": cm.author_avatar_url,
                            "txt": cm.text,
                            "lk": cm.like_count,
                            "pub": cm.published_at,
                            "rk": cm.rank,
                            "now": now,
                        }
                        for cm in comments
                    ],
                    transaction_id=tx,
                )
            set_evid = ", external_video_id = :evid" if external_video_id is not None else ""
            update_params: dict[str, Any] = {
                "s": status, "n": len(comments), "e": error, "now": now, "c": collection_id,
            }
            if external_video_id is not None:
                update_params["evid"] = external_video_id
            self._data_api.execute(
                f"""
                UPDATE comment_collections
                SET status = :s, comment_count = :n, error = :e,
                    collected_at = :now, updated_at = :now{set_evid}
                WHERE id = :c
                """,
                update_params,
                transaction_id=tx,
            )

    def list_comments_for_tracks(
        self,
        *,
        track_ids: list[str],
        platform: str,
        limit_per_track: int = 100,
    ) -> dict[str, tuple[CollectionRow | None, list[CommentRow]]]:
        """Return ALL comments (up to limit_per_track) for many tracks at once.

        Returns a dict keyed by track_id.  Tracks with no collection row are
        absent from the result (callers treat a missing key as "no comments").
        """
        if not track_ids:
            return {}

        # --- Query 1: collections for the requested track_ids + platform ---
        placeholders = ", ".join(f":t{i}" for i in range(len(track_ids)))
        params: dict[str, Any] = {"p": platform}
        for i, tid in enumerate(track_ids):
            params[f"t{i}"] = tid

        coll_rows = self._data_api.execute(
            f"SELECT id, track_id, platform, external_video_id, status, comment_count, collected_at "
            f"FROM comment_collections "
            f"WHERE platform = :p AND track_id IN ({placeholders})",
            params,
        )
        if not coll_rows:
            return {}

        collections: dict[str, CollectionRow] = {}
        coll_id_to_track_id: dict[str, str] = {}
        for r in coll_rows:
            col = CollectionRow(
                id=r["id"],
                track_id=r["track_id"],
                platform=r["platform"],
                external_video_id=r["external_video_id"],
                status=r["status"],
                comment_count=int(r["comment_count"]),
                collected_at=r["collected_at"],
            )
            collections[r["track_id"]] = col
            coll_id_to_track_id[r["id"]] = r["track_id"]

        # --- Query 2: comments for all found collection ids ---
        coll_ids = list(coll_id_to_track_id.keys())
        coll_placeholders = ", ".join(f":c{i}" for i in range(len(coll_ids)))
        coll_params: dict[str, Any] = {}
        for i, cid in enumerate(coll_ids):
            coll_params[f"c{i}"] = cid

        comment_rows = self._data_api.execute(
            f"SELECT author_name, author_avatar_url, text, like_count, published_at, rank, collection_id "
            f"FROM external_comments "
            f"WHERE collection_id IN ({coll_placeholders}) "
            f"ORDER BY collection_id, rank ASC",
            coll_params,
        )

        # Group comments by track_id, preserving ORDER BY rank from the query
        comments_by_track: dict[str, list[CommentRow]] = {tid: [] for tid in collections}
        for r in comment_rows:
            track_id = coll_id_to_track_id.get(r["collection_id"])
            if track_id is None:
                continue
            comments_by_track[track_id].append(
                CommentRow(
                    author_name=r["author_name"],
                    author_avatar_url=r["author_avatar_url"],
                    text=r["text"],
                    like_count=int(r["like_count"]),
                    published_at=r["published_at"],
                    rank=int(r["rank"]),
                )
            )

        # Build result, applying per-track cap
        result: dict[str, tuple[CollectionRow | None, list[CommentRow]]] = {}
        for tid, col in collections.items():
            result[tid] = (col, comments_by_track[tid][:limit_per_track])
        return result

    def fetch_track_meta(self, track_ids: list[str]) -> dict[str, "TrackMeta"]:
        """artist/title/duration for the given tracks (for fallback search).

        Unlike playlists_repository.fetch_unmatched_match_inputs, this does NOT
        anti-join vendor_track_map/match_review_queue — our tracks are already
        matched."""
        if not track_ids:
            return {}
        placeholders = ", ".join(f":t{i}" for i in range(len(track_ids)))
        params: dict[str, Any] = {}
        for i, tid in enumerate(track_ids):
            params[f"t{i}"] = tid
        rows = self._data_api.execute(
            f"""
            SELECT
                t.id AS track_id,
                t.title,
                t.length_ms,
                COALESCE(STRING_AGG(DISTINCT a.name, ', ' ORDER BY a.name), '') AS artist_names
            FROM clouder_tracks t
            LEFT JOIN clouder_track_artists cta ON cta.track_id = t.id
            LEFT JOIN clouder_artists       a   ON a.id = cta.artist_id
            WHERE t.id IN ({placeholders})
            GROUP BY t.id, t.title, t.length_ms
            """,
            params,
        )
        out: dict[str, TrackMeta] = {}
        for r in rows:
            length = r.get("length_ms")
            out[r["track_id"]] = TrackMeta(
                track_id=r["track_id"],
                artist=r.get("artist_names") or "",
                title=r.get("title") or "",
                duration_ms=int(length) if length is not None else None,
            )
        return out

    def list_comments(
        self, *, track_id: str, platform: str, limit: int
    ) -> tuple[CollectionRow | None, list[CommentRow]]:
        coll = self._data_api.execute(
            "SELECT id, track_id, platform, external_video_id, status, comment_count, collected_at "
            "FROM comment_collections WHERE track_id = :t AND platform = :p",
            {"t": track_id, "p": platform},
        )
        if not coll:
            return None, []
        c = coll[0]
        collection = CollectionRow(
            id=c["id"],
            track_id=c["track_id"],
            platform=c["platform"],
            external_video_id=c["external_video_id"],
            status=c["status"],
            comment_count=int(c["comment_count"]),
            collected_at=c["collected_at"],
        )
        rows = self._data_api.execute(
            "SELECT author_name, author_avatar_url, text, like_count, published_at, rank "
            "FROM external_comments WHERE collection_id = :c ORDER BY rank ASC LIMIT :lim",
            {"c": collection.id, "lim": int(limit)},
        )
        comments = [
            CommentRow(
                author_name=r["author_name"],
                author_avatar_url=r["author_avatar_url"],
                text=r["text"],
                like_count=int(r["like_count"]),
                published_at=r["published_at"],
                rank=int(r["rank"]),
            )
            for r in rows
        ]
        return collection, comments


def create_default_comments_repository() -> "CommentsRepository | None":
    settings = get_data_api_settings()
    if not settings.is_configured:
        return None
    client = create_default_data_api_client(
        resource_arn=str(settings.aurora_cluster_arn),
        secret_arn=str(settings.aurora_secret_arn),
        database=settings.aurora_database,
    )
    return CommentsRepository(data_api=client)

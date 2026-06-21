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


class CommentsRepository:
    def __init__(self, data_api: DataAPIClient) -> None:
        self._data_api = data_api

    def start_collection(
        self, *, track_id: str, platform: str, video_id: str, now: datetime
    ) -> str | None:
        """Insert/refresh a pending collection. Returns the collection id, or
        None if a completed collection for the same video already exists."""
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
            if row["status"] == "collected" and row["external_video_id"] == video_id:
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
            self._data_api.execute(
                """
                UPDATE comment_collections
                SET status = :s, comment_count = :n, error = :e,
                    collected_at = :now, updated_at = :now
                WHERE id = :c
                """,
                {"s": status, "n": len(comments), "e": error, "now": now, "c": collection_id},
                transaction_id=tx,
            )

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

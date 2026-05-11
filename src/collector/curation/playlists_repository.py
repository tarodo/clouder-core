"""Aurora Data API repository for playlists (spec 2026-05-11).

Tenancy: every method takes user_id and includes it in WHERE.
Cross-user access yields no rows → handler maps to 404.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Mapping

from collector.data_api import DataAPIClient
from collector.settings import get_data_api_settings

from . import (
    PlaylistLimitReachedError,
    PlaylistNameConflictError,
    PlaylistNotFoundError,
)
from .playlists_service import MAX_PLAYLISTS_PER_USER


@dataclass(frozen=True)
class PlaylistRow:
    id: str
    user_id: str
    name: str
    normalized_name: str
    description: str | None
    is_public: bool
    cover_s3_key: str | None
    cover_uploaded_at: str | None
    spotify_playlist_id: str | None
    last_published_at: str | None
    needs_republish: bool
    track_count: int
    created_at: str
    updated_at: str


_PLAYLIST_SELECT = """
    SELECT
        p.id, p.user_id, p.name, p.normalized_name, p.description,
        p.is_public, p.cover_s3_key, p.cover_uploaded_at,
        p.spotify_playlist_id, p.last_published_at, p.needs_republish,
        p.created_at, p.updated_at,
        COALESCE(t.cnt, 0) AS track_count
    FROM playlists p
    LEFT JOIN (
        SELECT playlist_id, COUNT(*) AS cnt
        FROM playlist_tracks
        GROUP BY playlist_id
    ) t ON t.playlist_id = p.id
"""


def _row(raw: Mapping[str, Any]) -> PlaylistRow:
    return PlaylistRow(
        id=raw["id"],
        user_id=raw["user_id"],
        name=raw["name"],
        normalized_name=raw["normalized_name"],
        description=raw.get("description"),
        is_public=bool(raw["is_public"]),
        cover_s3_key=raw.get("cover_s3_key"),
        cover_uploaded_at=(
            str(raw["cover_uploaded_at"])
            if raw.get("cover_uploaded_at") else None
        ),
        spotify_playlist_id=raw.get("spotify_playlist_id"),
        last_published_at=(
            str(raw["last_published_at"])
            if raw.get("last_published_at") else None
        ),
        needs_republish=bool(raw["needs_republish"]),
        track_count=int(raw.get("track_count") or 0),
        created_at=str(raw["created_at"]),
        updated_at=str(raw["updated_at"]),
    )


class PlaylistsRepository:
    def __init__(self, data_api: DataAPIClient) -> None:
        self._data_api = data_api

    # ---------- CRUD ---------------------------------------------------------

    def create(
        self,
        *,
        user_id: str,
        playlist_id: str,
        name: str,
        normalized_name: str,
        description: str | None,
        is_public: bool,
        now: datetime,
    ) -> PlaylistRow:
        with self._data_api.transaction() as tx_id:
            count_rows = self._data_api.execute(
                "SELECT COUNT(*) AS cnt FROM playlists "
                "WHERE user_id = :user_id AND deleted_at IS NULL",
                {"user_id": user_id},
                transaction_id=tx_id,
            )
            cnt = int(count_rows[0]["cnt"]) if count_rows else 0
            if cnt >= MAX_PLAYLISTS_PER_USER:
                raise PlaylistLimitReachedError(
                    f"User has reached {MAX_PLAYLISTS_PER_USER} active playlists"
                )

            try:
                rows = self._data_api.execute(
                    """
                    INSERT INTO playlists (
                        id, user_id, name, normalized_name, description,
                        is_public, cover_s3_key, cover_uploaded_at,
                        spotify_playlist_id, last_published_at, needs_republish,
                        created_at, updated_at, deleted_at
                    ) VALUES (
                        :id, :user_id, :name, :normalized_name, :description,
                        :is_public, NULL, NULL,
                        NULL, NULL, FALSE,
                        :now, :now, NULL
                    )
                    RETURNING id, user_id, name, normalized_name, description,
                              is_public, cover_s3_key, cover_uploaded_at,
                              spotify_playlist_id, last_published_at,
                              needs_republish, 0 AS track_count,
                              created_at, updated_at
                    """,
                    {
                        "id": playlist_id,
                        "user_id": user_id,
                        "name": name,
                        "normalized_name": normalized_name,
                        "description": description,
                        "is_public": is_public,
                        "now": now,
                    },
                    transaction_id=tx_id,
                )
            except Exception as exc:
                if "uq_playlists_user_normname" in str(exc):
                    raise PlaylistNameConflictError(
                        "Playlist name already exists"
                    ) from exc
                raise
            return _row(rows[0])

    def get(self, *, user_id: str, playlist_id: str) -> PlaylistRow | None:
        rows = self._data_api.execute(
            _PLAYLIST_SELECT
            + " WHERE p.id = :id AND p.user_id = :user_id "
              "AND p.deleted_at IS NULL",
            {"id": playlist_id, "user_id": user_id},
        )
        return _row(rows[0]) if rows else None

    def list_all(
        self, *, user_id: str, limit: int, offset: int
    ) -> tuple[list[PlaylistRow], int]:
        rows = self._data_api.execute(
            _PLAYLIST_SELECT
            + " WHERE p.user_id = :user_id AND p.deleted_at IS NULL "
              "ORDER BY p.created_at DESC, p.id ASC "
              "LIMIT :limit OFFSET :offset",
            {"user_id": user_id, "limit": limit, "offset": offset},
        )
        total_rows = self._data_api.execute(
            "SELECT COUNT(*) AS total FROM playlists "
            "WHERE user_id = :user_id AND deleted_at IS NULL",
            {"user_id": user_id},
        )
        total = int(total_rows[0]["total"]) if total_rows else 0
        return [_row(r) for r in rows], total

    def patch(
        self,
        *,
        user_id: str,
        playlist_id: str,
        name: str | None,
        normalized_name: str | None,
        description: str | None,
        is_public: bool | None,
        now: datetime,
    ) -> PlaylistRow:
        """Partial update. None values mean "leave as is".

        If the row is already published (spotify_playlist_id IS NOT NULL),
        marks needs_republish=TRUE inside the same statement.
        """
        try:
            rows = self._data_api.execute(
                """
                UPDATE playlists SET
                    name = COALESCE(:name, name),
                    normalized_name = COALESCE(:normalized_name, normalized_name),
                    description = CASE WHEN :description_set THEN :description ELSE description END,
                    is_public = COALESCE(:is_public, is_public),
                    needs_republish = CASE
                        WHEN spotify_playlist_id IS NOT NULL THEN TRUE
                        ELSE needs_republish
                    END,
                    updated_at = :now
                WHERE id = :id AND user_id = :user_id AND deleted_at IS NULL
                RETURNING id, user_id, name, normalized_name, description,
                          is_public, cover_s3_key, cover_uploaded_at,
                          spotify_playlist_id, last_published_at, needs_republish,
                          created_at, updated_at
                """,
                {
                    "id": playlist_id,
                    "user_id": user_id,
                    "name": name,
                    "normalized_name": normalized_name,
                    "description": description,
                    "description_set": description is not None,
                    "is_public": is_public,
                    "now": now,
                },
            )
        except Exception as exc:
            if "uq_playlists_user_normname" in str(exc):
                raise PlaylistNameConflictError(
                    "Playlist name already exists"
                ) from exc
            raise
        if not rows:
            raise PlaylistNotFoundError()
        # track_count not returned by UPDATE; re-select to attach it.
        # If the row vanished between UPDATE and SELECT (concurrent
        # soft-delete), surface as 404 rather than synthesizing a stale row.
        result = self.get(user_id=user_id, playlist_id=playlist_id)
        if result is None:
            raise PlaylistNotFoundError()
        return result

    def soft_delete(
        self, *, user_id: str, playlist_id: str, now: datetime
    ) -> bool:
        rows = self._data_api.execute(
            """
            UPDATE playlists SET deleted_at = :now, updated_at = :now
            WHERE id = :id AND user_id = :user_id AND deleted_at IS NULL
            RETURNING id
            """,
            {"id": playlist_id, "user_id": user_id, "now": now},
        )
        return bool(rows)


def create_default_playlists_repository() -> PlaylistsRepository | None:
    settings = get_data_api_settings()
    if not settings.is_configured:
        return None
    from collector.data_api import create_default_data_api_client

    data_api = create_default_data_api_client(
        resource_arn=str(settings.aurora_cluster_arn),
        secret_arn=str(settings.aurora_secret_arn),
        database=settings.aurora_database,
    )
    return PlaylistsRepository(data_api=data_api)

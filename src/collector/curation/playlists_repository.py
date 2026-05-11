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
    PlaylistTrackLimitError,
)
from .playlists_service import (
    MAX_PLAYLISTS_PER_USER,
    MAX_TRACKS_PER_PLAYLIST,
    validate_reorder_set,
)


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


@dataclass(frozen=True)
class PlaylistTrackRow:
    track_id: str
    position: int
    added_at: str
    title: str
    spotify_id: str | None
    isrc: str | None
    length_ms: int | None
    origin: str


@dataclass(frozen=True)
class AppendTracksResult:
    added_track_ids: list[str]
    skipped_duplicates: list[str]
    position_after: int


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

    # ---------- Tracks -------------------------------------------------------

    def append_tracks(
        self,
        *,
        user_id: str,
        playlist_id: str,
        track_ids: list[str],
        now: datetime,
    ) -> AppendTracksResult:
        with self._data_api.transaction() as tx_id:
            owner_rows = self._data_api.execute(
                "SELECT 1 AS ok FROM playlists "
                "WHERE id = :id AND user_id = :user_id AND deleted_at IS NULL",
                {"id": playlist_id, "user_id": user_id},
                transaction_id=tx_id,
            )
            if not owner_rows:
                raise PlaylistNotFoundError()

            if not track_ids:
                max_rows = self._data_api.execute(
                    "SELECT COALESCE(MAX(position), -1) AS max_pos "
                    "FROM playlist_tracks WHERE playlist_id = :id",
                    {"id": playlist_id},
                    transaction_id=tx_id,
                )
                start = int(max_rows[0]["max_pos"]) + 1
                return AppendTracksResult([], [], start)

            count_rows = self._data_api.execute(
                "SELECT COUNT(*) AS cnt FROM playlist_tracks "
                "WHERE playlist_id = :id",
                {"id": playlist_id},
                transaction_id=tx_id,
            )
            current = int(count_rows[0]["cnt"]) if count_rows else 0

            existing_rows = self._data_api.execute(
                "SELECT track_id FROM playlist_tracks "
                "WHERE playlist_id = :id AND track_id = ANY(:ids)",
                {"id": playlist_id, "ids": track_ids},
                transaction_id=tx_id,
            )
            existing = {r["track_id"] for r in existing_rows}

            to_add = [t for t in track_ids if t not in existing]
            skipped = [t for t in track_ids if t in existing]

            if current + len(to_add) > MAX_TRACKS_PER_PLAYLIST:
                raise PlaylistTrackLimitError(
                    f"Cannot exceed {MAX_TRACKS_PER_PLAYLIST} tracks per playlist"
                )

            max_rows = self._data_api.execute(
                "SELECT COALESCE(MAX(position), -1) AS max_pos "
                "FROM playlist_tracks WHERE playlist_id = :id",
                {"id": playlist_id},
                transaction_id=tx_id,
            )
            start = int(max_rows[0]["max_pos"]) + 1

            if to_add:
                self._data_api.batch_execute(
                    "INSERT INTO playlist_tracks "
                    "(playlist_id, track_id, position, added_at) "
                    "VALUES (:playlist_id, :track_id, :position, :now)",
                    [
                        {
                            "playlist_id": playlist_id,
                            "track_id": t,
                            "position": start + i,
                            "now": now,
                        }
                        for i, t in enumerate(to_add)
                    ],
                    transaction_id=tx_id,
                )
                self._mark_dirty_if_published(playlist_id, now, tx_id)

            return AppendTracksResult(
                added_track_ids=to_add,
                skipped_duplicates=skipped,
                position_after=start + len(to_add),
            )

    def remove_track(
        self,
        *,
        user_id: str,
        playlist_id: str,
        track_id: str,
        now: datetime,
    ) -> bool:
        with self._data_api.transaction() as tx_id:
            owner_rows = self._data_api.execute(
                "SELECT 1 AS ok FROM playlists "
                "WHERE id = :id AND user_id = :user_id AND deleted_at IS NULL",
                {"id": playlist_id, "user_id": user_id},
                transaction_id=tx_id,
            )
            if not owner_rows:
                raise PlaylistNotFoundError()

            pos_rows = self._data_api.execute(
                "SELECT position FROM playlist_tracks "
                "WHERE playlist_id = :id AND track_id = :tid",
                {"id": playlist_id, "tid": track_id},
                transaction_id=tx_id,
            )
            if not pos_rows:
                return False
            removed_pos = int(pos_rows[0]["position"])

            self._data_api.execute(
                "DELETE FROM playlist_tracks "
                "WHERE playlist_id = :id AND track_id = :tid",
                {"id": playlist_id, "tid": track_id},
                transaction_id=tx_id,
            )
            self._data_api.execute(
                "UPDATE playlist_tracks SET position = position - 1 "
                "WHERE playlist_id = :id AND position > :pos",
                {"id": playlist_id, "pos": removed_pos},
                transaction_id=tx_id,
            )
            self._mark_dirty_if_published(playlist_id, now, tx_id)
            return True

    def reorder_tracks(
        self,
        *,
        user_id: str,
        playlist_id: str,
        ordered_track_ids: list[str],
        now: datetime,
    ) -> None:
        with self._data_api.transaction() as tx_id:
            owner_rows = self._data_api.execute(
                "SELECT 1 AS ok FROM playlists "
                "WHERE id = :id AND user_id = :user_id AND deleted_at IS NULL",
                {"id": playlist_id, "user_id": user_id},
                transaction_id=tx_id,
            )
            if not owner_rows:
                raise PlaylistNotFoundError()

            current = self._data_api.execute(
                "SELECT track_id FROM playlist_tracks WHERE playlist_id = :id",
                {"id": playlist_id},
                transaction_id=tx_id,
            )
            actual_ids = [r["track_id"] for r in current]
            validate_reorder_set(actual=actual_ids, requested=ordered_track_ids)

            # Two-phase: shift everyone past the max position, then put them
            # back with desired positions. Avoids stepping on the
            # (playlist_id, position) UNIQUE even though it is DEFERRABLE.
            self._data_api.execute(
                "UPDATE playlist_tracks "
                "SET position = position + :offset "
                "WHERE playlist_id = :id",
                {"id": playlist_id, "offset": len(actual_ids) + 1},
                transaction_id=tx_id,
            )
            self._data_api.batch_execute(
                "UPDATE playlist_tracks SET position = :position "
                "WHERE playlist_id = :playlist_id AND track_id = :track_id",
                [
                    {"playlist_id": playlist_id, "track_id": t, "position": i}
                    for i, t in enumerate(ordered_track_ids)
                ],
                transaction_id=tx_id,
            )
            self._mark_dirty_if_published(playlist_id, now, tx_id)

    def list_tracks(
        self,
        *,
        user_id: str,
        playlist_id: str,
        limit: int,
        offset: int,
    ) -> tuple[list[PlaylistTrackRow], int]:
        owner = self._data_api.execute(
            "SELECT 1 AS ok FROM playlists "
            "WHERE id = :id AND user_id = :user_id AND deleted_at IS NULL",
            {"id": playlist_id, "user_id": user_id},
        )
        if not owner:
            raise PlaylistNotFoundError()
        rows = self._data_api.execute(
            """
            SELECT pt.track_id, pt.position, pt.added_at,
                   t.title, t.spotify_id, t.isrc, t.length_ms, t.origin
            FROM playlist_tracks pt
            JOIN clouder_tracks t ON t.id = pt.track_id
            WHERE pt.playlist_id = :id
            ORDER BY pt.position ASC
            LIMIT :limit OFFSET :offset
            """,
            {"id": playlist_id, "limit": limit, "offset": offset},
        )
        total_rows = self._data_api.execute(
            "SELECT COUNT(*) AS total FROM playlist_tracks pt2 "
            "WHERE pt2.playlist_id = :id",
            {"id": playlist_id},
        )
        total = int(total_rows[0]["total"]) if total_rows else 0
        out = [
            PlaylistTrackRow(
                track_id=r["track_id"],
                position=int(r["position"]),
                added_at=str(r["added_at"]),
                title=r["title"],
                spotify_id=r.get("spotify_id"),
                isrc=r.get("isrc"),
                length_ms=(int(r["length_ms"]) if r.get("length_ms") else None),
                origin=r.get("origin") or "beatport",
            )
            for r in rows
        ]
        return out, total

    # ---------- Helpers ------------------------------------------------------

    def _mark_dirty_if_published(
        self, playlist_id: str, now: datetime, tx_id: str
    ) -> None:
        self._data_api.execute(
            "UPDATE playlists SET needs_republish = TRUE, updated_at = :now "
            "WHERE id = :id AND spotify_playlist_id IS NOT NULL",
            {"id": playlist_id, "now": now},
            transaction_id=tx_id,
        )


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

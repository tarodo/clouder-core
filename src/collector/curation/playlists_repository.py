"""Aurora Data API repository for playlists (spec 2026-05-11).

Tenancy: every method takes user_id and includes it in WHERE.
Cross-user access yields no rows → handler maps to 404.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, replace
from datetime import datetime
from typing import TYPE_CHECKING, Any, Literal, Mapping

from collector.data_api import DataAPIClient
from collector.models import normalize_text
from collector.settings import get_data_api_settings

if TYPE_CHECKING:
    from .tags_repository import TagsRepository, TrackTagRow

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
    status: str  # 'active' | 'completed'


_PLAYLIST_SELECT = """
    SELECT
        p.id, p.user_id, p.name, p.normalized_name, p.description,
        p.is_public, p.cover_s3_key, p.cover_uploaded_at,
        p.spotify_playlist_id, p.last_published_at, p.needs_republish,
        p.status, p.created_at, p.updated_at,
        COALESCE(t.cnt, 0) AS track_count
    FROM playlists p
    LEFT JOIN (
        SELECT playlist_id, COUNT(*) AS cnt
        FROM playlist_tracks
        GROUP BY playlist_id
    ) t ON t.playlist_id = p.id
"""


# Aurora Data API forbids passing Python lists as PostgreSQL arrays
# (lists serialize as JSON via `typeHint=JSON`, not as `text[]`), so
# `t.id = ANY(:track_ids)` blows up with
# `op ANY/ALL (array) requires array on right side`. The scope-check SQL
# is built parametrically per-call — see `validate_tracks_in_scope`.
_SCOPE_CHECK_SQL_TEMPLATE = """
    SELECT t.id
    FROM clouder_tracks t
    WHERE t.id IN ({placeholders})
      AND (
        EXISTS (
          SELECT 1 FROM category_tracks ct
          JOIN categories c ON c.id = ct.category_id
          WHERE ct.track_id = t.id AND c.user_id = :user_id
        )
        OR EXISTS (
          SELECT 1 FROM playlist_tracks pt
          JOIN playlists p ON p.id = pt.playlist_id
          WHERE pt.track_id = t.id
            AND p.user_id = :user_id
            AND p.deleted_at IS NULL
        )
        OR EXISTS (
          SELECT 1 FROM user_imported_tracks uit
          WHERE uit.track_id = t.id AND uit.user_id = :user_id
        )
      )
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
        status=raw.get("status") or "active",
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
    mix_name: str | None = None
    bpm: int | None = None
    spotify_release_date: str | None = None
    is_ai_suspected: bool = False
    artists: tuple[dict, ...] = ()
    label: dict | None = None
    tags: tuple[TrackTagRow, ...] = ()
    ytmusic: dict | None = None


@dataclass(frozen=True)
class YtmusicStatus:
    status: Literal["matched", "pending", "needs_review", "not_found"]
    video_id: str | None = None
    url: str | None = None
    confidence: float | None = None


@dataclass(frozen=True)
class AppendTracksResult:
    added_track_ids: list[str]
    skipped_duplicates: list[str]
    position_after: int


@dataclass(frozen=True)
class MatchInput:
    track_id: str
    artist: str
    title: str
    isrc: str | None
    duration_ms: int | None
    album: str | None


class PlaylistsRepository:
    def __init__(self, data_api: DataAPIClient) -> None:
        self._data_api = data_api

    @property
    def data_api(self) -> DataAPIClient:
        """Exposed for collaborators that need read access to other tables
        from inside the same Lambda invocation (e.g. UserSpotifyIdReader)."""
        return self._data_api

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
                              needs_republish, status, 0 AS track_count,
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
        self,
        *,
        user_id: str,
        limit: int,
        offset: int,
        status: str | None = None,
    ) -> tuple[list[PlaylistRow], int]:
        params: dict[str, Any] = {
            "user_id": user_id,
            "limit": limit,
            "offset": offset,
        }
        status_clause = ""
        if status is not None:
            status_clause = " AND p.status = :status"
            params["status"] = status
        rows = self._data_api.execute(
            _PLAYLIST_SELECT
            + f" WHERE p.user_id = :user_id AND p.deleted_at IS NULL{status_clause} "
              "ORDER BY p.created_at DESC, p.id ASC "
              "LIMIT :limit OFFSET :offset",
            params,
        )
        count_params: dict[str, Any] = {"user_id": user_id}
        count_clause = ""
        if status is not None:
            count_clause = " AND status = :status"
            count_params["status"] = status
        total_rows = self._data_api.execute(
            "SELECT COUNT(*) AS total FROM playlists "
            f"WHERE user_id = :user_id AND deleted_at IS NULL{count_clause}",
            count_params,
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
        status: str | None,
        now: datetime,
    ) -> PlaylistRow:
        """Partial update. None values mean "leave as is".

        If the row is already published (spotify_playlist_id IS NOT NULL)
        and the user touches content (name/description/tracks/cover), marks
        needs_republish=TRUE. Status flips alone do NOT trigger drift —
        status is organizational, not Spotify-visible.
        """
        try:
            # Explicit ::type casts on every param: when status-only patches
            # send NULL for name/description/is_public, Aurora Data API fails
            # with `could not determine data type of parameter $N` because
            # the same param is read in multiple contexts (COALESCE for the
            # column AND `IS NOT NULL` for the drift gate). The casts give
            # Postgres a definite type independent of how each call uses it.
            rows = self._data_api.execute(
                """
                UPDATE playlists SET
                    name = COALESCE(:name::text, name),
                    normalized_name = COALESCE(:normalized_name::text, normalized_name),
                    description = CASE WHEN :description_set::boolean
                                       THEN :description::text
                                       ELSE description END,
                    is_public = COALESCE(:is_public::boolean, is_public),
                    status = COALESCE(:status::text, status),
                    needs_republish = CASE
                        WHEN spotify_playlist_id IS NOT NULL
                             AND (:name::text IS NOT NULL
                                  OR :description_set::boolean
                                  OR :is_public::boolean IS NOT NULL)
                        THEN TRUE
                        ELSE needs_republish
                    END,
                    updated_at = :now
                WHERE id = :id AND user_id = :user_id AND deleted_at IS NULL
                RETURNING id, user_id, name, normalized_name, description,
                          is_public, cover_s3_key, cover_uploaded_at,
                          spotify_playlist_id, last_published_at, needs_republish,
                          status, created_at, updated_at
                """,
                {
                    "id": playlist_id,
                    "user_id": user_id,
                    "name": name,
                    "normalized_name": normalized_name,
                    "description": description,
                    "description_set": description is not None,
                    "is_public": is_public,
                    "status": status,
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

            # Aurora Data API forbids array params (see _SCOPE_CHECK_SQL_TEMPLATE
            # note above). Build IN-list parametrically.
            id_placeholders = ", ".join(f":t{i}" for i in range(len(track_ids)))
            id_params: dict[str, Any] = {"id": playlist_id}
            for i, tid in enumerate(track_ids):
                id_params[f"t{i}"] = tid
            existing_rows = self._data_api.execute(
                "SELECT track_id FROM playlist_tracks "
                f"WHERE playlist_id = :id AND track_id IN ({id_placeholders})",
                id_params,
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
        tags_repo: TagsRepository | None = None,
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
            SELECT
                pt.track_id, pt.position, pt.added_at,
                t.title, t.mix_name, t.isrc, t.bpm, t.length_ms,
                t.spotify_id, t.is_ai_suspected, t.spotify_release_date, t.origin,
                COALESCE(
                    JSON_AGG(
                        JSON_BUILD_OBJECT('id', a.id, 'name', a.name)
                        ORDER BY cta.role, a.name
                    ) FILTER (WHERE a.id IS NOT NULL),
                    '[]'::json
                ) AS artists_json,
                l.id   AS label_id,
                l.name AS label_name
            FROM playlist_tracks pt
            JOIN clouder_tracks t ON t.id = pt.track_id
            LEFT JOIN clouder_track_artists cta ON cta.track_id = t.id
            LEFT JOIN clouder_artists       a   ON a.id  = cta.artist_id
            LEFT JOIN clouder_albums        alb ON alb.id = t.album_id
            LEFT JOIN clouder_labels        l   ON l.id   = alb.label_id
            WHERE pt.playlist_id = :id
            GROUP BY pt.track_id, pt.position, pt.added_at, t.id, l.id, l.name
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

        out: list[PlaylistTrackRow] = []
        for r in rows:
            artists_raw = r.get("artists_json", "[]")
            artists = (
                json.loads(artists_raw) if isinstance(artists_raw, str) else (artists_raw or [])
            )
            label_id = r.get("label_id")
            label = {"id": label_id, "name": r.get("label_name")} if label_id else None
            spot = r.get("spotify_release_date")
            out.append(
                PlaylistTrackRow(
                    track_id=r["track_id"],
                    position=int(r["position"]),
                    added_at=str(r["added_at"]),
                    title=r["title"],
                    spotify_id=r.get("spotify_id"),
                    isrc=r.get("isrc"),
                    length_ms=(int(r["length_ms"]) if r.get("length_ms") else None),
                    origin=r.get("origin") or "beatport",
                    mix_name=r.get("mix_name"),
                    bpm=(int(r["bpm"]) if r.get("bpm") is not None else None),
                    spotify_release_date=(str(spot) if spot is not None else None),
                    is_ai_suspected=bool(r.get("is_ai_suspected", False)),
                    artists=tuple(artists),
                    label=label,
                )
            )

        if tags_repo is not None and out:
            grouped = tags_repo.list_tags_for_tracks(
                user_id=user_id, track_ids=[row.track_id for row in out],
            )
            out = [
                replace(row, tags=tuple(grouped.get(row.track_id, [])))
                for row in out
            ]
        if out:
            statuses = self.fetch_ytmusic_status([row.track_id for row in out])
            out = [
                replace(
                    row,
                    ytmusic={
                        "status": s.status,
                        "video_id": s.video_id,
                        "url": s.url,
                        "confidence": s.confidence,
                    } if (s := statuses.get(row.track_id)) else None,
                )
                for row in out
            ]
        return out, total

    # ---------- Cover --------------------------------------------------------

    def set_cover(
        self,
        *,
        user_id: str,
        playlist_id: str,
        s3_key: str,
        now: datetime,
    ) -> bool:
        rows = self._data_api.execute(
            """
            UPDATE playlists SET
                cover_s3_key = :s3_key,
                cover_uploaded_at = :now,
                updated_at = :now,
                needs_republish = CASE
                    WHEN spotify_playlist_id IS NOT NULL THEN TRUE
                    ELSE needs_republish
                END
            WHERE id = :id AND user_id = :user_id AND deleted_at IS NULL
            RETURNING id
            """,
            {"id": playlist_id, "user_id": user_id, "s3_key": s3_key, "now": now},
        )
        return bool(rows)

    def clear_cover(
        self,
        *,
        user_id: str,
        playlist_id: str,
        now: datetime,
    ) -> bool:
        rows = self._data_api.execute(
            """
            UPDATE playlists SET
                cover_s3_key = NULL,
                cover_uploaded_at = NULL,
                updated_at = :now,
                needs_republish = CASE
                    WHEN spotify_playlist_id IS NOT NULL THEN TRUE
                    ELSE needs_republish
                END
            WHERE id = :id AND user_id = :user_id AND deleted_at IS NULL
            RETURNING id
            """,
            {"id": playlist_id, "user_id": user_id, "now": now},
        )
        return bool(rows)

    # ---------- Publish state -----------------------------------------------

    def set_publish_state(
        self,
        *,
        user_id: str,
        playlist_id: str,
        spotify_playlist_id: str,
        now: datetime,
        mark_dirty: bool = False,
    ) -> bool:
        """Persist publish-state.

        When ``mark_dirty`` is True we still record the resulting
        ``spotify_playlist_id`` (so the next publish targets the same
        Spotify playlist) and bump ``last_published_at``, but leave
        ``needs_republish`` as TRUE so the next publish retries the part
        that failed (e.g. cover upload).
        """
        rows = self._data_api.execute(
            """
            UPDATE playlists SET
                spotify_playlist_id = :spotify_playlist_id,
                last_published_at = :now,
                needs_republish = :needs_republish,
                updated_at = :now
            WHERE id = :id AND user_id = :user_id AND deleted_at IS NULL
            RETURNING id
            """,
            {
                "id": playlist_id,
                "user_id": user_id,
                "spotify_playlist_id": spotify_playlist_id,
                "needs_republish": mark_dirty,
                "now": now,
            },
        )
        return bool(rows)

    # ---------- Scope check + import -----------------------------------------

    def validate_tracks_in_scope(
        self,
        *,
        user_id: str,
        track_ids: list[str],
    ) -> set[str]:
        if not track_ids:
            return set()
        placeholders = ", ".join(f":t{i}" for i in range(len(track_ids)))
        params: dict[str, Any] = {"user_id": user_id}
        for i, tid in enumerate(track_ids):
            params[f"t{i}"] = tid
        rows = self._data_api.execute(
            _SCOPE_CHECK_SQL_TEMPLATE.format(placeholders=placeholders),
            params,
        )
        return {r["id"] for r in rows}

    def upsert_imported_track(
        self,
        *,
        user_id: str,
        spotify_id: str,
        title: str,
        isrc: str | None,
        length_ms: int | None,
        now: datetime,
    ) -> str:
        """Idempotent import: returns canonical clouder_tracks.id.

        Two branches:
          1. spotify_id already present → reuse (SELECT-first dedup).
          2. Otherwise INSERT a fresh row.

        Always inserts a (user_id, track_id) marker into user_imported_tracks.
        """
        with self._data_api.transaction() as tx_id:
            existing = self._data_api.execute(
                "SELECT id FROM clouder_tracks WHERE spotify_id = :spotify_id",
                {"spotify_id": spotify_id},
                transaction_id=tx_id,
            )
            if existing:
                track_id = existing[0]["id"]
            else:
                new_id = str(uuid.uuid4())
                # No ON CONFLICT — spotify_id is not unique by design (one
                # Spotify track may map to multiple Beatport tracks, e.g.
                # original vs extended mix).
                inserted = self._data_api.execute(
                    """
                    INSERT INTO clouder_tracks (
                        id, title, normalized_title, isrc, length_ms,
                        spotify_id, origin, created_at, updated_at
                    ) VALUES (
                        :id, :title, :normalized_title, :isrc, :length_ms,
                        :spotify_id, 'spotify_user_import', :now, :now
                    )
                    RETURNING id
                    """,
                    {
                        "id": new_id,
                        "title": title,
                        "normalized_title": normalize_text(title),
                        "isrc": isrc,
                        "length_ms": length_ms,
                        "spotify_id": spotify_id,
                        "now": now,
                    },
                    transaction_id=tx_id,
                )
                track_id = inserted[0]["id"]

            self._data_api.execute(
                """
                INSERT INTO user_imported_tracks (user_id, track_id, imported_at)
                VALUES (:user_id, :track_id, :now)
                ON CONFLICT DO NOTHING
                """,
                {"user_id": user_id, "track_id": track_id, "now": now},
                transaction_id=tx_id,
            )
            return track_id

    # ---------- Vendor match inputs ------------------------------------------

    def fetch_unmatched_match_inputs(
        self, *, track_ids: list[str], vendor: str
    ) -> list[MatchInput]:
        """Metadata for tracks not yet matched to `vendor`, ready to enqueue."""
        if not track_ids:
            return []
        placeholders = ", ".join(f":t{i}" for i in range(len(track_ids)))
        params: dict[str, Any] = {"vendor": vendor}
        for i, tid in enumerate(track_ids):
            params[f"t{i}"] = tid
        rows = self._data_api.execute(
            f"""
            SELECT
                t.id AS track_id,
                t.title,
                t.isrc,
                t.length_ms,
                alb.title AS album_title,
                COALESCE(STRING_AGG(DISTINCT a.name, ', ' ORDER BY a.name), '') AS artist_names
            FROM clouder_tracks t
            LEFT JOIN clouder_track_artists cta ON cta.track_id = t.id
            LEFT JOIN clouder_artists       a   ON a.id = cta.artist_id
            LEFT JOIN clouder_albums        alb ON alb.id = t.album_id
            LEFT JOIN vendor_track_map      vtm
                ON vtm.clouder_track_id = t.id AND vtm.vendor = :vendor
            LEFT JOIN match_review_queue    mrq
                ON mrq.clouder_track_id = t.id AND mrq.vendor = :vendor
            WHERE t.id IN ({placeholders})
              AND vtm.clouder_track_id IS NULL
              AND mrq.clouder_track_id IS NULL
            GROUP BY t.id, t.title, t.isrc, t.length_ms, alb.title
            """,
            params,
        )
        out: list[MatchInput] = []
        for r in rows:
            length = r.get("length_ms")
            out.append(
                MatchInput(
                    track_id=r["track_id"],
                    artist=r.get("artist_names") or "",
                    title=r.get("title") or "",
                    isrc=r.get("isrc"),
                    duration_ms=int(length) if length is not None else None,
                    album=r.get("album_title"),
                )
            )
        return out

    def fetch_ytmusic_status(
        self, track_ids: list[str]
    ) -> dict[str, "YtmusicStatus"]:
        """Per-track YT Music status. matched > needs_review > not_found > pending."""
        if not track_ids:
            return {}
        placeholders = ", ".join(f":t{i}" for i in range(len(track_ids)))
        params: dict[str, Any] = {"vendor": "ytmusic"}
        for i, tid in enumerate(track_ids):
            params[f"t{i}"] = tid

        matched_rows = self._data_api.execute(
            f"""
            SELECT clouder_track_id, vendor_track_id, confidence
            FROM vendor_track_map
            WHERE vendor = :vendor AND clouder_track_id IN ({placeholders})
            """,
            params,
        )
        review_rows = self._data_api.execute(
            f"""
            SELECT clouder_track_id, status
            FROM match_review_queue
            WHERE vendor = :vendor
              AND status IN ('pending', 'no_match')
              AND clouder_track_id IN ({placeholders})
            """,
            params,
        )

        matched = {r["clouder_track_id"]: r for r in matched_rows}
        # A track may have both a 'pending' and a 'no_match' row (separate
        # partial indexes). needs_review outranks not_found, so 'pending' wins.
        review: dict[str, str] = {}
        for r in review_rows:
            tid = r["clouder_track_id"]
            if review.get(tid) == "pending":
                continue
            review[tid] = r["status"]

        out: dict[str, YtmusicStatus] = {}
        for tid in track_ids:
            if tid in matched:
                row = matched[tid]
                vid = row["vendor_track_id"]
                out[tid] = YtmusicStatus(
                    status="matched",
                    video_id=vid,
                    url=f"https://music.youtube.com/watch?v={vid}",
                    confidence=float(row["confidence"]),
                )
            elif review.get(tid) == "pending":
                out[tid] = YtmusicStatus(status="needs_review")
            elif review.get(tid) == "no_match":
                out[tid] = YtmusicStatus(status="not_found")
            else:
                out[tid] = YtmusicStatus(status="pending")
        return out

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

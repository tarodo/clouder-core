"""Publish orchestration for playlists (spec 2026-05-11)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Protocol

from collector.logging_utils import log_event

from . import (
    ConfirmOverwriteRequiredError,
    NothingToPublishError,
    PlaylistNotFoundError,
    SpotifyApiError,
    SpotifyNotAuthorizedError,
    SpotifyNotFoundError,
)


@dataclass(frozen=True)
class PublishResult:
    spotify_playlist_id: str
    spotify_url: str | None
    skipped: list[dict]
    published_at: str
    cover_failed: bool = False


class _UserRepoLike(Protocol):
    def get_spotify_id(self, user_id: str) -> str | None: ...


class PlaylistsPublishService:
    def __init__(
        self,
        *,
        repo,
        spotify_client,
        user_repo: _UserRepoLike,
        storage,
        now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ) -> None:
        self._repo = repo
        self._sp = spotify_client
        self._user_repo = user_repo
        self._storage = storage
        self._now = now

    def publish(
        self,
        *,
        user_id: str,
        playlist_id: str,
        confirm_overwrite: bool,
        treat_404_as_orphan: bool = True,
    ) -> PublishResult:
        playlist = self._repo.get(user_id=user_id, playlist_id=playlist_id)
        if playlist is None:
            raise PlaylistNotFoundError()

        if playlist.spotify_playlist_id and not confirm_overwrite:
            raise ConfirmOverwriteRequiredError(
                "Playlist already published — pass confirm_overwrite=true to replace"
            )

        rows, _total = self._repo.list_tracks(
            user_id=user_id, playlist_id=playlist_id,
            limit=10_000, offset=0,
        )
        skipped = [
            {"track_id": r.track_id, "title": r.title, "reason": "no_spotify_id"}
            for r in rows if not r.spotify_id
        ]
        uris = [f"spotify:track:{r.spotify_id}" for r in rows if r.spotify_id]
        if not uris:
            raise NothingToPublishError("Playlist has no playable tracks")

        user_spotify_id = self._user_repo.get_spotify_id(user_id)
        if not user_spotify_id:
            raise SpotifyNotAuthorizedError("User has no linked Spotify identity")

        log_event(
            "INFO", "playlist_publish_started",
            user_id=user_id, playlist_id=playlist_id,
            first_time=not bool(playlist.spotify_playlist_id),
            track_count=len(uris),
            has_cover=bool(playlist.cover_s3_key),
        )

        target_id = playlist.spotify_playlist_id

        if target_id:
            try:
                self._sp.update_playlist(
                    spotify_playlist_id=target_id,
                    name=playlist.name,
                    description=playlist.description,
                    public=playlist.is_public,
                )
            except SpotifyNotFoundError as exc:
                if not treat_404_as_orphan:
                    raise SpotifyApiError(str(exc)) from exc
                log_event(
                    "WARNING", "playlist_publish_orphan_recreated",
                    user_id=user_id, playlist_id=playlist_id,
                    old_spotify_playlist_id=target_id,
                )
                target_id = None
        if not target_id:
            ref = self._sp.create_playlist(
                user_spotify_id=user_spotify_id,
                name=playlist.name,
                description=playlist.description,
                public=playlist.is_public,
            )
            target_id = ref.id
            spotify_url = ref.url
        else:
            spotify_url = f"https://open.spotify.com/playlist/{target_id}"

        self._sp.replace_tracks(target_id, uris[:100])
        for i in range(100, len(uris), 100):
            self._sp.append_tracks(target_id, uris[i : i + 100])

        cover_failed = False
        if playlist.cover_s3_key:
            try:
                jpeg_bytes = self._storage.read_cover_bytes(playlist.cover_s3_key)
                self._sp.set_cover(target_id, jpeg_bytes)
            except Exception as exc:
                cover_failed = True
                log_event(
                    "WARNING", "playlist_publish_partial_fail",
                    user_id=user_id, playlist_id=playlist_id,
                    stage="cover",
                    error_message=str(exc),
                    error_type=type(exc).__name__,
                )

        now = self._now()
        self._repo.set_publish_state(
            user_id=user_id, playlist_id=playlist_id,
            spotify_playlist_id=target_id, now=now,
            mark_dirty=cover_failed,
        )
        log_event(
            "INFO", "playlist_publish_succeeded",
            user_id=user_id, playlist_id=playlist_id,
            spotify_playlist_id=target_id, skipped=len(skipped),
            cover_failed=cover_failed,
        )
        return PublishResult(
            spotify_playlist_id=target_id,
            spotify_url=spotify_url,
            skipped=skipped,
            published_at=now.isoformat(),
            cover_failed=cover_failed,
        )


class UserSpotifyIdReader:
    """Reads the user's Spotify identity from the users table.

    Used by PlaylistsPublishService to populate the create_playlist URL.
    """

    def __init__(self, data_api) -> None:
        self._data_api = data_api

    def get_spotify_id(self, user_id: str) -> str | None:
        rows = self._data_api.execute(
            "SELECT spotify_id FROM users WHERE id = :id",
            {"id": user_id},
        )
        return rows[0]["spotify_id"] if rows else None

"""Publish orchestration for the YouTube Music target.

Mirror of PlaylistsPublishService. Matched video_ids come from
fetch_ytmusic_status; unmatched tracks are skipped with reason
'no_ytmusic_match'. Cover is best-effort via playlistImages.insert — a
failure flags cover_failed and never blocks the publish.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable

from collector.logging_utils import log_event

from . import (
    ConfirmOverwriteRequiredError,
    NothingToPublishError,
    PlaylistNotFoundError,
    YtmusicApiError,
    YtmusicNotFoundError,
)

_YTMUSIC_PLAYLIST_URL = "https://music.youtube.com/playlist?list={}"


@dataclass(frozen=True)
class YtmusicPublishResult:
    ytmusic_playlist_id: str
    ytmusic_url: str | None
    skipped: list[dict]
    published_at: str
    cover_failed: bool = False


class YtmusicPublishService:
    def __init__(
        self,
        *,
        repo,
        ytmusic_client,
        storage=None,
        now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ) -> None:
        self._repo = repo
        self._yt = ytmusic_client
        self._storage = storage
        self._now = now

    def publish(
        self,
        *,
        user_id: str,
        playlist_id: str,
        confirm_overwrite: bool,
        treat_404_as_orphan: bool = True,
    ) -> YtmusicPublishResult:
        playlist = self._repo.get(user_id=user_id, playlist_id=playlist_id)
        if playlist is None:
            raise PlaylistNotFoundError()

        if playlist.ytmusic_playlist_id and not confirm_overwrite:
            raise ConfirmOverwriteRequiredError(
                "Playlist already published to YouTube Music — pass "
                "confirm_overwrite=true to replace"
            )

        rows, _total = self._repo.list_tracks(
            user_id=user_id, playlist_id=playlist_id, limit=10_000, offset=0
        )
        statuses = self._repo.fetch_ytmusic_status([r.track_id for r in rows])

        video_ids: list[str] = []
        skipped: list[dict] = []
        for r in rows:
            st = statuses.get(r.track_id)
            if st is not None and st.status == "matched" and st.video_id:
                video_ids.append(st.video_id)
            else:
                skipped.append(
                    {"track_id": r.track_id, "title": r.title, "reason": "no_ytmusic_match"}
                )
        if not video_ids:
            raise NothingToPublishError("Playlist has no matched YouTube Music tracks")

        privacy = "PUBLIC" if playlist.is_public else "PRIVATE"

        log_event(
            "INFO", "ytmusic_publish_started",
            user_id=user_id, playlist_id=playlist_id,
            first_time=not bool(playlist.ytmusic_playlist_id),
            track_count=len(video_ids),
        )

        target_id = playlist.ytmusic_playlist_id
        if target_id:
            try:
                self._yt.edit_meta(
                    playlist_id=target_id, name=playlist.name,
                    description=playlist.description, privacy=privacy,
                )
                existing = self._yt.get_existing_items(target_id)
                self._yt.remove_items(target_id, existing)
            except YtmusicNotFoundError as exc:
                if not treat_404_as_orphan:
                    raise YtmusicApiError(str(exc)) from exc
                log_event(
                    "WARNING", "ytmusic_publish_orphan_recreated",
                    user_id=user_id, playlist_id=playlist_id,
                    old_ytmusic_playlist_id=target_id,
                )
                target_id = None

        if not target_id:
            target_id = self._yt.create_playlist(
                name=playlist.name, description=playlist.description, privacy=privacy
            )

        self._yt.add_items(target_id, video_ids)

        cover_failed = False
        cover_key = getattr(playlist, "cover_s3_key", None)
        if cover_key and self._storage is not None:
            try:
                image_bytes = self._storage.read_cover_bytes(cover_key)
                self._yt.set_cover(target_id, image_bytes)
            except Exception as exc:  # noqa: BLE001
                cover_failed = True
                log_event(
                    "WARNING", "ytmusic_publish_partial_fail",
                    user_id=user_id, playlist_id=playlist_id,
                    stage="cover", error_message=str(exc),
                    error_type=type(exc).__name__,
                )

        now = self._now()
        self._repo.set_ytmusic_publish_state(
            user_id=user_id, playlist_id=playlist_id,
            ytmusic_playlist_id=target_id, now=now,
        )
        log_event(
            "INFO", "ytmusic_publish_succeeded",
            user_id=user_id, playlist_id=playlist_id,
            ytmusic_playlist_id=target_id, skipped=len(skipped),
            cover_failed=cover_failed,
        )
        return YtmusicPublishResult(
            ytmusic_playlist_id=target_id,
            ytmusic_url=_YTMUSIC_PLAYLIST_URL.format(target_id),
            skipped=skipped,
            published_at=now.isoformat(),
            cover_failed=cover_failed,
        )

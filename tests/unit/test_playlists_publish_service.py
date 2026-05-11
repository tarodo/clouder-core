"""Publish/import service orchestration. Repository + Spotify client are
MagicMock — we assert on call order and effects."""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from collector.curation import (
    ConfirmOverwriteRequiredError,
    NothingToPublishError,
    PlaylistNotFoundError,
    SpotifyApiError,
)
from collector.curation.playlists_publish_service import (
    PlaylistsPublishService,
    PublishResult,
)


def _utc() -> datetime:
    return datetime(2026, 5, 12, 10, 0, 0, tzinfo=timezone.utc)


def _playlist(**overrides):
    base = dict(
        id="p-1", user_id="u-1", normalized_name="my set",
        description=None, is_public=False, cover_s3_key=None,
        cover_uploaded_at=None, spotify_playlist_id=None,
        last_published_at=None, needs_republish=False, track_count=2,
        created_at="2026-05-12T10:00:00+00:00",
        updated_at="2026-05-12T10:00:00+00:00",
    )
    base.update(overrides)
    m = MagicMock()
    m.configure_mock(**base)
    # `name` is reserved on MagicMock; assign explicitly.
    m.name = overrides.get("name", "My Set")
    return m


def _track(track_id, spotify_id):
    m = MagicMock()
    m.configure_mock(
        track_id=track_id, position=0, added_at=_utc().isoformat(),
        spotify_id=spotify_id, isrc=None,
        length_ms=200000, origin="beatport",
    )
    m.title = track_id  # name-collision shim
    return m


def _build(repo, sp_client, user_repo, s3, now=_utc):
    return PlaylistsPublishService(
        repo=repo, spotify_client=sp_client,
        user_repo=user_repo, storage=s3,
        now=now,
    )


def test_publish_first_time_creates_then_replaces_then_persists() -> None:
    repo = MagicMock()
    repo.get.return_value = _playlist()
    repo.list_tracks.return_value = (
        [_track("t-1", "spt-1"), _track("t-2", "spt-2")], 2,
    )

    sp = MagicMock()
    sp.create_playlist.return_value = MagicMock(
        id="spt-pl-1", url="https://open.spotify.com/playlist/spt-pl-1",
    )

    user_repo = MagicMock()
    user_repo.get_spotify_id.return_value = "user-spotify-id"

    s3 = MagicMock()

    svc = _build(repo, sp, user_repo, s3)
    result = svc.publish(
        user_id="u-1", playlist_id="p-1", confirm_overwrite=False,
    )
    assert isinstance(result, PublishResult)
    assert result.spotify_playlist_id == "spt-pl-1"
    assert result.skipped == []
    sp.create_playlist.assert_called_once()
    sp.replace_tracks.assert_called_once_with(
        "spt-pl-1", ["spotify:track:spt-1", "spotify:track:spt-2"],
    )
    repo.set_publish_state.assert_called_once()


def test_publish_skips_tracks_without_spotify_id() -> None:
    repo = MagicMock()
    repo.get.return_value = _playlist()
    repo.list_tracks.return_value = (
        [_track("t-1", "spt-1"), _track("t-2", None)], 2,
    )
    sp = MagicMock()
    sp.create_playlist.return_value = MagicMock(id="spt-pl-1", url=None)
    user_repo = MagicMock()
    user_repo.get_spotify_id.return_value = "u-sp"
    s3 = MagicMock()

    svc = _build(repo, sp, user_repo, s3)
    result = svc.publish(user_id="u-1", playlist_id="p-1", confirm_overwrite=False)
    assert [s["track_id"] for s in result.skipped] == ["t-2"]
    sp.replace_tracks.assert_called_once_with(
        "spt-pl-1", ["spotify:track:spt-1"],
    )


def test_publish_empty_playlist_raises() -> None:
    repo = MagicMock()
    repo.get.return_value = _playlist(track_count=0)
    repo.list_tracks.return_value = ([], 0)
    sp = MagicMock()
    user_repo = MagicMock()
    user_repo.get_spotify_id.return_value = "u-sp"
    svc = _build(repo, sp, user_repo, MagicMock())
    with pytest.raises(NothingToPublishError):
        svc.publish(user_id="u-1", playlist_id="p-1", confirm_overwrite=False)


def test_repub_without_confirm_raises() -> None:
    repo = MagicMock()
    repo.get.return_value = _playlist(spotify_playlist_id="existing")
    svc = _build(repo, MagicMock(), MagicMock(), MagicMock())
    with pytest.raises(ConfirmOverwriteRequiredError):
        svc.publish(user_id="u-1", playlist_id="p-1", confirm_overwrite=False)


def test_repub_with_confirm_uses_update_then_replace() -> None:
    repo = MagicMock()
    repo.get.return_value = _playlist(spotify_playlist_id="existing")
    repo.list_tracks.return_value = ([_track("t-1", "spt-1")], 1)
    sp = MagicMock()
    user_repo = MagicMock()
    user_repo.get_spotify_id.return_value = "u-sp"
    svc = _build(repo, sp, user_repo, MagicMock())
    svc.publish(user_id="u-1", playlist_id="p-1", confirm_overwrite=True)
    sp.update_playlist.assert_called_once()
    sp.replace_tracks.assert_called_once()


def test_repub_orphan_falls_back_to_create() -> None:
    from collector.curation import SpotifyNotFoundError
    repo = MagicMock()
    repo.get.return_value = _playlist(spotify_playlist_id="orphan")
    repo.list_tracks.return_value = ([_track("t-1", "spt-1")], 1)
    sp = MagicMock()
    sp.update_playlist.side_effect = SpotifyNotFoundError("Spotify 404")
    sp.create_playlist.return_value = MagicMock(id="new-spt-id", url=None)
    user_repo = MagicMock()
    user_repo.get_spotify_id.return_value = "u-sp"
    svc = _build(repo, sp, user_repo, MagicMock())
    result = svc.publish(
        user_id="u-1", playlist_id="p-1", confirm_overwrite=True,
    )
    assert result.spotify_playlist_id == "new-spt-id"


def test_publish_raises_not_authorized_when_no_spotify_identity() -> None:
    from collector.curation import SpotifyNotAuthorizedError
    repo = MagicMock()
    repo.get.return_value = _playlist()
    repo.list_tracks.return_value = ([_track("t-1", "spt-1")], 1)
    sp = MagicMock()
    user_repo = MagicMock()
    user_repo.get_spotify_id.return_value = None  # no Spotify identity
    svc = _build(repo, sp, user_repo, MagicMock())
    with pytest.raises(SpotifyNotAuthorizedError):
        svc.publish(user_id="u-1", playlist_id="p-1", confirm_overwrite=False)


def test_publish_non_404_spotify_error_propagates() -> None:
    repo = MagicMock()
    repo.get.return_value = _playlist(spotify_playlist_id="existing")
    repo.list_tracks.return_value = ([_track("t-1", "spt-1")], 1)
    sp = MagicMock()
    sp.update_playlist.side_effect = SpotifyApiError("Spotify 500")
    user_repo = MagicMock()
    user_repo.get_spotify_id.return_value = "u-sp"
    svc = _build(repo, sp, user_repo, MagicMock())
    with pytest.raises(SpotifyApiError):
        svc.publish(
            user_id="u-1", playlist_id="p-1", confirm_overwrite=True,
        )


def test_publish_uploads_cover_when_present() -> None:
    repo = MagicMock()
    repo.get.return_value = _playlist(cover_s3_key="covers/u/p/1.jpg")
    repo.list_tracks.return_value = ([_track("t-1", "spt-1")], 1)
    sp = MagicMock()
    sp.create_playlist.return_value = MagicMock(id="spt-1", url=None)
    user_repo = MagicMock()
    user_repo.get_spotify_id.return_value = "u-sp"
    s3 = MagicMock()
    s3.read_cover_bytes.return_value = b"\xff\xd8jpegbytes"
    svc = _build(repo, sp, user_repo, s3)
    result = svc.publish(user_id="u-1", playlist_id="p-1", confirm_overwrite=False)
    sp.set_cover.assert_called_once_with("spt-1", b"\xff\xd8jpegbytes")
    assert result.cover_failed is False


def test_publish_cover_failure_marks_dirty() -> None:
    """When set_cover raises, set_publish_state is called with
    mark_dirty=True, and the result carries cover_failed=True."""
    repo = MagicMock()
    repo.get.return_value = _playlist(cover_s3_key="covers/u/p/1.jpg")
    repo.list_tracks.return_value = ([_track("t-1", "spt-1")], 1)
    sp = MagicMock()
    sp.create_playlist.return_value = MagicMock(id="spt-1", url=None)
    sp.set_cover.side_effect = SpotifyApiError("S3 down")
    user_repo = MagicMock()
    user_repo.get_spotify_id.return_value = "u-sp"
    s3 = MagicMock()
    s3.read_cover_bytes.return_value = b"jpeg"
    svc = _build(repo, sp, user_repo, s3)
    result = svc.publish(
        user_id="u-1", playlist_id="p-1", confirm_overwrite=False,
    )
    assert result.cover_failed is True
    repo.set_publish_state.assert_called_once()
    call_kwargs = repo.set_publish_state.call_args.kwargs
    assert call_kwargs["mark_dirty"] is True


def test_publish_404_when_not_found() -> None:
    repo = MagicMock()
    repo.get.return_value = None
    svc = _build(repo, MagicMock(), MagicMock(), MagicMock())
    with pytest.raises(PlaylistNotFoundError):
        svc.publish(user_id="u-1", playlist_id="missing", confirm_overwrite=False)

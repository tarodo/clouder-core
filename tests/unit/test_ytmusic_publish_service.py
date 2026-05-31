from dataclasses import dataclass
from datetime import datetime, timezone

import pytest

from collector.curation import (
    ConfirmOverwriteRequiredError,
    NothingToPublishError,
    PlaylistNotFoundError,
    YtmusicApiError,
    YtmusicNotFoundError,
)
from collector.curation.playlists_repository import YtmusicStatus
from collector.curation.ytmusic_publish_service import YtmusicPublishService


@dataclass
class FakePlaylist:
    id: str
    name: str
    description: str | None
    is_public: bool
    ytmusic_playlist_id: str | None = None


@dataclass
class FakeTrackRow:
    track_id: str
    title: str


class FakeRepo:
    def __init__(self, playlist, rows, statuses):
        self._playlist = playlist
        self._rows = rows
        self._statuses = statuses
        self.published_state = None

    def get(self, *, user_id, playlist_id):
        return self._playlist

    def list_tracks(self, *, user_id, playlist_id, limit, offset):
        return self._rows, len(self._rows)

    def fetch_ytmusic_status(self, track_ids):
        return self._statuses

    def set_ytmusic_publish_state(self, *, user_id, playlist_id, ytmusic_playlist_id, now):
        self.published_state = (ytmusic_playlist_id, now)
        return True


class FakeClient:
    def __init__(self, *, create_ret="PLnew", edit_raises=None):
        self.create_ret = create_ret
        self.edit_raises = edit_raises
        self.created = None
        self.edited = None
        self.added = []
        self.removed = []

    def create_playlist(self, *, name, description, privacy):
        self.created = (name, description, privacy)
        return self.create_ret

    def edit_meta(self, *, playlist_id, name, description, privacy):
        if self.edit_raises:
            raise self.edit_raises
        self.edited = (playlist_id, name, description, privacy)

    def get_existing_items(self, playlist_id):
        return [{"videoId": "old", "setVideoId": "s"}]

    def add_items(self, playlist_id, video_ids):
        self.added.append((playlist_id, list(video_ids)))

    def remove_items(self, playlist_id, items):
        self.removed.append((playlist_id, items))


def _now():
    return datetime(2026, 5, 31, tzinfo=timezone.utc)


def _matched(vid):
    return YtmusicStatus(status="matched", video_id=vid, url=f"u/{vid}", confidence=0.9)


def test_playlist_not_found():
    repo = FakeRepo(None, [], {})
    svc = YtmusicPublishService(repo=repo, ytmusic_client=FakeClient(), now=_now)
    with pytest.raises(PlaylistNotFoundError):
        svc.publish(user_id="u", playlist_id="p", confirm_overwrite=False)


def test_first_publish_creates_and_adds():
    pl = FakePlaylist(id="p", name="N", description="D", is_public=True)
    rows = [FakeTrackRow("t1", "T1"), FakeTrackRow("t2", "T2")]
    statuses = {"t1": _matched("v1"), "t2": _matched("v2")}
    client = FakeClient(create_ret="PLnew")
    repo = FakeRepo(pl, rows, statuses)
    svc = YtmusicPublishService(repo=repo, ytmusic_client=client, now=_now)
    result = svc.publish(user_id="u", playlist_id="p", confirm_overwrite=False)
    assert result.ytmusic_playlist_id == "PLnew"
    assert client.created == ("N", "D", "PUBLIC")
    assert client.added == [("PLnew", ["v1", "v2"])]
    assert result.skipped == []
    assert repo.published_state[0] == "PLnew"


def test_skips_unmatched_tracks():
    pl = FakePlaylist(id="p", name="N", description=None, is_public=False)
    rows = [FakeTrackRow("t1", "T1"), FakeTrackRow("t2", "T2")]
    statuses = {"t1": _matched("v1"), "t2": YtmusicStatus(status="not_found")}
    client = FakeClient()
    svc = YtmusicPublishService(repo=FakeRepo(pl, rows, statuses), ytmusic_client=client, now=_now)
    result = svc.publish(user_id="u", playlist_id="p", confirm_overwrite=False)
    assert client.created[2] == "PRIVATE"
    assert result.skipped == [{"track_id": "t2", "title": "T2", "reason": "no_ytmusic_match"}]
    assert client.added == [("PLnew", ["v1"])]


def test_nothing_to_publish():
    pl = FakePlaylist(id="p", name="N", description=None, is_public=True)
    rows = [FakeTrackRow("t1", "T1")]
    statuses = {"t1": YtmusicStatus(status="pending")}
    svc = YtmusicPublishService(repo=FakeRepo(pl, rows, statuses), ytmusic_client=FakeClient(), now=_now)
    with pytest.raises(NothingToPublishError):
        svc.publish(user_id="u", playlist_id="p", confirm_overwrite=False)


def test_republish_requires_confirm():
    pl = FakePlaylist(id="p", name="N", description=None, is_public=True, ytmusic_playlist_id="PLold")
    rows = [FakeTrackRow("t1", "T1")]
    statuses = {"t1": _matched("v1")}
    svc = YtmusicPublishService(repo=FakeRepo(pl, rows, statuses), ytmusic_client=FakeClient(), now=_now)
    with pytest.raises(ConfirmOverwriteRequiredError):
        svc.publish(user_id="u", playlist_id="p", confirm_overwrite=False)


def test_republish_edits_in_place():
    pl = FakePlaylist(id="p", name="N2", description="D2", is_public=True, ytmusic_playlist_id="PLold")
    rows = [FakeTrackRow("t1", "T1")]
    statuses = {"t1": _matched("v1")}
    client = FakeClient()
    repo = FakeRepo(pl, rows, statuses)
    svc = YtmusicPublishService(repo=repo, ytmusic_client=client, now=_now)
    result = svc.publish(user_id="u", playlist_id="p", confirm_overwrite=True)
    assert result.ytmusic_playlist_id == "PLold"
    assert client.edited == ("PLold", "N2", "D2", "PUBLIC")
    assert client.removed == [("PLold", [{"videoId": "old", "setVideoId": "s"}])]
    assert client.added == [("PLold", ["v1"])]


def test_orphan_recreates_when_edit_404s():
    pl = FakePlaylist(id="p", name="N", description=None, is_public=True, ytmusic_playlist_id="PLgone")
    rows = [FakeTrackRow("t1", "T1")]
    statuses = {"t1": _matched("v1")}
    client = FakeClient(create_ret="PLnew", edit_raises=YtmusicNotFoundError("gone"))
    repo = FakeRepo(pl, rows, statuses)
    svc = YtmusicPublishService(repo=repo, ytmusic_client=client, now=_now)
    result = svc.publish(user_id="u", playlist_id="p", confirm_overwrite=True)
    assert result.ytmusic_playlist_id == "PLnew"
    assert client.created is not None
    assert repo.published_state[0] == "PLnew"


def test_non_404_edit_error_propagates():
    # A generic upstream error during republish must propagate, NOT trigger a
    # silent orphan recreate.
    pl = FakePlaylist(id="p", name="N", description=None, is_public=True, ytmusic_playlist_id="PLold")
    rows = [FakeTrackRow("t1", "T1")]
    statuses = {"t1": _matched("v1")}
    client = FakeClient(edit_raises=YtmusicApiError("network timeout"))
    svc = YtmusicPublishService(repo=FakeRepo(pl, rows, statuses), ytmusic_client=client, now=_now)
    with pytest.raises(YtmusicApiError):
        svc.publish(user_id="u", playlist_id="p", confirm_overwrite=True)
    assert client.created is None  # did not recreate


def test_orphan_404_wraps_when_not_treating_as_orphan():
    pl = FakePlaylist(id="p", name="N", description=None, is_public=True, ytmusic_playlist_id="PLgone")
    rows = [FakeTrackRow("t1", "T1")]
    statuses = {"t1": _matched("v1")}
    client = FakeClient(edit_raises=YtmusicNotFoundError("gone"))
    svc = YtmusicPublishService(repo=FakeRepo(pl, rows, statuses), ytmusic_client=client, now=_now)
    with pytest.raises(YtmusicApiError):
        svc.publish(user_id="u", playlist_id="p", confirm_overwrite=True, treat_404_as_orphan=False)
    assert client.created is None

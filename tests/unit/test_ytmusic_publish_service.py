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
    cover_s3_key: str | None = None


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
    def __init__(self, *, create_ret="PLnew", edit_raises=None, cover_raises=None, existing=None):
        self.create_ret = create_ret
        self.edit_raises = edit_raises
        self.cover_raises = cover_raises
        self._existing = existing if existing is not None else [{"videoId": "old", "itemId": "i_old"}]
        self.created = None
        self.edited = None
        self.added = []
        self.removed = []
        self.cover = None

    def create_playlist(self, *, name, description, privacy):
        self.created = (name, description, privacy)
        return self.create_ret

    def set_cover(self, playlist_id, image_bytes):
        if self.cover_raises:
            raise self.cover_raises
        self.cover = (playlist_id, image_bytes)

    def edit_meta(self, *, playlist_id, name, description, privacy):
        if self.edit_raises:
            raise self.edit_raises
        self.edited = (playlist_id, name, description, privacy)

    def get_existing_items(self, playlist_id):
        return list(self._existing)

    def add_items(self, playlist_id, video_ids):
        self.added.append((playlist_id, list(video_ids)))

    def remove_items(self, playlist_id, items):
        self.removed.append((playlist_id, items))


class FakeStorage:
    def __init__(self, data=b"IMG"):
        self.data = data
        self.reads = []

    def read_cover_bytes(self, key):
        self.reads.append(key)
        return self.data


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
    # Playlists are always published PUBLIC.
    assert client.created[2] == "PUBLIC"
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
    # diff: existing "old" not desired -> remove its itemId; "v1" not present -> add.
    assert client.removed == [("PLold", ["i_old"])]
    assert client.added == [("PLold", ["v1"])]


def test_republish_unchanged_skips_track_ops():
    pl = FakePlaylist(id="p", name="N", description=None, is_public=True, ytmusic_playlist_id="PLold")
    rows = [FakeTrackRow("t1", "T1"), FakeTrackRow("t2", "T2")]
    statuses = {"t1": _matched("v1"), "t2": _matched("v2")}
    client = FakeClient(existing=[{"videoId": "v1", "itemId": "i1"}, {"videoId": "v2", "itemId": "i2"}])
    svc = YtmusicPublishService(repo=FakeRepo(pl, rows, statuses), ytmusic_client=client, now=_now)
    svc.publish(user_id="u", playlist_id="p", confirm_overwrite=True)
    # Existing == desired -> no quota-costly inserts/deletes.
    assert client.removed == []
    assert client.added == []
    assert client.edited is not None  # metadata still synced


def test_republish_incremental_diff_touches_only_delta():
    pl = FakePlaylist(id="p", name="N", description=None, is_public=True, ytmusic_playlist_id="PLold")
    rows = [FakeTrackRow("t1", "T1"), FakeTrackRow("t3", "T3")]
    statuses = {"t1": _matched("v1"), "t3": _matched("v3")}
    # existing has v1 + v2; desired is v1 + v3 -> remove v2's item, add v3.
    client = FakeClient(existing=[{"videoId": "v1", "itemId": "i1"}, {"videoId": "v2", "itemId": "i2"}])
    svc = YtmusicPublishService(repo=FakeRepo(pl, rows, statuses), ytmusic_client=client, now=_now)
    svc.publish(user_id="u", playlist_id="p", confirm_overwrite=True)
    assert client.removed == [("PLold", ["i2"])]
    assert client.added == [("PLold", ["v3"])]


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


def test_cover_uploaded_when_present():
    pl = FakePlaylist(id="p", name="N", description=None, is_public=True, cover_s3_key="covers/p.jpg")
    rows = [FakeTrackRow("t1", "T1")]
    statuses = {"t1": _matched("v1")}
    client = FakeClient()
    storage = FakeStorage(b"IMG")
    svc = YtmusicPublishService(
        repo=FakeRepo(pl, rows, statuses), ytmusic_client=client, storage=storage, now=_now
    )
    result = svc.publish(user_id="u", playlist_id="p", confirm_overwrite=False)
    assert storage.reads == ["covers/p.jpg"]
    assert client.cover == ("PLnew", b"IMG")
    assert result.cover_failed is False


def test_cover_failure_does_not_break_publish():
    pl = FakePlaylist(id="p", name="N", description=None, is_public=True, cover_s3_key="covers/p.jpg")
    rows = [FakeTrackRow("t1", "T1")]
    statuses = {"t1": _matched("v1")}
    client = FakeClient(cover_raises=RuntimeError("YouTube 400: invalid type"))
    svc = YtmusicPublishService(
        repo=FakeRepo(pl, rows, statuses), ytmusic_client=client, storage=FakeStorage(), now=_now
    )
    result = svc.publish(user_id="u", playlist_id="p", confirm_overwrite=False)
    assert result.cover_failed is True
    assert result.ytmusic_playlist_id == "PLnew"  # publish still succeeded


def test_no_cover_when_storage_absent():
    pl = FakePlaylist(id="p", name="N", description=None, is_public=True, cover_s3_key="covers/p.jpg")
    rows = [FakeTrackRow("t1", "T1")]
    statuses = {"t1": _matched("v1")}
    client = FakeClient()
    svc = YtmusicPublishService(repo=FakeRepo(pl, rows, statuses), ytmusic_client=client, now=_now)
    result = svc.publish(user_id="u", playlist_id="p", confirm_overwrite=False)
    assert client.cover is None
    assert result.cover_failed is False

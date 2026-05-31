import pytest

from collector.curation import YtmusicApiError
from collector.curation.ytmusic_user_client import YtmusicUserClient


class FakeYt:
    def __init__(self, *, create_ret="PLnew", playlist=None):
        self.create_ret = create_ret
        self.playlist = playlist or {"tracks": []}
        self.added = []
        self.removed = []
        self.edited = []

    def create_playlist(self, title, description, privacy_status=None, video_ids=None):
        return self.create_ret

    def get_playlist(self, playlist_id, limit=None):
        return self.playlist

    def add_playlist_items(self, playlist_id, videoIds, duplicates=False):
        self.added.append(list(videoIds))
        return {"status": "STATUS_SUCCEEDED"}

    def remove_playlist_items(self, playlist_id, videos):
        self.removed.append(videos)
        return {"status": "STATUS_SUCCEEDED"}

    def edit_playlist(self, playlist_id, title=None, description=None, privacyStatus=None):
        self.edited.append((title, description, privacyStatus))
        return {"status": "STATUS_SUCCEEDED"}


def test_create_playlist_returns_id():
    client = YtmusicUserClient(yt=FakeYt(create_ret="PLabc"))
    assert client.create_playlist(name="n", description="d", privacy="PUBLIC") == "PLabc"


def test_create_playlist_non_str_raises():
    client = YtmusicUserClient(yt=FakeYt(create_ret={"error": "nope"}))
    with pytest.raises(YtmusicApiError):
        client.create_playlist(name="n", description="d", privacy="PUBLIC")


def test_add_items_chunks_by_100():
    yt = FakeYt()
    client = YtmusicUserClient(yt=yt)
    client.add_items("PL", [f"v{i}" for i in range(250)])
    assert [len(c) for c in yt.added] == [100, 100, 50]


def test_get_existing_items_returns_video_setvideo_pairs():
    yt = FakeYt(playlist={"tracks": [
        {"videoId": "v1", "setVideoId": "s1"},
        {"videoId": "v2", "setVideoId": "s2"},
        {"videoId": "v3"},  # no setVideoId -> skipped
    ]})
    client = YtmusicUserClient(yt=yt)
    items = client.get_existing_items("PL")
    assert items == [
        {"videoId": "v1", "setVideoId": "s1"},
        {"videoId": "v2", "setVideoId": "s2"},
    ]


def test_remove_items_noop_when_empty():
    yt = FakeYt()
    client = YtmusicUserClient(yt=yt)
    client.remove_items("PL", [])
    assert yt.removed == []

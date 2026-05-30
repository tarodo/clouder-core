from collector.providers.ytmusic.lookup import YTMusicLookup


class FakeYT:
    def __init__(self, by_filter):
        self.by_filter = by_filter
        self.calls = []

    def search(self, query, filter, limit):  # noqa: A002 - matches ytmusicapi
        self.calls.append((query, filter, limit))
        return self.by_filter.get(filter, [])


def test_isrc_lookup_always_none():
    lookup = YTMusicLookup(client=FakeYT({}))
    assert lookup.lookup_by_isrc("GBxxx1234567") is None


def test_metadata_uses_songs_pass_first():
    fake = FakeYT({
        "songs": [
            {"videoId": "v1", "title": "Lost Track",
             "artists": [{"name": "Guri"}], "duration_seconds": 225},
        ],
    })
    lookup = YTMusicLookup(client=fake)
    refs = lookup.lookup_by_metadata("Guri", "Lost Track", 225_000, None)
    assert [r.vendor_track_id for r in refs] == ["v1"]
    assert [c[1] for c in fake.calls] == ["songs"]  # no fallback


def test_metadata_falls_back_to_videos_when_songs_empty():
    fake = FakeYT({
        "songs": [],
        "videos": [{"videoId": "v2", "title": "Edit", "artists": [{"name": "Guri"}]}],
    })
    lookup = YTMusicLookup(client=fake)
    refs = lookup.lookup_by_metadata("Guri", "Edit", None, None)
    assert [r.vendor_track_id for r in refs] == ["v2"]
    assert [c[1] for c in fake.calls] == ["songs", "videos"]


def test_metadata_skips_results_without_video_id():
    fake = FakeYT({"songs": [{"title": "no id", "artists": []}]})
    lookup = YTMusicLookup(client=fake)
    # songs pass yields no playable ref (no videoId) -> falls back to videos pass
    assert lookup.lookup_by_metadata("A", "B", None, None) == []
    assert [c[1] for c in fake.calls] == ["songs", "videos"]

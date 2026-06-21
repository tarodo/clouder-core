from __future__ import annotations

import pytest

from collector.providers.youtube.comments import (
    CommentsDisabledError,
    YouTubeCommentProvider,
)


class FakeResp:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload or {}

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"http {self.status_code}")


class FakeSession:
    def __init__(self, resp):
        self._resp = resp
        self.calls = []

    def get(self, url, params=None, timeout=None):
        self.calls.append((url, params))
        return self._resp


def _thread(cid, author, text, likes, when, avatar="http://a/x.jpg"):
    return {
        "snippet": {
            "topLevelComment": {
                "id": cid,
                "snippet": {
                    "authorDisplayName": author,
                    "authorProfileImageUrl": avatar,
                    "textDisplay": text,
                    "likeCount": likes,
                    "publishedAt": when,
                },
            }
        }
    }


def test_collect_parses_threads_in_order():
    payload = {"items": [
        _thread("c1", "Alice", "first", 5, "2025-01-02T10:00:00Z"),
        _thread("c2", "Bob", "second", 0, "2025-01-03T11:30:00Z"),
    ]}
    session = FakeSession(FakeResp(200, payload))
    provider = YouTubeCommentProvider(api_key="KEY", session=session)

    out = provider.collect("vid123", limit=100)

    assert provider.platform == "youtube"
    assert [c.external_id for c in out] == ["c1", "c2"]
    assert [c.rank for c in out] == [0, 1]
    assert out[0].author_name == "Alice"
    assert out[0].like_count == 5
    assert out[0].author_avatar_url == "http://a/x.jpg"
    assert out[0].published_at is not None and out[0].published_at.year == 2025
    # request shape
    _, params = session.calls[-1]
    assert params["videoId"] == "vid123"
    assert params["maxResults"] == 100
    assert params["part"] == "snippet"
    assert params["key"] == "KEY"


def test_collect_caps_at_limit():
    payload = {"items": [
        _thread(f"c{i}", "A", "t", 0, "2025-01-02T10:00:00Z") for i in range(10)
    ]}
    provider = YouTubeCommentProvider(api_key="K", session=FakeSession(FakeResp(200, payload)))
    out = provider.collect("v", limit=3)
    assert len(out) == 3


def test_collect_empty_items_returns_empty():
    provider = YouTubeCommentProvider(api_key="K", session=FakeSession(FakeResp(200, {"items": []})))
    assert provider.collect("v") == []


def test_collect_raises_comments_disabled_on_403():
    payload = {"error": {"errors": [{"reason": "commentsDisabled"}]}}
    provider = YouTubeCommentProvider(api_key="K", session=FakeSession(FakeResp(403, payload)))
    with pytest.raises(CommentsDisabledError):
        provider.collect("v")


def test_collect_other_403_raises_generic():
    payload = {"error": {"errors": [{"reason": "quotaExceeded"}]}}
    provider = YouTubeCommentProvider(api_key="K", session=FakeSession(FakeResp(403, payload)))
    with pytest.raises(RuntimeError):
        provider.collect("v")


def test_collect_missing_top_level_comment_does_not_crash():
    """Item with no topLevelComment must yield a blank CollectedComment, not raise."""
    payload = {"items": [{"snippet": {}}]}
    provider = YouTubeCommentProvider(api_key="K", session=FakeSession(FakeResp(200, payload)))
    out = provider.collect("v")
    assert len(out) == 1
    assert out[0].external_id == ""
    assert out[0].text == ""


class FakeYtClient:
    def __init__(self, results):
        self._results = results
        self.calls = []

    def search(self, query, filter=None, limit=None):
        self.calls.append((query, filter, limit))
        return self._results


def _video(video_id, title, artist, seconds=200):
    return {
        "videoId": video_id,
        "title": title,
        "artists": [{"name": artist}],
        "duration_seconds": seconds,
    }


def _provider_with(results, threshold=0.5):
    # session is unused by the resolver; pass a dummy.
    return YouTubeCommentProvider(
        api_key="K",
        session=object(),
        ytmusic_client=FakeYtClient(results),
        threshold=threshold,
    )


def test_resolve_returns_scored_videos_best_first():
    results = [
        _video("good1", "Lost Track", "Guri"),     # strong match
        _video("weakX", "Totally Different", "Nobody"),  # below threshold
        _video("good2", "Lost Track (Extended)", "Guri"),
    ]
    provider = _provider_with(results, threshold=0.5)
    out = provider.resolve_alternate_videos(
        artist="Guri", title="Lost Track", duration_ms=200_000, exclude_video_id="art1"
    )
    assert "good1" in out and "good2" in out
    assert "weakX" not in out
    assert out[0] == "good1"  # exact title ranks first
    # request shape
    q, flt, _ = provider._ytmusic_client.calls[-1]
    assert flt == "videos"
    assert "Guri" in q and "Lost Track" in q


def test_resolve_excludes_the_art_track_id():
    results = [_video("art1", "Lost Track", "Guri"), _video("good1", "Lost Track", "Guri")]
    provider = _provider_with(results, threshold=0.5)
    out = provider.resolve_alternate_videos(
        artist="Guri", title="Lost Track", duration_ms=200_000, exclude_video_id="art1"
    )
    assert out == ["good1"]


def test_resolve_caps_at_three():
    results = [_video(f"v{i}", "Lost Track", "Guri") for i in range(6)]
    provider = _provider_with(results, threshold=0.5)
    out = provider.resolve_alternate_videos(
        artist="Guri", title="Lost Track", duration_ms=None, exclude_video_id="art1"
    )
    assert len(out) == 3


def test_resolve_empty_when_nothing_clears_threshold():
    results = [_video("v1", "Totally Different", "Nobody")]
    provider = _provider_with(results, threshold=0.9)
    out = provider.resolve_alternate_videos(
        artist="Guri", title="Lost Track", duration_ms=None, exclude_video_id="art1"
    )
    assert out == []


def test_resolve_tolerates_malformed_results():
    provider = _provider_with(["junk", {}, {"title": "no id"}], threshold=0.1)
    out = provider.resolve_alternate_videos(
        artist="Guri", title="Lost Track", duration_ms=None, exclude_video_id="art1"
    )
    assert out == []

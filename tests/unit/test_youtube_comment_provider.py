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


def _video(video_id, title):
    # artists is the uploading channel on purpose — the matcher must ignore it.
    return {"videoId": video_id, "title": title,
            "artists": [{"name": "Some Channel"}], "duration_seconds": 200}


def _provider(results):
    return YouTubeCommentProvider(api_key="K", session=object(),
                                  ytmusic_client=FakeYtClient(results))


def test_resolve_returns_matching_videos_in_search_order():
    results = [
        _video("good1", "Lychee - Back in Time"),
        _video("bad", "Totally Different Song"),
        _video("good2", "Lychee - Back in Time (Official Video)"),
    ]
    provider = _provider(results)
    out = provider.resolve_alternate_videos(
        artist="Lychee", title="Back In Time", duration_ms=200000, exclude_video_id="art1"
    )
    assert out == ["good1", "good2"]
    q, flt, _ = provider._ytmusic_client.calls[-1]
    assert flt == "videos"
    assert q == "Lychee - Back In Time"


def test_resolve_excludes_art_track():
    results = [_video("art1", "Lychee - Back in Time"), _video("good1", "Lychee - Back in Time")]
    provider = _provider(results)
    out = provider.resolve_alternate_videos(
        artist="Lychee", title="Back In Time", duration_ms=None, exclude_video_id="art1"
    )
    assert out == ["good1"]


def test_resolve_caps_at_three():
    results = [_video(f"v{i}", "Lychee - Back in Time") for i in range(6)]
    provider = _provider(results)
    out = provider.resolve_alternate_videos(
        artist="Lychee", title="Back In Time", duration_ms=None, exclude_video_id="art1"
    )
    assert out == ["v0", "v1", "v2"]


def test_resolve_empty_when_nothing_matches():
    provider = _provider([_video("v1", "Completely Unrelated Mix 2026")])
    out = provider.resolve_alternate_videos(
        artist="Lychee", title="Back In Time", duration_ms=None, exclude_video_id="art1"
    )
    assert out == []


def test_resolve_rejects_remix_for_original():
    provider = _provider([_video("rmx", "Lychee - Back in Time (Klute Remix)")])
    out = provider.resolve_alternate_videos(
        artist="Lychee", title="Back In Time", duration_ms=None, exclude_video_id="art1"
    )
    assert out == []


def test_resolve_tolerates_malformed_results():
    provider = _provider(["junk", {}, {"title": "no id"}])
    out = provider.resolve_alternate_videos(
        artist="Lychee", title="Back In Time", duration_ms=None, exclude_video_id="art1"
    )
    assert out == []

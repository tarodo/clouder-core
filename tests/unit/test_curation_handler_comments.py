from __future__ import annotations

import json

import collector.curation_handler as ch
from collector.comments.repository import CollectionRow, CommentRow


class FakeCommentsRepo:
    def __init__(self, collection, comments):
        self._collection = collection
        self._comments = comments
        self.calls = []

    def list_comments(self, *, track_id, platform, limit):
        self.calls.append((track_id, platform, limit))
        return self._collection, self._comments


def _event(track_id="t1", qs=None):
    return {"pathParameters": {"track_id": track_id}, "queryStringParameters": qs}


def test_returns_collected_comments():
    collection = CollectionRow("col1", "t1", "youtube", "vidA", "collected", 2, None)
    comments = [CommentRow("Alice", None, "hi", 3, None, 0)]
    repo = FakeCommentsRepo(collection, comments)
    resp = ch._handle_list_track_comments(_event(qs={"limit": "5"}), repo, "u1", "corr")
    assert resp["statusCode"] == 200
    body = json.loads(resp["body"])
    assert body["status"] == "collected"
    assert body["comment_count"] == 2
    assert body["video_url"] == "https://www.youtube.com/watch?v=vidA"
    assert body["comments"][0]["author_name"] == "Alice"
    assert repo.calls == [("t1", "youtube", 5)]


def test_no_collection_returns_pending_envelope():
    repo = FakeCommentsRepo(None, [])
    resp = ch._handle_list_track_comments(_event(), repo, "u1", "corr")
    body = json.loads(resp["body"])
    assert resp["statusCode"] == 200
    assert body["status"] == "pending"
    assert body["comments"] == [] and body["video_url"] is None


def test_limit_defaults_and_caps():
    collection = CollectionRow("col1", "t1", "youtube", "vidA", "collected", 0, None)
    repo = FakeCommentsRepo(collection, [])
    ch._handle_list_track_comments(_event(qs={"limit": "999"}), repo, "u1", "corr")
    assert repo.calls[-1][2] == 100
    ch._handle_list_track_comments(_event(qs=None), repo, "u1", "corr")
    assert repo.calls[-1][2] == 5

from __future__ import annotations

import json

import collector.comments_collect_handler as worker
from collector.providers.base import CollectedComment
from collector.providers.youtube.comments import CommentsDisabledError


class FakeRepo:
    def __init__(self):
        self.stored = []

    def store_comments(self, *, collection_id, platform, comments, status, now, error=None):
        self.stored.append({"collection_id": collection_id, "status": status,
                            "count": len(comments), "error": error})


class FakeProvider:
    def __init__(self, result=None, exc=None):
        self._result = result or []
        self._exc = exc

    def collect(self, video_ref, *, limit=100):
        if self._exc:
            raise self._exc
        return self._result


def _event(*msgs):
    return {"Records": [{"body": json.dumps(m)} for m in msgs]}


def _msg(collection_id="col1", video_id="vidA"):
    return {"track_id": "t1", "platform": "youtube",
            "video_id": video_id, "collection_id": collection_id}


def _patch(monkeypatch, repo, provider):
    monkeypatch.setattr(worker, "_build_repository", lambda: repo)
    monkeypatch.setattr(worker, "get_comment_provider", lambda *a, **k: provider)
    monkeypatch.setenv("YOUTUBE_API_KEY", "K")


def test_collected_path(monkeypatch):
    repo = FakeRepo()
    provider = FakeProvider(result=[CollectedComment("c1", "A", None, "hi", 1, None, 0)])
    _patch(monkeypatch, repo, provider)
    out = worker.lambda_handler(_event(_msg()), None)
    assert out["processed"] == 1
    assert repo.stored[0]["status"] == "collected" and repo.stored[0]["count"] == 1


def test_empty_path(monkeypatch):
    repo = FakeRepo()
    _patch(monkeypatch, repo, FakeProvider(result=[]))
    worker.lambda_handler(_event(_msg()), None)
    assert repo.stored[0]["status"] == "empty"


def test_comments_disabled_path(monkeypatch):
    repo = FakeRepo()
    _patch(monkeypatch, repo, FakeProvider(exc=CommentsDisabledError("v")))
    worker.lambda_handler(_event(_msg()), None)
    assert repo.stored[0]["status"] == "disabled"


def test_generic_error_marks_failed_and_does_not_raise(monkeypatch):
    repo = FakeRepo()
    _patch(monkeypatch, repo, FakeProvider(exc=RuntimeError("network")))
    out = worker.lambda_handler(_event(_msg()), None)
    assert out["processed"] == 1
    assert repo.stored[0]["status"] == "failed"
    assert "network" in repo.stored[0]["error"]

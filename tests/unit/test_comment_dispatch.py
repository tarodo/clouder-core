from __future__ import annotations

import collector.comments.dispatch as dispatch


class FakeRepo:
    def __init__(self, start_result):
        self._start_result = start_result
        self.start_calls = []

    def start_collection(self, *, track_id, platform, video_id, now):
        self.start_calls.append((track_id, platform, video_id))
        return self._start_result


class FakeSqs:
    def __init__(self):
        self.sent = []

    def send_message(self, *, QueueUrl, MessageBody):
        self.sent.append((QueueUrl, MessageBody))


def _patch(monkeypatch, repo, sqs, queue="https://q"):
    monkeypatch.setattr(dispatch, "_build_repository", lambda: repo)
    monkeypatch.setattr(dispatch, "_build_sqs_client", lambda: sqs)
    monkeypatch.setenv("COMMENT_COLLECT_QUEUE_URL", queue)


def test_dispatch_sends_message_for_new_collection(monkeypatch):
    repo, sqs = FakeRepo("col1"), FakeSqs()
    _patch(monkeypatch, repo, sqs)
    dispatch.try_dispatch_comment_collection(track_id="t1", video_id="vidA", platform="youtube")
    assert len(sqs.sent) == 1
    assert repo.start_calls == [("t1", "youtube", "vidA")]


def test_dispatch_skips_when_already_collected(monkeypatch):
    repo, sqs = FakeRepo(None), FakeSqs()
    _patch(monkeypatch, repo, sqs)
    dispatch.try_dispatch_comment_collection(track_id="t1", video_id="vidA", platform="youtube")
    assert sqs.sent == []


def test_dispatch_noop_on_empty_video(monkeypatch):
    repo, sqs = FakeRepo("col1"), FakeSqs()
    _patch(monkeypatch, repo, sqs)
    dispatch.try_dispatch_comment_collection(track_id="t1", video_id="", platform="youtube")
    assert sqs.sent == [] and repo.start_calls == []


def test_dispatch_never_raises(monkeypatch):
    def boom():
        raise RuntimeError("db down")
    monkeypatch.setattr(dispatch, "_build_repository", boom)
    monkeypatch.setenv("COMMENT_COLLECT_QUEUE_URL", "https://q")
    # must not raise
    dispatch.try_dispatch_comment_collection(track_id="t1", video_id="vidA", platform="youtube")

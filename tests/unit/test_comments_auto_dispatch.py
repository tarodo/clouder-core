from __future__ import annotations

import pytest

import collector.comments.auto_dispatch as ad


class FakeRepo:
    def __init__(self, ids):
        self._ids = ids
        self.seen = None

    def promoted_track_ids_for_block(self, *, block_id, user_id):
        self.seen = (block_id, user_id)
        return self._ids


def test_dispatches_for_each_promoted_track(monkeypatch):
    repo = FakeRepo(["t1", "t2"])
    dispatched = []
    monkeypatch.setattr(ad, "_build_repository", lambda: repo)
    monkeypatch.setattr(
        ad, "try_dispatch_comment_collection", lambda **kw: dispatched.append(kw)
    )
    ad.try_dispatch_comments_for_triage_block(block_id="blk-1", user_id="u1")
    assert repo.seen == ("blk-1", "u1")
    assert dispatched == [
        {"track_id": "t1", "platform": "youtube"},
        {"track_id": "t2", "platform": "youtube"},
    ]


def test_no_user_id_is_noop(monkeypatch):
    called = []
    monkeypatch.setattr(
        ad, "_build_repository",
        lambda: pytest.fail("should not build repository without user_id"),
    )
    monkeypatch.setattr(
        ad, "try_dispatch_comment_collection", lambda **kw: called.append(kw)
    )
    ad.try_dispatch_comments_for_triage_block(block_id="blk-1", user_id=None)
    assert called == []


def test_never_raises(monkeypatch):
    def boom():
        raise RuntimeError("db down")

    monkeypatch.setattr(ad, "_build_repository", boom)
    # must not raise
    ad.try_dispatch_comments_for_triage_block(block_id="blk-1", user_id="u1")

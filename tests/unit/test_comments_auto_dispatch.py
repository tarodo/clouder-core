from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

import collector.comments.auto_dispatch as ad


class FakeRepo:
    def __init__(self, ids):
        self._ids = ids
        self.seen = None

    def track_ids_to_collect(self, *, block_id, user_id):
        self.seen = (block_id, user_id)
        return self._ids


def test_dispatches_for_each_track_to_collect(monkeypatch):
    repo = FakeRepo(["t1", "t2"])
    dispatched = []
    monkeypatch.setattr(ad, "_build_repository", lambda: repo)
    monkeypatch.setattr(ad, "try_dispatch_comment_collection", lambda **kw: dispatched.append(kw))
    ad.try_dispatch_comments_for_triage_block(block_id="blk-1", user_id="u1")
    assert repo.seen == ("blk-1", "u1")
    assert dispatched == [
        {"track_id": "t1", "platform": "youtube"},
        {"track_id": "t2", "platform": "youtube"},
    ]


def test_no_user_id_is_noop(monkeypatch):
    called = []
    monkeypatch.setattr(
        ad,
        "_build_repository",
        lambda: pytest.fail("should not build repository without user_id"),
    )
    monkeypatch.setattr(ad, "try_dispatch_comment_collection", lambda **kw: called.append(kw))
    ad.try_dispatch_comments_for_triage_block(block_id="blk-1", user_id=None)
    assert called == []


def test_never_raises(monkeypatch):
    def boom():
        raise RuntimeError("db down")

    monkeypatch.setattr(ad, "_build_repository", boom)
    # must not raise
    ad.try_dispatch_comments_for_triage_block(block_id="blk-1", user_id="u1")


def _add_track(was_new):
    from collector.curation.routes_categories import _handle_add_track

    repo = MagicMock()
    repo.add_track.return_value = ({"added_at": "t", "source_triage_block_id": None}, was_new)
    event = {"pathParameters": {"id": "cat-1"}, "body": '{"track_id": "trk-1"}'}
    with (
        patch("collector.curation.routes_categories.try_dispatch_for_track"),
        patch("collector.curation.routes_categories.try_dispatch_artists_for_track"),
        patch("collector.curation.routes_categories.try_dispatch_comment_collection") as dispatch,
    ):
        _handle_add_track(event, repo, "u1", "corr-1")
    return dispatch


def test_add_track_collects_comments_of_a_new_track():
    _add_track(True).assert_called_once_with(track_id="trk-1", platform="youtube")


def test_add_track_skips_comments_when_already_present():
    _add_track(False).assert_not_called()

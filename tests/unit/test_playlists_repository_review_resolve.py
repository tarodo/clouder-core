from datetime import datetime, timezone
from decimal import Decimal

from collector.curation.playlists_repository import PlaylistsRepository


class FakeTx:
    def __enter__(self):
        return "tx-1"
    def __exit__(self, *a):
        return False


class FakeDataAPI:
    def __init__(self, review_rows):
        self.review_rows = review_rows
        self.calls = []
    def execute(self, sql, params=None, transaction_id=None):
        self.calls.append((sql, params, transaction_id))
        if "FROM match_review_queue" in sql and "SELECT" in sql:
            return self.review_rows
        return []
    def transaction(self):
        return FakeTx()


def test_get_open_review_parses_candidates():
    api = FakeDataAPI([{"candidates": [{"ref": {"videoId": "v1"}, "score": 0.9}]}])
    repo = PlaylistsRepository(api)
    row = repo.get_open_review(track_id="t1", vendor="ytmusic")
    assert row is not None
    assert row.candidates[0]["ref"]["videoId"] == "v1"


def test_get_open_review_none_when_absent():
    repo = PlaylistsRepository(FakeDataAPI([]))
    assert repo.get_open_review(track_id="t1", vendor="ytmusic") is None


def test_resolve_accept_upserts_and_resolves():
    api = FakeDataAPI([])
    repo = PlaylistsRepository(api)
    now = datetime(2026, 5, 30, tzinfo=timezone.utc)
    repo.resolve_review_accept(
        clouder_track_id="t1", vendor="ytmusic", vendor_track_id="dQw4w9WgXcQ",
        payload={"videoId": "dQw4w9WgXcQ"}, now=now,
    )
    sqls = " ".join(c[0] for c in api.calls)
    assert "INSERT INTO vendor_track_map" in sqls
    assert "match_review_queue" in sqls and "'resolved'" in sqls
    txids = {c[2] for c in api.calls if c[2] is not None}
    assert txids == {"tx-1"}


def test_resolve_reject_deletes_pending_and_marks_no_match():
    api = FakeDataAPI([])
    repo = PlaylistsRepository(api)
    now = datetime(2026, 5, 30, tzinfo=timezone.utc)
    repo.resolve_review_reject(clouder_track_id="t1", vendor="ytmusic", now=now)
    sqls = [c[0] for c in api.calls]
    joined = " ".join(sqls)
    # deletes the open needs_review (pending) row...
    assert any("DELETE FROM match_review_queue" in s and "status = 'pending'" in s for s in sqls)
    # ...and idempotently inserts a no_match row via mark_no_match (ON CONFLICT DO NOTHING)
    assert "INSERT INTO match_review_queue" in joined and "'no_match'" in joined
    assert "ON CONFLICT" in joined
    # all within one transaction
    txids = {c[2] for c in api.calls if c[2] is not None}
    assert txids == {"tx-1"}


def test_get_open_review_parses_string_json_candidates():
    api = FakeDataAPI([{"candidates": '[{"ref": {"videoId": "v2"}, "score": 0.5}]'}])
    repo = PlaylistsRepository(api)
    row = repo.get_open_review(track_id="t1", vendor="ytmusic")
    assert row is not None
    assert row.candidates[0]["ref"]["videoId"] == "v2"

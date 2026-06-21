from __future__ import annotations

from datetime import datetime, timezone

from collector.comments.repository import CommentsRepository
from collector.providers.base import CollectedComment


class FakeDataAPI:
    """Returns canned rows by SQL substring; records calls; fakes a transaction."""

    def __init__(self, rows_by_marker=None):
        self.rows_by_marker = rows_by_marker or []
        self.calls = []
        self.batch_calls = []

    def execute(self, sql, params=None, transaction_id=None):
        self.calls.append((sql, params, transaction_id))
        for marker, rows in self.rows_by_marker:
            if marker in sql:
                return rows
        return []

    def batch_execute(self, sql, parameter_sets, transaction_id=None):
        sets = list(parameter_sets)
        self.batch_calls.append((sql, sets, transaction_id))

    class _Tx:
        def __enter__(self_inner):
            return "tx-1"

        def __exit__(self_inner, *a):
            return False

    def transaction(self):
        return FakeDataAPI._Tx()


NOW = datetime(2026, 6, 21, tzinfo=timezone.utc)


def test_start_collection_skips_when_already_collected_same_video():
    api = FakeDataAPI([
        ("SELECT id, external_video_id, status FROM comment_collections",
         [{"id": "col1", "external_video_id": "vidA", "status": "collected"}]),
    ])
    repo = CommentsRepository(api)
    result = repo.start_collection(track_id="t1", platform="youtube", video_id="vidA", now=NOW)
    assert result is None
    # no INSERT issued
    assert all("INSERT INTO comment_collections" not in sql for sql, *_ in api.calls)


def test_start_collection_inserts_when_new():
    api = FakeDataAPI([
        ("SELECT id, external_video_id, status FROM comment_collections", []),
        ("INSERT INTO comment_collections", [{"id": "colNEW"}]),
    ])
    repo = CommentsRepository(api)
    result = repo.start_collection(track_id="t1", platform="youtube", video_id="vidA", now=NOW)
    assert result == "colNEW"
    insert_sql, params, _ = [c for c in api.calls if "INSERT INTO comment_collections" in c[0]][0]
    assert params["t"] == "t1" and params["p"] == "youtube" and params["v"] == "vidA"


def test_start_collection_reinserts_when_video_changed():
    api = FakeDataAPI([
        ("SELECT id, external_video_id, status FROM comment_collections",
         [{"id": "col1", "external_video_id": "OLD", "status": "collected"}]),
        ("INSERT INTO comment_collections", [{"id": "col1"}]),
    ])
    repo = CommentsRepository(api)
    assert repo.start_collection(track_id="t1", platform="youtube", video_id="NEW", now=NOW) == "col1"


def test_store_comments_deletes_then_batch_inserts_and_marks_collected():
    api = FakeDataAPI()
    repo = CommentsRepository(api)
    comments = [
        CollectedComment("c1", "A", None, "hi", 2, NOW, 0),
        CollectedComment("c2", "B", "http://x", "yo", 0, None, 1),
    ]
    repo.store_comments(collection_id="col1", platform="youtube", comments=comments,
                        status="collected", now=NOW)
    assert any("DELETE FROM external_comments" in sql for sql, *_ in api.calls)
    assert len(api.batch_calls) == 1
    _, sets, _ = api.batch_calls[0]
    assert [s["eid"] for s in sets] == ["c1", "c2"]
    update_sql, params, _ = [c for c in api.calls if "UPDATE comment_collections" in c[0]][0]
    assert params["s"] == "collected" and params["n"] == 2


def test_store_comments_empty_skips_batch_and_marks_status():
    api = FakeDataAPI()
    repo = CommentsRepository(api)
    repo.store_comments(collection_id="col1", platform="youtube", comments=[],
                        status="empty", now=NOW)
    assert api.batch_calls == []
    update_sql, params, _ = [c for c in api.calls if "UPDATE comment_collections" in c[0]][0]
    assert params["s"] == "empty" and params["n"] == 0


def test_list_comments_returns_collection_and_rows():
    api = FakeDataAPI([
        ("SELECT id, track_id, platform, external_video_id, status, comment_count, collected_at",
         [{"id": "col1", "track_id": "t1", "platform": "youtube",
           "external_video_id": "vidA", "status": "collected", "comment_count": 2,
           "collected_at": None}]),
        ("FROM external_comments",
         [{"author_name": "A", "author_avatar_url": None, "text": "hi",
           "like_count": 2, "published_at": None, "rank": 0}]),
    ])
    repo = CommentsRepository(api)
    collection, comments = repo.list_comments(track_id="t1", platform="youtube", limit=5)
    assert collection is not None and collection.status == "collected"
    assert collection.external_video_id == "vidA"
    assert len(comments) == 1 and comments[0].author_name == "A"


def test_list_comments_none_when_no_collection():
    api = FakeDataAPI([])
    repo = CommentsRepository(api)
    collection, comments = repo.list_comments(track_id="t1", platform="youtube", limit=5)
    assert collection is None and comments == []


def test_store_comments_all_writes_share_transaction_id():
    """DELETE, batch INSERT, and UPDATE must all run under the same transaction."""
    api = FakeDataAPI()
    repo = CommentsRepository(api)
    comments = [CollectedComment("c1", "A", None, "hi", 1, NOW, 0)]
    repo.store_comments(collection_id="col1", platform="youtube", comments=comments,
                        status="collected", now=NOW)
    # All execute() calls that are writes (DELETE and UPDATE) must carry tx "tx-1".
    write_calls = [c for c in api.calls if "SELECT" not in c[0]]
    assert write_calls, "expected at least one non-SELECT execute call"
    for sql, params, tx_id in write_calls:
        assert tx_id == "tx-1", f"write call missing transaction_id: {sql!r}"
    # The batch insert must also carry tx "tx-1".
    assert len(api.batch_calls) == 1
    _, _, batch_tx_id = api.batch_calls[0]
    assert batch_tx_id == "tx-1", "batch_execute call missing transaction_id"

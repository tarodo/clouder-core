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


# ---------------------------------------------------------------------------
# list_comments_for_tracks
# ---------------------------------------------------------------------------

def _coll_row(track_id: str, coll_id: str) -> dict:
    return {
        "id": coll_id,
        "track_id": track_id,
        "platform": "youtube",
        "external_video_id": f"vid-{track_id}",
        "status": "collected",
        "comment_count": 2,
        "collected_at": None,
    }


def _comment_row(collection_id: str, rank: int) -> dict:
    return {
        "author_name": f"Author-{rank}",
        "author_avatar_url": None,
        "text": f"comment {rank}",
        "like_count": rank,
        "published_at": None,
        "rank": rank,
        "collection_id": collection_id,
    }


def test_list_comments_for_tracks_empty_input_returns_empty_dict():
    """Empty track_ids → {} with no SQL calls."""
    api = FakeDataAPI()
    repo = CommentsRepository(api)
    result = repo.list_comments_for_tracks(track_ids=[], platform="youtube")
    assert result == {}
    assert api.calls == []


def test_list_comments_for_tracks_two_tracks_grouping():
    """Two tracks: t1 has 2 comments, t2 has a collection but 0 comments."""
    col1 = _coll_row("t1", "col-1")
    col2 = _coll_row("t2", "col-2")
    c1 = _comment_row("col-1", 0)
    c2 = _comment_row("col-1", 1)

    api = FakeDataAPI([
        # collections query is identified by the SELECT with comment_collections + IN
        ("FROM comment_collections", [col1, col2]),
        # comments query is identified by collection_id IN
        ("FROM external_comments", [c1, c2]),
    ])
    repo = CommentsRepository(api)
    result = repo.list_comments_for_tracks(track_ids=["t1", "t2"], platform="youtube")

    # t1 has a collection and 2 comments ordered by rank
    assert "t1" in result
    t1_col, t1_comments = result["t1"]
    assert t1_col is not None
    assert t1_col.track_id == "t1"
    assert [c.rank for c in t1_comments] == [0, 1]

    # t2 has a collection row but no comments
    assert "t2" in result
    t2_col, t2_comments = result["t2"]
    assert t2_col is not None
    assert t2_col.track_id == "t2"
    assert t2_comments == []


def test_list_comments_for_tracks_no_collection_track_absent():
    """Track with no collection row is absent from the result dict."""
    col1 = _coll_row("t1", "col-1")
    c1 = _comment_row("col-1", 0)

    api = FakeDataAPI([
        ("FROM comment_collections", [col1]),   # only t1 has a collection
        ("FROM external_comments", [c1]),
    ])
    repo = CommentsRepository(api)
    result = repo.list_comments_for_tracks(track_ids=["t1", "t2-missing"], platform="youtube")

    assert "t1" in result
    assert "t2-missing" not in result


def test_list_comments_for_tracks_limit_per_track():
    """limit_per_track caps the returned comment list."""
    col1 = _coll_row("t1", "col-1")
    comments = [_comment_row("col-1", r) for r in range(5)]

    api = FakeDataAPI([
        ("FROM comment_collections", [col1]),
        ("FROM external_comments", comments),
    ])
    repo = CommentsRepository(api)
    result = repo.list_comments_for_tracks(track_ids=["t1"], platform="youtube", limit_per_track=3)

    _, t1_comments = result["t1"]
    assert len(t1_comments) == 3
    assert [c.rank for c in t1_comments] == [0, 1, 2]


def test_list_comments_for_tracks_in_clause_params():
    """The params dict contains track-id placeholders t0, t1, ... and platform."""
    api = FakeDataAPI([
        ("FROM comment_collections", []),
    ])
    repo = CommentsRepository(api)
    repo.list_comments_for_tracks(track_ids=["track-A", "track-B"], platform="youtube")

    coll_call = next(
        (sql, params) for sql, params, _ in api.calls if "comment_collections" in sql
    )
    _, params = coll_call
    assert params["t0"] == "track-A"
    assert params["t1"] == "track-B"
    assert params["p"] == "youtube"


def test_list_comments_for_tracks_query2_collection_id_params():
    """Query 2 (external_comments) binds c0, c1, ... to the found collection ids.

    The FakeDataAPI routes by SQL substring and ignores params, so a
    placeholder/param mismatch on this second query would be invisible without
    this assertion (it only surfaces against a real DB)."""
    api = FakeDataAPI([
        ("FROM comment_collections", [_coll_row("t1", "col-1"), _coll_row("t2", "col-2")]),
        ("FROM external_comments", [_comment_row("col-1", 0)]),
    ])
    repo = CommentsRepository(api)
    repo.list_comments_for_tracks(track_ids=["t1", "t2"], platform="youtube")

    comments_call = next(
        (sql, params) for sql, params, _ in api.calls if "external_comments" in sql
    )
    _, params = comments_call
    assert params["c0"] == "col-1"
    assert params["c1"] == "col-2"


def test_list_comments_for_tracks_no_collections_skips_second_query():
    """If query 1 returns no collections, query 2 (external_comments) is never issued."""
    api = FakeDataAPI([
        ("FROM comment_collections", []),
    ])
    repo = CommentsRepository(api)
    result = repo.list_comments_for_tracks(track_ids=["t1"], platform="youtube")

    assert result == {}
    assert all("external_comments" not in sql for sql, *_ in api.calls)


# ---------------------------------------------------------------------------
# fetch_track_meta
# ---------------------------------------------------------------------------

def test_fetch_track_meta_maps_rows():
    api = FakeDataAPI([
        ("FROM clouder_tracks t", [
            {"track_id": "t1", "title": "Lost Track",
             "length_ms": 225000, "artist_names": "Guri, Eider"},
        ]),
    ])
    repo = CommentsRepository(api)
    meta = repo.fetch_track_meta(["t1"])
    assert "t1" in meta
    assert meta["t1"].title == "Lost Track"
    assert meta["t1"].artist == "Guri, Eider"
    assert meta["t1"].duration_ms == 225000


def test_fetch_track_meta_empty_input():
    repo = CommentsRepository(FakeDataAPI([]))
    assert repo.fetch_track_meta([]) == {}


def test_fetch_track_meta_maps_null_duration():
    api = FakeDataAPI([
        ("FROM clouder_tracks t", [
            {"track_id": "t1", "title": "Solo", "length_ms": None, "artist_names": ""},
        ]),
    ])
    repo = CommentsRepository(api)
    meta = repo.fetch_track_meta(["t1"])["t1"]
    assert meta.duration_ms is None and meta.artist == ""


# ---------------------------------------------------------------------------
# store_comments with external_video_id
# ---------------------------------------------------------------------------

def test_store_comments_updates_external_video_id_when_provided():
    api = FakeDataAPI()
    repo = CommentsRepository(api)
    repo.store_comments(
        collection_id="col1", platform="youtube", comments=[],
        status="collected", now=NOW, external_video_id="alt-vid",
    )
    update_sql, params = [c for c in api.calls if "UPDATE comment_collections" in c[0]][:1][0][:2]
    assert "external_video_id = :evid" in update_sql
    assert params["evid"] == "alt-vid"


def test_store_comments_omits_external_video_id_when_not_provided():
    api = FakeDataAPI()
    repo = CommentsRepository(api)
    repo.store_comments(
        collection_id="col1", platform="youtube", comments=[],
        status="empty", now=NOW,
    )
    update_sql, params = [c for c in api.calls if "UPDATE comment_collections" in c[0]][:1][0][:2]
    assert "external_video_id" not in update_sql
    assert "evid" not in params


def test_start_collection_empty_seed_skips_when_already_collected():
    api = FakeDataAPI([
        ("SELECT id, external_video_id, status FROM comment_collections",
         [{"id": "colOLD", "external_video_id": "vidOLD", "status": "collected"}]),
        ("INSERT INTO comment_collections", [{"id": "colNEW"}]),
    ])
    repo = CommentsRepository(api)
    result = repo.start_collection(track_id="t1", platform="youtube", video_id="", now=NOW)
    assert result is None
    assert not any("INSERT INTO comment_collections" in c[0] for c in api.calls)


def test_start_collection_empty_seed_inserts_when_not_collected():
    api = FakeDataAPI([
        ("SELECT id, external_video_id, status FROM comment_collections", []),
        ("INSERT INTO comment_collections", [{"id": "colNEW"}]),
    ])
    repo = CommentsRepository(api)
    result = repo.start_collection(track_id="t1", platform="youtube", video_id="", now=NOW)
    assert result == "colNEW"


def test_promoted_track_ids_for_block():
    api = FakeDataAPI([
        ("FROM category_tracks ct", [{"track_id": "t1"}, {"track_id": "t2"}]),
    ])
    repo = CommentsRepository(api)
    out = repo.promoted_track_ids_for_block(block_id="blk-1", user_id="u1")
    assert out == ["t1", "t2"]
    sql, params, _ = api.calls[0]
    assert "source_triage_block_id = :block_id" in sql
    assert "c.user_id = :user_id" in sql
    assert params == {"block_id": "blk-1", "user_id": "u1"}

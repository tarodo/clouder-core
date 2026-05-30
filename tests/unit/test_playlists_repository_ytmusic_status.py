from collector.curation.playlists_repository import PlaylistsRepository


class FakeDataAPI:
    def __init__(self, rows_by_marker):
        # rows_by_marker: list of (sql_substring, rows) checked in order
        self.rows_by_marker = rows_by_marker
        self.calls = []

    def execute(self, sql, params=None, transaction_id=None):
        self.calls.append((sql, params))
        for marker, rows in self.rows_by_marker:
            if marker in sql:
                return rows
        return []


def test_fetch_unmatched_match_inputs_filters_and_joins():
    api = FakeDataAPI([
        ("FROM clouder_tracks t", [
            {"track_id": "t1", "title": "Lost Track", "isrc": "GB123",
             "length_ms": 225000, "artist_names": "Guri, Eider",
             "album_title": "Lost EP"},
        ]),
    ])
    repo = PlaylistsRepository(api)
    inputs = repo.fetch_unmatched_match_inputs(track_ids=["t1", "t2"], vendor="ytmusic")
    assert len(inputs) == 1
    inp = inputs[0]
    assert inp.track_id == "t1"
    assert inp.artist == "Guri, Eider"
    assert inp.title == "Lost Track"
    assert inp.isrc == "GB123"
    assert inp.duration_ms == 225000
    assert inp.album == "Lost EP"
    sql, params = api.calls[-1]
    assert params["vendor"] == "ytmusic"
    assert params["t0"] == "t1" and params["t1"] == "t2"


def test_fetch_unmatched_match_inputs_empty_returns_empty():
    repo = PlaylistsRepository(FakeDataAPI([]))
    assert repo.fetch_unmatched_match_inputs(track_ids=[], vendor="ytmusic") == []


def test_fetch_unmatched_excludes_already_attempted_in_sql():
    api = FakeDataAPI([("FROM clouder_tracks t", [])])
    repo = PlaylistsRepository(api)
    repo.fetch_unmatched_match_inputs(track_ids=["t1"], vendor="ytmusic")
    sql, _ = api.calls[-1]
    # must anti-join BOTH vendor_track_map and match_review_queue
    assert "vendor_track_map" in sql and "vtm.clouder_track_id IS NULL" in sql
    assert "match_review_queue" in sql and "mrq.clouder_track_id IS NULL" in sql


def test_fetch_unmatched_maps_null_fields():
    api = FakeDataAPI([("FROM clouder_tracks t", [
        {"track_id": "t1", "title": "Solo", "isrc": None,
         "length_ms": None, "artist_names": "", "album_title": None},
    ])])
    repo = PlaylistsRepository(api)
    inp = repo.fetch_unmatched_match_inputs(track_ids=["t1"], vendor="ytmusic")[0]
    assert inp.isrc is None
    assert inp.duration_ms is None
    assert inp.album is None
    assert inp.artist == ""


def test_fetch_unmatched_maps_multiple_rows():
    api = FakeDataAPI([("FROM clouder_tracks t", [
        {"track_id": "t1", "title": "A", "isrc": "X1", "length_ms": 1000,
         "artist_names": "Guri", "album_title": "AlbA"},
        {"track_id": "t2", "title": "B", "isrc": "X2", "length_ms": 2000,
         "artist_names": "Eider", "album_title": "AlbB"},
    ])])
    repo = PlaylistsRepository(api)
    inputs = repo.fetch_unmatched_match_inputs(track_ids=["t1", "t2"], vendor="ytmusic")
    assert [i.track_id for i in inputs] == ["t1", "t2"]
    assert [i.duration_ms for i in inputs] == [1000, 2000]


def test_fetch_ytmusic_status_derives_all_states():
    from collector.curation.playlists_repository import PlaylistsRepository

    api = FakeDataAPI([
        ("FROM vendor_track_map", [
            {"clouder_track_id": "t_matched", "vendor_track_id": "vid1",
             "confidence": "0.970"},
        ]),
        ("FROM match_review_queue", [
            {"clouder_track_id": "t_review", "status": "pending"},
            {"clouder_track_id": "t_none", "status": "no_match"},
        ]),
    ])
    repo = PlaylistsRepository(api)
    status = repo.fetch_ytmusic_status(["t_matched", "t_review", "t_none", "t_pending"])

    assert status["t_matched"].status == "matched"
    assert status["t_matched"].video_id == "vid1"
    assert status["t_matched"].url == "https://music.youtube.com/watch?v=vid1"
    assert abs(status["t_matched"].confidence - 0.97) < 1e-6
    assert status["t_review"].status == "needs_review"
    assert status["t_none"].status == "not_found"
    assert status["t_pending"].status == "pending"


def test_fetch_ytmusic_status_empty_returns_empty():
    from collector.curation.playlists_repository import PlaylistsRepository
    repo = PlaylistsRepository(FakeDataAPI([]))
    assert repo.fetch_ytmusic_status([]) == {}


def test_fetch_ytmusic_status_pending_wins_over_no_match():
    from collector.curation.playlists_repository import PlaylistsRepository
    # both rows present for the same track, in either DB order
    api = FakeDataAPI([
        ("FROM vendor_track_map", []),
        ("FROM match_review_queue", [
            {"clouder_track_id": "t1", "status": "no_match"},
            {"clouder_track_id": "t1", "status": "pending"},
        ]),
    ])
    repo = PlaylistsRepository(api)
    status = repo.fetch_ytmusic_status(["t1"])
    assert status["t1"].status == "needs_review"

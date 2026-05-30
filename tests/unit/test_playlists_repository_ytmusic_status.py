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

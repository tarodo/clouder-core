from datetime import datetime, timezone

from collector.curation.playlists_repository import PlaylistsRepository, _row


class FakeDataApi:
    def __init__(self, rows):
        self._rows = rows
        self.calls = []

    def execute(self, sql, params=None):
        self.calls.append((sql, params))
        return self._rows


def test_row_maps_ytmusic_columns():
    raw = {
        "id": "p1", "user_id": "u1", "name": "n", "normalized_name": "n",
        "description": None, "is_public": True, "cover_s3_key": None,
        "cover_uploaded_at": None, "spotify_playlist_id": None,
        "last_published_at": None, "needs_republish": False,
        "status": "active", "created_at": "t", "updated_at": "t",
        "track_count": 0,
        "ytmusic_playlist_id": "PLabc",
        "ytmusic_last_published_at": "2026-05-31T00:00:00+00:00",
        "ytmusic_needs_republish": True,
    }
    row = _row(raw)
    assert row.ytmusic_playlist_id == "PLabc"
    assert row.ytmusic_last_published_at == "2026-05-31T00:00:00+00:00"
    assert row.ytmusic_needs_republish is True


def test_set_ytmusic_publish_state_writes_columns():
    fake = FakeDataApi(rows=[{"id": "p1"}])
    repo = PlaylistsRepository(data_api=fake)
    now = datetime(2026, 5, 31, tzinfo=timezone.utc)
    ok = repo.set_ytmusic_publish_state(
        user_id="u1", playlist_id="p1",
        ytmusic_playlist_id="PLabc", now=now,
    )
    assert ok is True
    sql, params = fake.calls[-1]
    assert "ytmusic_playlist_id = :ytmusic_playlist_id" in sql
    assert "ytmusic_needs_republish = FALSE" in sql
    assert params["ytmusic_playlist_id"] == "PLabc"
    assert params["id"] == "p1"

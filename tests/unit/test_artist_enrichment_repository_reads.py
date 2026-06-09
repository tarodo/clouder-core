from collector.artist_enrichment.repository import ArtistEnrichmentRepository


class FakeDataAPI:
    def __init__(self, responses=None):
        self.calls = []
        self._responses = list(responses or [])

    def execute(self, sql, params=None):
        self.calls.append((sql, dict(params or {})))
        return self._responses.pop(0) if self._responses else []


def test_upsert_user_artist_pref_rejects_bad_status():
    repo = ArtistEnrichmentRepository(FakeDataAPI())
    import pytest
    with pytest.raises(ValueError):
        repo.upsert_user_artist_pref(user_id="u", artist_id="a", status="bogus")


def test_upsert_user_artist_pref_writes_prefs_table():
    api = FakeDataAPI()
    repo = ArtistEnrichmentRepository(api)
    repo.upsert_user_artist_pref(user_id="u", artist_id="a", status="liked")
    sql, params = api.calls[-1]
    assert "clouder_user_artist_prefs" in sql
    assert params["status"] == "liked" and params["artist_id"] == "a"


def test_get_artist_info_for_user_strips_admin_fields():
    api = FakeDataAPI(responses=[[{"merged": {"artist_name": "ANNA", "summary": "x", "provenance": {"a": 1}, "cost_usd": 9}, "my_preference": "liked"}]])
    repo = ArtistEnrichmentRepository(api)
    out = repo.get_artist_info_for_user("a", user_id="u")
    assert out["artist_name"] == "ANNA"
    assert "provenance" not in out and "cost_usd" not in out
    assert out["my_preference"] == "liked"


def test_list_artists_counts_tracks_via_track_artists():
    api = FakeDataAPI(responses=[
        [{"id": "a", "name": "ANNA", "status": "completed", "tagline": None, "country": "Brazil",
          "active_since": 2008, "primary_styles": ["techno"], "artist_type": "solo",
          "ai_content": "none_detected", "updated_at": None, "dominant_style": "techno",
          "track_count": 12, "my_preference": None}],
        [{"c": 1}],
    ])
    repo = ArtistEnrichmentRepository(api)
    items, total = repo.list_artists(style=None, q=None, sort="name", page=1, limit=50, user_id="u", my="all")
    # the list query must count tracks via the many-to-many join, not albums
    list_sql = api.calls[0][0]
    assert "clouder_track_artists" in list_sql
    assert "clouder_artist_info" in list_sql
    assert items[0]["info"]["active_since"] == 2008
    assert items[0]["info"]["artist_type"] == "solo"
    assert "founded_year" not in items[0]["info"]
    assert total == 1


def test_list_backlog_joins_track_artists():
    api = FakeDataAPI(responses=[
        [{"id": "a", "name": "ANNA", "style": "techno", "track_count": 5, "status": "none", "last_attempted_at": None}],
        [{"c": 1}],
    ])
    repo = ArtistEnrichmentRepository(api)
    items, cursor, total = repo.list_backlog(style=None, status="none", cursor=None, limit=100)
    assert "clouder_track_artists" in api.calls[0][0]
    assert items[0]["id"] == "a" and total == 1


def test_get_artists_by_ids_one_query_returns_name_map():
    captured = []

    class FakeDataAPI:
        def execute(self, sql, params=None, transaction_id=None):
            captured.append((sql, params))
            return [
                {"id": "a1", "name": "Artist One"},
                {"id": "a2", "name": "Artist Two"},
            ]

    from collector.artist_enrichment.repository import ArtistEnrichmentRepository
    repo = ArtistEnrichmentRepository(data_api=FakeDataAPI())
    result = repo.get_artists_by_ids(["a1", "a2"])
    assert result == {"a1": "Artist One", "a2": "Artist Two"}
    assert len(captured) == 1  # single round-trip, not one per id
    assert ":t0" in captured[0][0] and ":t1" in captured[0][0]


def test_get_artists_by_ids_empty_input_no_query():
    class FakeDataAPI:
        def execute(self, *a, **k):  # pragma: no cover - must not be called
            raise AssertionError("should not query for empty input")

    from collector.artist_enrichment.repository import ArtistEnrichmentRepository
    assert ArtistEnrichmentRepository(data_api=FakeDataAPI()).get_artists_by_ids([]) == {}

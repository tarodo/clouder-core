from collector.artist_enrichment.auto_repository import AutoEnrichRepository


class FakeDataAPI:
    def __init__(self, responses=None):
        self.calls = []
        self._responses = list(responses or [])

    def execute(self, sql, params=None):
        self.calls.append((sql, dict(params or {})))
        return self._responses.pop(0) if self._responses else []


def test_get_config_uses_auto_enrich_config_table():
    api = FakeDataAPI(responses=[[{"kind": "artists", "enabled": True, "vendors": ["openai"],
                                   "models": {"openai": "m"}, "prompt_slug": "artist_v1",
                                   "prompt_version": "v1", "merge_vendor": "deepseek", "merge_model": "d"}]])
    repo = AutoEnrichRepository(api)
    cfg = repo.get_config("artists")
    assert "auto_enrich_config" in api.calls[0][0]
    assert api.calls[0][1]["kind"] == "artists"
    assert cfg["enabled"] is True and cfg["vendors"] == ["openai"]


def test_artist_ids_for_track_returns_all_roles():
    api = FakeDataAPI(responses=[[{"artist_id": "a1"}, {"artist_id": "a2"}, {"artist_id": "a3"}]])
    repo = AutoEnrichRepository(api)
    ids = repo.artist_ids_for_track("t1")
    sql = api.calls[0][0]
    assert "clouder_track_artists" in sql
    assert "role" not in sql.lower().split("where")[1] if "where" in sql.lower() else True  # no role filter
    assert ids == ["a1", "a2", "a3"]


def test_artist_ids_for_triage_block_all_roles():
    api = FakeDataAPI(responses=[[{"artist_id": "a1"}, {"artist_id": "a2"}]])
    repo = AutoEnrichRepository(api)
    ids = repo.artist_ids_for_triage_block("b1")
    assert "clouder_track_artists" in api.calls[0][0]
    assert "category_tracks" in api.calls[0][0]
    assert ids == ["a1", "a2"]


def test_mark_outcome_flips_queued_state():
    api = FakeDataAPI()
    repo = AutoEnrichRepository(api)
    repo.mark_auto_enrich_outcome("a1", True)
    sql, params = api.calls[-1]
    assert "artist_auto_enrich_state" in sql
    assert params["new_status"] == "completed"


def test_claim_artists_skips_when_info_exists():
    # reclaim UPDATE returns nothing, INSERT returns nothing (info exists) → not claimed
    api = FakeDataAPI(responses=[[], []])
    repo = AutoEnrichRepository(api)
    claimed = repo.claim_artists(["a1"])
    assert claimed == []
    assert "artist_auto_enrich_state" in api.calls[0][0]
    assert "clouder_artist_info" in api.calls[1][0]

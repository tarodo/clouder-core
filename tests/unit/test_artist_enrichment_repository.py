from decimal import Decimal

from collector.artist_enrichment.repository import ArtistEnrichmentRepository, RunSpec
from collector.artist_enrichment.schemas import AIContentStatus, ArtistInfo
from collector.label_enrichment.vendors.base import VendorResponse


class FakeDataAPI:
    """Records execute() calls; returns queued responses FIFO (default [])."""

    def __init__(self, responses=None):
        self.calls = []
        self._responses = list(responses or [])

    def execute(self, sql, params=None):
        self.calls.append((sql, dict(params or {})))
        return self._responses.pop(0) if self._responses else []

    def last(self):
        return self.calls[-1]


def _info(**over):
    base = dict(artist_name="ANNA", ai_reasoning="x", summary="x", confidence=0.9)
    base.update(over)
    return ArtistInfo(**base)


def test_create_run_sets_cells_total():
    api = FakeDataAPI()
    repo = ArtistEnrichmentRepository(api)
    spec = RunSpec(
        prompt_slug="artist_v1", prompt_version="v1",
        vendors=["openai", "gemini"], models={"openai": "m", "gemini": "m"},
        merge_vendor="deepseek", merge_model="d", requested_artists=3, source="auto",
    )
    run_id = repo.create_run(spec)
    assert run_id
    sql, params = api.last()
    assert "clouder_artist_enrichment_runs" in sql
    assert params["requested_artists"] == 3
    assert params["cells_total"] == 6  # 3 artists * 2 vendors
    assert params["source"] == "auto"


def test_insert_cell_marks_error_when_no_parse():
    api = FakeDataAPI()
    repo = ArtistEnrichmentRepository(api)
    resp = VendorResponse(parsed=None, raw={}, citations=[], usage={"cost_usd": 0.0},
                          latency_ms=5, model="m", error="boom")
    repo.insert_cell(run_id="r", artist_id="a", vendor="openai", response=resp)
    sql, params = api.last()
    assert "clouder_artist_enrichment_cells" in sql
    assert params["status"] == "error"
    assert params["error"] == {"message": "boom"}


def test_upsert_artist_info_denormalizes_artist_columns():
    api = FakeDataAPI()
    repo = ArtistEnrichmentRepository(api)
    info = _info(artist_type="solo", country="Brazil", active_since=2008,
                 tagline="Brazilian techno", primary_styles=["techno", "house"],
                 ai_content=AIContentStatus.NONE_DETECTED, status="active", confidence=0.91)
    repo.upsert_artist_info(artist_id="a", last_run_id="r", prompt_slug="artist_v1",
                            prompt_version="v1", merged=info, provenance={"country": "x"})
    sql, params = api.last()
    assert "clouder_artist_info" in sql
    assert params["artist_type"] == "solo"
    assert params["country"] == "Brazil"
    assert params["active_since"] == 2008
    assert params["tagline"] == "Brazilian techno"
    assert params["ai_content"] == "none_detected"
    assert params["ai_confidence"] == Decimal("0.91")
    assert params["primary_styles"] == '{"techno","house"}'
    # no label-only columns leaked
    assert "founded_year" not in params and "activity" not in params


def test_project_ai_suspected_sets_flag_above_threshold():
    api = FakeDataAPI()
    repo = ArtistEnrichmentRepository(api)
    info = _info(ai_content=AIContentStatus.CONFIRMED, confidence=0.95)
    repo.project_ai_suspected("a", info, threshold=0.7)
    sql, params = api.last()
    assert "UPDATE clouder_artists" in sql
    assert params["value"] is True
    assert params["id"] == "a"


def test_project_ai_suspected_noop_below_threshold():
    api = FakeDataAPI()
    repo = ArtistEnrichmentRepository(api)
    info = _info(ai_content=AIContentStatus.CONFIRMED, confidence=0.5)
    repo.project_ai_suspected("a", info, threshold=0.7)
    assert api.calls == []  # nothing executed


def test_derive_artist_context_reads_style_tracks_labels():
    api = FakeDataAPI(responses=[
        [{"style_name": "techno", "cnt": 9}],                       # style query
        [{"title": "Hidden Beauties"}, {"title": "Forsaken"}],       # tracks query
        [{"label_name": "Drumcode"}, {"label_name": "Kompakt"}],     # labels query
    ])
    repo = ArtistEnrichmentRepository(api)
    ctx = repo.derive_artist_context("a")
    assert ctx.style == "techno"
    assert ctx.sample_tracks == ["Hidden Beauties", "Forsaken"]
    assert ctx.known_labels == ["Drumcode", "Kompakt"]


def test_derive_artist_context_defaults_style_to_music_when_no_tracks():
    api = FakeDataAPI(responses=[[], [], []])
    repo = ArtistEnrichmentRepository(api)
    ctx = repo.derive_artist_context("a")
    assert ctx.style == "music"
    assert ctx.sample_tracks == []
    assert ctx.known_labels == []


def test_upsert_artist_by_name_returns_existing_id():
    api = FakeDataAPI(responses=[[{"id": "existing-1"}]])
    repo = ArtistEnrichmentRepository(api)
    assert repo.upsert_artist_by_name("ANNA") == "existing-1"
    assert len(api.calls) == 1  # only the SELECT, no INSERT

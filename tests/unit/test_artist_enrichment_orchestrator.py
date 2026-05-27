from collector.artist_enrichment.orchestrator import enrich_artist_for_run, run_vendors_parallel
from collector.artist_enrichment.prompts import get_prompt, load_builtin_prompts
from collector.artist_enrichment.repository import ArtistContext
from collector.artist_enrichment.schemas import ArtistInfo
from collector.label_enrichment.vendors.base import VendorResponse


class StubAdapter:
    def __init__(self, name):
        self.name = name
        self.default_model = "stub-model"
        self.supports_web_search = True
        self.seen_user = None

    def run(self, *, system, user, schema, model=None):
        self.seen_user = user
        parsed = schema.model_validate(
            {"artist_name": "ANNA", "ai_reasoning": "x", "summary": "x", "confidence": 0.8}
        )
        return VendorResponse(parsed=parsed, raw={}, citations=["u"],
                              usage={"cost_usd": 0.001}, latency_ms=3,
                              model=model or self.default_model, error=None)


class FakeRepo:
    def __init__(self):
        self.cells = []
        self.upserted = None
        self.projected = None
        self.counters = None
        self.running = None

    def derive_artist_context(self, artist_id):
        return ArtistContext(style="techno", sample_tracks=["Hidden Beauties"], known_labels=["Drumcode"])

    def mark_run_running(self, run_id):
        self.running = run_id

    def insert_cell(self, *, run_id, artist_id, vendor, response):
        self.cells.append((vendor, response.error))

    def upsert_artist_info(self, *, artist_id, last_run_id, prompt_slug, prompt_version, merged, provenance):
        self.upserted = (artist_id, merged)

    def project_ai_suspected(self, artist_id, merged, threshold):
        self.projected = artist_id

    def increment_run_counters(self, *, run_id, ok_delta, error_delta, cost_delta):
        self.counters = (ok_delta, error_delta)


class FakeMergeClient:
    pass  # single-source path skips DeepSeek; multi-source uses it (mocked elsewhere)


def test_enrich_artist_for_run_persists_and_projects():
    load_builtin_prompts()
    prompt = get_prompt("artist_v1")
    repo = FakeRepo()
    adapters = [StubAdapter("openai")]
    outcomes = []

    enrich_artist_for_run(
        run_id="r", artist_id="a", artist_name="ANNA",
        adapters=adapters, merge_client=FakeMergeClient(), merge_model="d",
        prompt=prompt, repository=repo, ai_flag_threshold=0.7,
        on_outcome=lambda aid, ok: outcomes.append((aid, ok)),
    )

    assert repo.running == "r"
    assert repo.cells == [("openai", None)]
    assert isinstance(repo.upserted[1], ArtistInfo)
    assert repo.projected == "a"
    assert repo.counters == (1, 0)
    assert outcomes == [("a", True)]
    # disambiguation context flowed into the rendered prompt
    assert "Hidden Beauties" in adapters[0].seen_user
    assert "Drumcode" in adapters[0].seen_user

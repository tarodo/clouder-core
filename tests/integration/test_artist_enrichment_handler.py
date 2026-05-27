import json

from collector import artist_enrichment_handler as handler_mod
from collector.artist_enrichment.repository import ArtistContext


class FakeRepo:
    def __init__(self):
        self.upserted = None
        self.projected = None
        self.counters = None

    def get_run(self, run_id):
        return {"vendors": ["openai"], "models": {"openai": "m"},
                "prompt_slug": "artist_v1", "merge_model": "deepseek-v4-flash"}

    def derive_artist_context(self, artist_id):
        return ArtistContext(style="techno", sample_tracks=["Hidden Beauties"], known_labels=["Drumcode"])

    def mark_run_running(self, run_id): pass
    def insert_cell(self, **kw): pass
    def upsert_artist_info(self, **kw): self.upserted = kw["artist_id"]
    def project_ai_suspected(self, artist_id, merged, threshold): self.projected = artist_id
    def increment_run_counters(self, **kw): self.counters = kw


class FakeAutoRepo:
    def __init__(self): self.outcomes = []
    def mark_auto_enrich_outcome(self, artist_id, success): self.outcomes.append((artist_id, success))


def test_handler_enriches_one_artist(monkeypatch):
    repo, auto = FakeRepo(), FakeAutoRepo()
    monkeypatch.setattr(handler_mod, "_build_clients", lambda: (repo, auto))

    class _Settings:
        gemini_api_key = openai_api_key = tavily_api_key = deepseek_api_key = "k"
        request_timeout_s = 30.0
        ai_flag_confidence_threshold = 0.7
    monkeypatch.setattr(handler_mod, "get_artist_enrichment_worker_settings", lambda: _Settings(), raising=False)
    monkeypatch.setattr(handler_mod, "_build_merge_client", lambda *a, **k: object())

    # Stub the vendor build + enrich on the HANDLER module (the handler imports
    # both names, so they are handler_mod attributes — patch them there).
    monkeypatch.setattr(handler_mod, "build_adapters_from_run_config", lambda **k: [])

    def fake_enrich(**kw):
        kw["repository"].upsert_artist_info(artist_id=kw["artist_id"], last_run_id="r",
                                            prompt_slug="artist_v1", prompt_version="v1",
                                            merged=object(), provenance={})
        if kw.get("on_outcome"):
            kw["on_outcome"](kw["artist_id"], True)
    monkeypatch.setattr(handler_mod, "enrich_artist_for_run", fake_enrich)

    event = {"Records": [{"body": json.dumps({"run_id": "r", "artist_id": "a", "artist_name": "ANNA"})}]}
    out = handler_mod.lambda_handler(event, None)
    assert out["processed"] == 1
    assert repo.upserted == "a"
    assert auto.outcomes == [("a", True)]

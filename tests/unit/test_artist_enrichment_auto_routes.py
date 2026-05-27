import json
import collector.artist_enrichment.auto_routes as ar


class FakeRepo:
    def __init__(self): self.saved = None
    def get_config(self, kind): return None
    def upsert_config(self, **kw): self.saved = kw


def test_get_auto_config_returns_defaults(monkeypatch):
    repo = FakeRepo()
    monkeypatch.setattr(ar, "_build_repository", lambda: repo)
    status, body = ar.handle_get_auto_config({})
    assert status == 200
    assert body["config"]["enabled"] is False
    assert "options" in body and body["options"]["vendors"]


def test_put_auto_config_persists_with_artists_kind(monkeypatch):
    repo = FakeRepo()
    monkeypatch.setattr(ar, "_build_repository", lambda: repo)
    event = {"body": json.dumps({"enabled": True, "vendors": ["openai"],
                                 "models": {"openai": "m"}, "prompt_slug": "artist_v1",
                                 "prompt_version": "v1", "merge_vendor": "deepseek", "merge_model": "d"})}
    status, body = ar.handle_put_auto_config(event)
    assert status == 204
    assert repo.saved["kind"] == "artists" and repo.saved["enabled"] is True

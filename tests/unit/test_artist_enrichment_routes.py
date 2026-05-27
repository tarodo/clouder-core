"""Unit tests for artist enrichment HTTP route handlers."""

import json
import collector.artist_enrichment.routes as routes


class FakeRepo:
    def __init__(self):
        self.runs = []
        self.created = None

    def get_artist_by_id(self, aid):
        return {"id": aid, "name": "ANNA"}

    def derive_artist_context(self, aid):
        from collector.artist_enrichment.repository import ArtistContext
        return ArtistContext(style="techno", sample_tracks=[], known_labels=[])

    def create_run(self, spec):
        self.created = spec
        return "run-1"

    def get_artist_info(self, aid):
        return {"artist_id": aid, "merged": {}}

    def list_artists(self, **kw):
        return ([{"id": "a", "name": "ANNA"}], 1)


class FakeSQS:
    def __init__(self):
        self.sent = []

    def send_message(self, **kw):
        self.sent.append(kw)


def _setup(monkeypatch, repo=None, sqs=None):
    repo = repo or FakeRepo()
    sqs = sqs or FakeSQS()
    monkeypatch.setattr(routes, "_build_repository", lambda: repo)
    monkeypatch.setattr(routes, "_build_sqs_client", lambda: sqs)
    monkeypatch.setattr(routes, "_queue_url", lambda: "https://q")
    return repo, sqs


def test_post_enrich_creates_run_and_enqueues(monkeypatch):
    repo, sqs = _setup(monkeypatch)
    event = {"body": json.dumps({
        "artists": [{"artist_id": "a1"}],
        "vendors": ["openai"], "models": {"openai": "m"},
        "prompt_slug": "artist_v1", "prompt_version": "v1",
        "merge_vendor": "deepseek", "merge_model": "d",
    })}
    status, body = routes.handle_post_enrich(event)
    assert status == 202
    assert body["run_id"] == "run-1" and body["queued_artists"] == 1
    assert repo.created.requested_artists == 1
    assert len(sqs.sent) == 1
    msg = json.loads(sqs.sent[0]["MessageBody"])
    assert msg["artist_id"] == "a1" and msg["artist_name"] == "ANNA"
    assert "style" not in msg  # worker derives context; message carries no style


def test_post_enrich_rejects_unknown_prompt(monkeypatch):
    from collector.errors import ValidationError
    import pytest
    _setup(monkeypatch)
    event = {"body": json.dumps({
        "artists": [{"artist_id": "a1"}],
        "vendors": ["openai"], "models": {"openai": "m"},
        "prompt_slug": "nope", "prompt_version": "v1",
        "merge_vendor": "deepseek", "merge_model": "d",
    })}
    with pytest.raises(ValidationError):
        routes.handle_post_enrich(event)


def test_get_artist_user_404_when_missing(monkeypatch):
    class R(FakeRepo):
        def get_artist_info_for_user(self, aid, user_id=None):
            return None

    _setup(monkeypatch, repo=R())
    status, body = routes.handle_get_artist_user({"pathParameters": {"artist_id": "x"}})
    assert status == 404

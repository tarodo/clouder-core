import json
from unittest.mock import MagicMock

import pytest

from collector.handler import lambda_handler

_ROUTE = "POST /admin/artists/{artist_id}/enrich-auto"


def _admin_event(artist_id: str) -> dict:
    return {
        "routeKey": _ROUTE,
        "body": None,
        "pathParameters": {"artist_id": artist_id},
        "requestContext": {"authorizer": {"lambda": {"is_admin": True, "user_id": "user-1"}}},
    }


_CONFIG = {
    "kind": "artists",
    "enabled": False,
    "vendors": ["gemini", "openai", "tavily_deepseek"],
    "models": {
        "gemini": "gemini-3-flash-preview",
        "openai": "gpt-5.4-mini",
        "tavily_deepseek": "deepseek-v4-flash",
    },
    "prompt_slug": "artist_v1_facts",
    "prompt_version": "v1",
    "merge_vendor": "deepseek",
    "merge_model": "deepseek-v4-flash",
}


@pytest.fixture
def patched(monkeypatch):
    repo = MagicMock()
    repo.get_artist_by_id.return_value = {"id": "art-1", "name": "Joja"}
    repo.create_run.return_value = "run-1"
    auto = MagicMock()
    auto.get_config.return_value = dict(_CONFIG)
    sqs = MagicMock()
    monkeypatch.setattr("collector.artist_enrichment.routes._build_repository", lambda: repo)
    monkeypatch.setattr("collector.artist_enrichment.routes._build_auto_repository", lambda: auto)
    monkeypatch.setattr("collector.artist_enrichment.routes._build_sqs_client", lambda: sqs)
    monkeypatch.setenv("ARTIST_ENRICHMENT_QUEUE_URL", "https://sqs.example/q")
    yield repo, auto, sqs


def test_enrich_auto_enqueues_with_config_settings(patched):
    repo, auto, sqs = patched
    resp = lambda_handler(_admin_event("art-1"), None)
    assert resp["statusCode"] == 202
    body = json.loads(resp["body"])
    assert body == {"run_id": "run-1", "queued_artists": 1}
    auto.get_config.assert_called_once_with("artists")
    spec = repo.create_run.call_args[0][0]
    assert spec.requested_artists == 1
    assert spec.created_by_user_id == "user-1"
    msg = json.loads(sqs.send_message.call_args.kwargs["MessageBody"])
    assert msg == {"run_id": "run-1", "artist_id": "art-1", "artist_name": "Joja"}


def test_enrich_auto_404_when_artist_missing(patched):
    repo, _auto, _sqs = patched
    repo.get_artist_by_id.return_value = None
    resp = lambda_handler(_admin_event("nope"), None)
    assert resp["statusCode"] == 404


def test_enrich_auto_409_when_no_config(patched):
    _repo, auto, _sqs = patched
    auto.get_config.return_value = None
    resp = lambda_handler(_admin_event("art-1"), None)
    assert resp["statusCode"] == 409

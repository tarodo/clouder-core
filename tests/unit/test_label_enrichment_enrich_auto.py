import json
from unittest.mock import MagicMock

import pytest

from collector.handler import lambda_handler

_ROUTE = "POST /admin/labels/{label_id}/enrich-auto"


def _admin_event(label_id: str) -> dict:
    return {
        "routeKey": _ROUTE,
        "body": None,
        "pathParameters": {"label_id": label_id},
        "requestContext": {"authorizer": {"lambda": {"is_admin": True, "user_id": "user-1"}}},
    }


_CONFIG = {
    "kind": "labels",
    "enabled": False,
    "vendors": ["gemini", "openai", "tavily_deepseek"],
    "models": {
        "gemini": "gemini-3-flash-preview",
        "openai": "gpt-5.4-mini",
        "tavily_deepseek": "deepseek-v4-flash",
    },
    "prompt_slug": "label_v3_app_fields",
    "prompt_version": "v1",
    "merge_vendor": "deepseek",
    "merge_model": "deepseek-v4-flash",
}


@pytest.fixture
def patched(monkeypatch):
    repo = MagicMock()
    repo.get_label_by_id.return_value = {"id": "lbl-1", "name": "Fokuz"}
    repo.derive_style_for_label.return_value = "dnb"
    repo.create_run.return_value = "run-1"
    auto = MagicMock()
    auto.get_config.return_value = dict(_CONFIG)
    sqs = MagicMock()
    monkeypatch.setattr("collector.label_enrichment.routes._build_repository", lambda: repo)
    monkeypatch.setattr("collector.label_enrichment.routes._build_auto_repository", lambda: auto)
    monkeypatch.setattr("collector.label_enrichment.routes._build_sqs_client", lambda: sqs)
    monkeypatch.setenv("LABEL_ENRICHMENT_QUEUE_URL", "https://sqs.example/q")
    yield repo, auto, sqs


def test_enrich_auto_enqueues_with_config_settings(patched):
    repo, auto, sqs = patched
    resp = lambda_handler(_admin_event("lbl-1"), None)
    assert resp["statusCode"] == 202
    body = json.loads(resp["body"])
    assert body == {"run_id": "run-1", "queued_labels": 1}
    auto.get_config.assert_called_once_with("labels")
    spec = repo.create_run.call_args[0][0]
    assert spec.vendors == _CONFIG["vendors"]
    assert spec.prompt_slug == "label_v3_app_fields"
    assert spec.requested_labels == 1
    assert spec.source == "manual"
    assert spec.created_by_user_id == "user-1"
    sqs.send_message.assert_called_once()
    msg = json.loads(sqs.send_message.call_args.kwargs["MessageBody"])
    assert msg == {"run_id": "run-1", "label_id": "lbl-1", "label_name": "Fokuz", "style": "dnb"}


def test_enrich_auto_404_when_label_missing(patched):
    repo, _auto, _sqs = patched
    repo.get_label_by_id.return_value = None
    resp = lambda_handler(_admin_event("nope"), None)
    assert resp["statusCode"] == 404


def test_enrich_auto_409_when_no_config(patched):
    _repo, auto, _sqs = patched
    auto.get_config.return_value = None
    resp = lambda_handler(_admin_event("lbl-1"), None)
    assert resp["statusCode"] == 409


def test_enrich_auto_rejects_non_admin(patched):
    event = _admin_event("lbl-1")
    event["requestContext"]["authorizer"]["lambda"]["is_admin"] = False
    resp = lambda_handler(event, None)
    assert resp["statusCode"] == 403

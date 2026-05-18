import json
from unittest.mock import MagicMock, patch

import pytest

from collector.handler import lambda_handler


def _admin_event(route_key: str, body: dict | None = None, path_params: dict | None = None) -> dict:
    return {
        "routeKey": route_key,
        "body": json.dumps(body) if body is not None else None,
        "pathParameters": path_params or {},
        "requestContext": {
            "authorizer": {"lambda": {"is_admin": True, "user_id": "user-1"}},
        },
    }


def _non_admin_event(route_key: str, body: dict | None = None) -> dict:
    return {
        "routeKey": route_key,
        "body": json.dumps(body) if body is not None else None,
        "pathParameters": {},
        "requestContext": {
            "authorizer": {"lambda": {"is_admin": False, "user_id": "user-2"}},
        },
    }


_VALID_BODY = {
    "labels": [
        {"label_name": "Drumcode", "style": "techno"},
        {"label_name": "Anjunadeep", "style": "deep house"},
    ],
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
def patched_deps(monkeypatch):
    repo = MagicMock()
    repo.upsert_label_by_name.side_effect = lambda name: f"lbl-{name.lower().replace(' ', '-')}"
    repo.create_run.return_value = "run-1"
    sqs_client = MagicMock()
    monkeypatch.setattr(
        "collector.label_enrichment.routes._build_repository",
        lambda: repo,
    )
    monkeypatch.setattr(
        "collector.label_enrichment.routes._build_sqs_client",
        lambda: sqs_client,
    )
    monkeypatch.setenv("LABEL_ENRICHMENT_QUEUE_URL", "https://sqs.example/q")
    yield repo, sqs_client


def test_post_enrich_returns_202_and_enqueues_one_message_per_label(patched_deps):
    repo, sqs = patched_deps
    resp = lambda_handler(_admin_event("POST /admin/labels/enrich", _VALID_BODY), None)
    assert resp["statusCode"] == 202
    body = json.loads(resp["body"])
    assert body["run_id"] == "run-1"
    assert body["queued_labels"] == 2
    assert sqs.send_message.call_count == 2
    repo.create_run.assert_called_once()
    spec = repo.create_run.call_args[0][0]
    assert spec.requested_labels == 2
    assert spec.created_by_user_id == "user-1"


def test_post_enrich_rejects_non_admin(patched_deps):
    resp = lambda_handler(_non_admin_event("POST /admin/labels/enrich", _VALID_BODY), None)
    assert resp["statusCode"] == 403


def test_post_enrich_rejects_invalid_body(patched_deps):
    bad = {**_VALID_BODY, "labels": []}
    resp = lambda_handler(_admin_event("POST /admin/labels/enrich", bad), None)
    assert resp["statusCode"] == 400

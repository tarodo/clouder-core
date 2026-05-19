"""GET /admin/labels/{label_id}/history exposes per-label cell history."""

import json
from unittest.mock import MagicMock


def _admin_event(label_id: str) -> dict:
    return {
        "routeKey": "GET /admin/labels/{label_id}/history",
        "pathParameters": {"label_id": label_id},
        "requestContext": {"authorizer": {"lambda": {"is_admin": True}}},
    }


def test_label_history_returns_items(monkeypatch):
    from collector import handler

    fake_repo = MagicMock()
    fake_repo.list_history_for_label.return_value = [
        {
            "cell_id": "c-1",
            "run_id": "r-1",
            "run_status": "completed",
            "run_created_at": "2026-05-19T14:00:00Z",
            "prompt_slug": "label_v3_app_fields",
            "prompt_version": "v1",
            "vendor": "gemini",
            "model": "gemini-2.5-pro",
            "status": "ok",
            "latency_ms": 1200,
            "cost_usd": 0.005,
            "error_message": None,
            "parsed": {"label_name": "Fokuz"},
            "citations": [],
        }
    ]
    monkeypatch.setattr(
        "collector.label_enrichment.routes._build_repository",
        lambda: fake_repo,
    )

    resp = handler.lambda_handler(_admin_event("lbl-1"), None)
    body = json.loads(resp["body"])
    assert resp["statusCode"] == 200
    assert len(body["items"]) == 1
    assert body["items"][0]["vendor"] == "gemini"
    fake_repo.list_history_for_label.assert_called_once_with("lbl-1")


def test_label_history_requires_admin(monkeypatch):
    from collector import handler

    event = _admin_event("lbl-1")
    event["requestContext"]["authorizer"]["lambda"]["is_admin"] = False
    resp = handler.lambda_handler(event, None)
    assert resp["statusCode"] == 403

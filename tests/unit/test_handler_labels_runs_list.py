"""GET /admin/labels/enrich-runs paginates enrichment runs."""

import json
from unittest.mock import MagicMock


def _admin_event(qs: dict) -> dict:
    return {
        "routeKey": "GET /admin/labels/enrich-runs",
        "queryStringParameters": qs,
        "pathParameters": {},
        "requestContext": {"authorizer": {"lambda": {"is_admin": True}}},
    }


def test_list_runs_returns_items_sorted_by_created_at_desc(monkeypatch):
    from collector import handler

    fake_repo = MagicMock()
    fake_repo.list_runs.return_value = (
        [
            {"id": "r-1", "status": "completed", "created_at": "2026-05-19T14:00:00Z",
             "cells_total": 3, "cells_ok": 3, "cells_error": 0, "cost_usd": 0.015,
             "prompt_slug": "label_v3_app_fields", "prompt_version": "v1",
             "vendors": ["gemini", "openai", "tavily_deepseek"]},
        ],
        None,
    )
    monkeypatch.setattr(
        "collector.label_enrichment.routes._build_repository",
        lambda: fake_repo,
    )
    resp = handler.lambda_handler(_admin_event({"limit": "50"}), None)
    body = json.loads(resp["body"])
    assert resp["statusCode"] == 200
    assert body["items"][0]["id"] == "r-1"
    assert body["next_cursor"] is None
    fake_repo.list_runs.assert_called_once_with(status=None, cursor=None, limit=50)

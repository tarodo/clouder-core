"""GET /admin/labels/enrich-runs/{run_id} now includes cells[]."""

import json
from unittest.mock import MagicMock


def _admin_event(run_id: str) -> dict:
    return {
        "routeKey": "GET /admin/labels/enrich-runs/{run_id}",
        "pathParameters": {"run_id": run_id},
        "requestContext": {"authorizer": {"lambda": {"is_admin": True}}},
    }


def test_run_detail_includes_cells(monkeypatch):
    from collector import handler

    fake_repo = MagicMock()
    fake_repo.get_run.return_value = {
        "id": "r-1", "status": "completed",
        "cells_total": 3, "cells_ok": 3, "cells_error": 0,
    }
    fake_repo.list_cells_for_run.return_value = [
        {"cell_id": "c-1", "label_id": "l-1", "label_name": "Fokuz",
         "vendor": "gemini", "status": "ok", "latency_ms": 1200,
         "cost_usd": 0.005, "error_message": None},
        {"cell_id": "c-2", "label_id": "l-1", "label_name": "Fokuz",
         "vendor": "openai", "status": "ok", "latency_ms": 2400,
         "cost_usd": 0.006, "error_message": None},
    ]
    monkeypatch.setattr(
        "collector.label_enrichment.routes._build_repository",
        lambda: fake_repo,
    )
    resp = handler.lambda_handler(_admin_event("r-1"), None)
    body = json.loads(resp["body"])
    assert resp["statusCode"] == 200
    assert len(body["cells"]) == 2
    assert body["cells"][0]["vendor"] == "gemini"

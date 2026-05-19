"""GET /admin/labels/backlog lists labels without (current) enrichment."""

import json
from unittest.mock import MagicMock


def _admin_event(qs: dict) -> dict:
    return {
        "routeKey": "GET /admin/labels/backlog",
        "queryStringParameters": qs,
        "pathParameters": {},
        "requestContext": {"authorizer": {"lambda": {"is_admin": True}}},
    }


def test_backlog_returns_items_and_total_estimate(monkeypatch):
    from collector import handler

    fake_repo = MagicMock()
    fake_repo.list_backlog.return_value = (
        [
            {"id": "lbl-1", "name": "VIM", "style": "drum-and-bass",
             "status": "failed", "track_count": 12,
             "last_attempted_at": "2026-05-12T10:00:00Z"},
            {"id": "lbl-2", "name": "Fokuz", "style": "drum-and-bass",
             "status": "none", "track_count": 142, "last_attempted_at": None},
        ],
        None,
        142,
    )
    monkeypatch.setattr(
        "collector.label_enrichment.routes._build_repository",
        lambda: fake_repo,
    )

    resp = handler.lambda_handler(_admin_event({"style": "drum-and-bass"}), None)
    body = json.loads(resp["body"])
    assert resp["statusCode"] == 200
    assert len(body["items"]) == 2
    assert body["items"][0]["status"] == "failed"
    assert body["total_estimate"] == 142
    assert body["next_cursor"] is None


def test_backlog_requires_admin(monkeypatch):
    from collector import handler

    event = _admin_event({})
    event["requestContext"]["authorizer"]["lambda"]["is_admin"] = False
    resp = handler.lambda_handler(event, None)
    assert resp["statusCode"] == 403

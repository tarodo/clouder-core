"""GET /labels returns paginated label list with style/q/sort filters."""

import json
from unittest.mock import MagicMock


def _user_event(qs: dict) -> dict:
    return {
        "routeKey": "GET /labels",
        "queryStringParameters": qs,
        "pathParameters": {},
        "requestContext": {
            "authorizer": {"lambda": {"is_admin": False, "user_id": "u-1"}}
        },
    }


def test_list_labels_returns_items_and_next_cursor(monkeypatch):
    from collector import handler

    fake_repo = MagicMock()
    fake_repo.list_labels.return_value = (
        [
            {
                "id": "lbl-1",
                "name": "Fokuz",
                "style": "drum-and-bass",
                "status": "completed",
                "info": {
                    "tagline": "soulful d&b",
                    "country": "NL",
                    "primary_styles": ["liquid"],
                    "activity": "steady",
                    "updated_at": "2026-05-19T00:00:00Z",
                },
            }
        ],
        "cursor-2",
    )
    monkeypatch.setattr(
        "collector.label_enrichment.routes._build_repository",
        lambda: fake_repo,
    )

    resp = handler.lambda_handler(
        _user_event({"style": "drum-and-bass", "limit": "50"}),
        None,
    )
    body = json.loads(resp["body"])
    assert resp["statusCode"] == 200
    assert body["items"][0]["id"] == "lbl-1"
    assert body["items"][0]["info"]["tagline"] == "soulful d&b"
    assert body["next_cursor"] == "cursor-2"
    fake_repo.list_labels.assert_called_once_with(
        style="drum-and-bass", q=None, sort="name", cursor=None, limit=50,
    )


def test_list_labels_passes_q_and_sort(monkeypatch):
    from collector import handler

    fake_repo = MagicMock()
    fake_repo.list_labels.return_value = ([], None)
    monkeypatch.setattr(
        "collector.label_enrichment.routes._build_repository",
        lambda: fake_repo,
    )

    handler.lambda_handler(
        _user_event({"style": "techno", "q": "fok", "sort": "recent", "cursor": "abc"}),
        None,
    )
    fake_repo.list_labels.assert_called_once_with(
        style="techno", q="fok", sort="recent", cursor="abc", limit=50,
    )

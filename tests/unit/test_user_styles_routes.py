"""GET /styles — personal list, catalog scope, fallbacks."""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest


def _user_event(route: str, *, qs: dict | None = None,
                body: dict | None = None) -> dict:
    return {
        "routeKey": route,
        "pathParameters": {},
        "queryStringParameters": qs or {},
        "body": json.dumps(body) if body is not None else None,
        "requestContext": {
            "authorizer": {"lambda": {"is_admin": False, "user_id": "u-1"}}
        },
    }


@pytest.fixture
def fake_repo(monkeypatch):
    repo = MagicMock()
    monkeypatch.setattr(
        "collector.user_styles.routes._build_repository", lambda: repo
    )
    return repo


def test_get_styles_with_selection_returns_personal_list(fake_repo):
    from collector import handler

    fake_repo.count_selection.return_value = 2
    fake_repo.list_for_user.return_value = [{"id": "sty-1", "name": "DnB"}]
    fake_repo.count_for_user.return_value = 2

    resp = handler.lambda_handler(_user_event("GET /styles"), None)

    assert resp["statusCode"] == 200
    body = json.loads(resp["body"])
    assert body["items"][0]["name"] == "DnB"
    assert body["total"] == 2
    assert body["correlation_id"]
    fake_repo.list_for_user.assert_called_once_with(
        user_id="u-1", limit=50, offset=0, search=None
    )
    fake_repo.list_all.assert_not_called()


def test_get_styles_without_selection_falls_back_to_catalog(fake_repo):
    from collector import handler

    fake_repo.count_selection.return_value = 0
    fake_repo.list_all.return_value = [{"id": "sty-9", "name": "House"}]
    fake_repo.count_all.return_value = 1

    resp = handler.lambda_handler(_user_event("GET /styles"), None)

    assert resp["statusCode"] == 200
    assert json.loads(resp["body"])["items"][0]["name"] == "House"
    fake_repo.list_for_user.assert_not_called()


def test_get_styles_scope_all_returns_catalog_with_flags(fake_repo):
    from collector import handler

    fake_repo.list_catalog.return_value = [
        {"id": "sty-1", "name": "DnB", "selected": True, "position": 0}
    ]
    fake_repo.count_all.return_value = 1

    resp = handler.lambda_handler(
        _user_event("GET /styles", qs={"scope": "all"}), None
    )

    assert resp["statusCode"] == 200
    assert json.loads(resp["body"])["items"][0]["selected"] is True
    fake_repo.count_selection.assert_not_called()


def test_get_styles_rejects_unknown_scope(fake_repo):
    from collector import handler

    resp = handler.lambda_handler(
        _user_event("GET /styles", qs={"scope": "mine"}), None
    )

    assert resp["statusCode"] == 400
    assert json.loads(resp["body"])["error_code"] == "validation_error"


def test_get_styles_without_user_returns_401(monkeypatch):
    from collector import handler

    event = _user_event("GET /styles")
    event["requestContext"] = {"authorizer": {"lambda": {}}}

    resp = handler.lambda_handler(event, None)

    assert resp["statusCode"] == 401


def test_get_styles_without_db_returns_503(monkeypatch):
    from collector import handler

    monkeypatch.setattr(
        "collector.user_styles.routes._build_repository", lambda: None
    )

    resp = handler.lambda_handler(_user_event("GET /styles"), None)

    assert resp["statusCode"] == 503
    assert json.loads(resp["body"])["error_code"] == "db_not_configured"


def test_get_styles_rejects_unknown_scope_without_db(monkeypatch):
    from collector import handler

    monkeypatch.setattr(
        "collector.user_styles.routes._build_repository", lambda: None
    )

    resp = handler.lambda_handler(
        _user_event("GET /styles", qs={"scope": "mine"}), None
    )

    assert resp["statusCode"] == 400
    assert json.loads(resp["body"])["error_code"] == "validation_error"


def test_put_my_styles_replaces_selection(fake_repo):
    from collector import handler

    resp = handler.lambda_handler(
        _user_event("PUT /me/styles", body={"style_ids": ["sty-2", "sty-1"]}),
        None,
    )

    assert resp["statusCode"] == 204
    assert resp["body"] == ""
    fake_repo.replace_selection.assert_called_once_with(
        user_id="u-1", style_ids=["sty-2", "sty-1"]
    )


def test_put_my_styles_empty_list_clears(fake_repo):
    from collector import handler

    resp = handler.lambda_handler(
        _user_event("PUT /me/styles", body={"style_ids": []}), None
    )

    assert resp["statusCode"] == 204
    fake_repo.replace_selection.assert_called_once_with(
        user_id="u-1", style_ids=[]
    )


@pytest.mark.parametrize(
    "body,fragment",
    [
        ({}, "style_ids must be an array"),
        ({"style_ids": "sty-1"}, "style_ids must be an array"),
        ({"style_ids": [1, 2]}, "style_ids must be an array"),
        ({"style_ids": ["a", "a"]}, "style_ids must be unique"),
        ({"style_ids": [f"s-{i}" for i in range(101)]}, "exceeds 100"),
    ],
)
def test_put_my_styles_validation(fake_repo, body, fragment):
    from collector import handler

    resp = handler.lambda_handler(_user_event("PUT /me/styles", body=body), None)

    assert resp["statusCode"] == 400
    payload = json.loads(resp["body"])
    assert payload["error_code"] == "validation_error"
    assert fragment in payload["message"]
    fake_repo.replace_selection.assert_not_called()


def test_put_my_styles_unknown_style_returns_400(fake_repo):
    from collector import handler
    from collector.errors import ValidationError

    fake_repo.replace_selection.side_effect = ValidationError(
        "unknown style_id: sty-9"
    )

    resp = handler.lambda_handler(
        _user_event("PUT /me/styles", body={"style_ids": ["sty-9"]}), None
    )

    assert resp["statusCode"] == 400
    assert "unknown style_id: sty-9" in json.loads(resp["body"])["message"]

"""PUT /labels/{id}/preference + GET /me/label-preferences."""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest


def _user_event(route: str, *, body: dict | None = None,
                path: dict | None = None, qs: dict | None = None) -> dict:
    return {
        "routeKey": route,
        "pathParameters": path or {},
        "queryStringParameters": qs or {},
        "body": json.dumps(body) if body is not None else None,
        "requestContext": {
            "authorizer": {"lambda": {"is_admin": False, "user_id": "u-1"}}
        },
    }


def test_put_pref_liked_calls_upsert(monkeypatch):
    from collector import handler

    fake_repo = MagicMock()
    fake_repo.get_label_by_id.return_value = {"id": "lbl-1", "name": "Fokuz"}
    monkeypatch.setattr(
        "collector.label_enrichment.routes._build_repository",
        lambda: fake_repo,
    )
    resp = handler.lambda_handler(
        _user_event(
            "PUT /labels/{label_id}/preference",
            body={"status": "liked"},
            path={"label_id": "lbl-1"},
        ),
        None,
    )
    assert resp["statusCode"] == 204
    fake_repo.upsert_user_label_pref.assert_called_once_with(
        user_id="u-1", label_id="lbl-1", status="liked",
    )
    fake_repo.delete_user_label_pref.assert_not_called()


def test_put_pref_none_calls_delete(monkeypatch):
    from collector import handler

    fake_repo = MagicMock()
    fake_repo.get_label_by_id.return_value = {"id": "lbl-1", "name": "Fokuz"}
    monkeypatch.setattr(
        "collector.label_enrichment.routes._build_repository",
        lambda: fake_repo,
    )
    resp = handler.lambda_handler(
        _user_event(
            "PUT /labels/{label_id}/preference",
            body={"status": "none"},
            path={"label_id": "lbl-1"},
        ),
        None,
    )
    assert resp["statusCode"] == 204
    fake_repo.delete_user_label_pref.assert_called_once_with(
        user_id="u-1", label_id="lbl-1",
    )
    fake_repo.upsert_user_label_pref.assert_not_called()


def test_put_pref_404_when_label_missing(monkeypatch):
    from collector import handler

    fake_repo = MagicMock()
    fake_repo.get_label_by_id.return_value = None
    monkeypatch.setattr(
        "collector.label_enrichment.routes._build_repository",
        lambda: fake_repo,
    )
    resp = handler.lambda_handler(
        _user_event(
            "PUT /labels/{label_id}/preference",
            body={"status": "liked"},
            path={"label_id": "nope"},
        ),
        None,
    )
    assert resp["statusCode"] == 404


@pytest.mark.parametrize("bad", ["loved", "", None, 7])
def test_put_pref_422_on_invalid_status(monkeypatch, bad):
    from collector import handler

    fake_repo = MagicMock()
    fake_repo.get_label_by_id.return_value = {"id": "lbl-1", "name": "Fokuz"}
    monkeypatch.setattr(
        "collector.label_enrichment.routes._build_repository",
        lambda: fake_repo,
    )
    resp = handler.lambda_handler(
        _user_event(
            "PUT /labels/{label_id}/preference",
            body={"status": bad},
            path={"label_id": "lbl-1"},
        ),
        None,
    )
    assert resp["statusCode"] == 400  # ValidationError → 400 in this codebase


def test_get_my_label_preferences_passes_user_id(monkeypatch):
    from collector import handler

    fake_repo = MagicMock()
    fake_repo.list_user_label_prefs.return_value = (
        [{"id": "lbl-1", "name": "Fokuz", "my_preference": "liked"}],
        1,
    )
    monkeypatch.setattr(
        "collector.label_enrichment.routes._build_repository",
        lambda: fake_repo,
    )
    resp = handler.lambda_handler(
        _user_event(
            "GET /me/label-preferences",
            qs={"status": "liked", "page": "1", "limit": "50"},
        ),
        None,
    )
    body = json.loads(resp["body"])
    assert resp["statusCode"] == 200
    assert body == {
        "items": [{"id": "lbl-1", "name": "Fokuz", "my_preference": "liked"}],
        "total": 1, "page": 1, "limit": 50,
    }
    fake_repo.list_user_label_prefs.assert_called_once_with(
        user_id="u-1", status="liked", page=1, limit=50,
    )


def test_labels_list_forwards_my_and_user_id(monkeypatch):
    from collector import handler

    fake_repo = MagicMock()
    fake_repo.list_labels.return_value = ([], 0)
    monkeypatch.setattr(
        "collector.label_enrichment.routes._build_repository",
        lambda: fake_repo,
    )
    handler.lambda_handler(
        _user_event(
            "GET /labels",
            qs={"my": "liked", "page": "1", "limit": "50", "sort": "name"},
        ),
        None,
    )
    kwargs = fake_repo.list_labels.call_args.kwargs
    assert kwargs["my"] == "liked"
    assert kwargs["user_id"] == "u-1"


def test_label_detail_forwards_user_id(monkeypatch):
    from collector import handler

    fake_repo = MagicMock()
    fake_repo.get_label_info_for_user.return_value = {
        "label_name": "Fokuz", "my_preference": "liked",
    }
    monkeypatch.setattr(
        "collector.label_enrichment.routes._build_repository",
        lambda: fake_repo,
    )
    handler.lambda_handler(
        _user_event(
            "GET /labels/{label_id}",
            path={"label_id": "lbl-1"},
        ),
        None,
    )
    fake_repo.get_label_info_for_user.assert_called_once_with(
        "lbl-1", user_id="u-1",
    )

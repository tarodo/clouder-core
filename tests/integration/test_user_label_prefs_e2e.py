"""PUT /labels/{id}/preference + GET /labels/{id} round trip."""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock


def _event(route: str, *, body: dict | None = None,
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


def test_put_then_get_label_returns_my_preference(monkeypatch):
    """The user sets a preference; the next GET surfaces it."""
    from collector import handler

    state: dict[tuple[str, str], str] = {}

    fake_repo = MagicMock()
    fake_repo.get_label_by_id.return_value = {"id": "lbl-1", "name": "Fokuz"}

    def upsert(*, user_id: str, label_id: str, status: str) -> None:
        state[(user_id, label_id)] = status

    def delete(*, user_id: str, label_id: str) -> None:
        state.pop((user_id, label_id), None)

    def get_for_user(label_id: str, user_id: str | None = None) -> dict[str, Any] | None:
        return {
            "label_name": "Fokuz",
            "my_preference": state.get((user_id, label_id)),
        }

    fake_repo.upsert_user_label_pref.side_effect = upsert
    fake_repo.delete_user_label_pref.side_effect = delete
    fake_repo.get_label_info_for_user.side_effect = get_for_user
    monkeypatch.setattr(
        "collector.label_enrichment.routes._build_repository",
        lambda: fake_repo,
    )

    # 1. Start unrated → GET shows my_preference None.
    resp = handler.lambda_handler(
        _event("GET /labels/{label_id}", path={"label_id": "lbl-1"}), None,
    )
    assert resp["statusCode"] == 200
    assert json.loads(resp["body"])["my_preference"] is None

    # 2. PUT liked → 204.
    resp = handler.lambda_handler(
        _event(
            "PUT /labels/{label_id}/preference",
            body={"status": "liked"},
            path={"label_id": "lbl-1"},
        ),
        None,
    )
    assert resp["statusCode"] == 204

    # 3. GET reflects new state.
    resp = handler.lambda_handler(
        _event("GET /labels/{label_id}", path={"label_id": "lbl-1"}), None,
    )
    assert json.loads(resp["body"])["my_preference"] == "liked"

    # 4. PUT none → state cleared.
    resp = handler.lambda_handler(
        _event(
            "PUT /labels/{label_id}/preference",
            body={"status": "none"},
            path={"label_id": "lbl-1"},
        ),
        None,
    )
    assert resp["statusCode"] == 204
    resp = handler.lambda_handler(
        _event("GET /labels/{label_id}", path={"label_id": "lbl-1"}), None,
    )
    assert json.loads(resp["body"])["my_preference"] is None

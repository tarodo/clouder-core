"""GET /labels/{id} returns sanitized LabelInfo for completed labels."""

import json
from unittest.mock import MagicMock


def _user_event(label_id: str) -> dict:
    return {
        "routeKey": "GET /labels/{label_id}",
        "pathParameters": {"label_id": label_id},
        "requestContext": {
            "authorizer": {"lambda": {"is_admin": False, "user_id": "u-1"}}
        },
    }


def test_get_label_user_returns_sanitized_payload(monkeypatch):
    from collector import handler

    fake_repo = MagicMock()
    fake_repo.get_label_info_for_user.return_value = {
        "label_name": "Fokuz",
        "country": "NL",
        "tagline": "soulful d&b",
        "summary": "Rotterdam liquid label.",
        "primary_styles": ["liquid"],
        "website": "https://fokuzrecordings.com",
        "ai_content": "none_detected",
        "ai_reasoning": "no signals",
    }
    monkeypatch.setattr(
        "collector.label_enrichment.routes._build_repository",
        lambda: fake_repo,
    )
    resp = handler.lambda_handler(_user_event("lbl-1"), None)
    body = json.loads(resp["body"])
    assert resp["statusCode"] == 200
    assert body["label_name"] == "Fokuz"
    # Admin-only fields must not leak
    for forbidden in ("run_id", "prompt_version", "token_cost", "provenance"):
        assert forbidden not in body, f"{forbidden} leaked to user-facing endpoint"


def test_get_label_user_returns_minimal_payload_when_not_completed(monkeypatch):
    from collector import handler

    fake_repo = MagicMock()
    fake_repo.get_label_info_for_user.return_value = {
        "label_name": "Drumcode",
        "my_preference": None,
    }
    monkeypatch.setattr(
        "collector.label_enrichment.routes._build_repository",
        lambda: fake_repo,
    )
    resp = handler.lambda_handler(_user_event("lbl-x"), None)
    body = json.loads(resp["body"])
    assert resp["statusCode"] == 200
    assert body == {"label_name": "Drumcode", "my_preference": None}


def test_get_label_user_returns_404_when_label_missing(monkeypatch):
    from collector import handler

    fake_repo = MagicMock()
    fake_repo.get_label_info_for_user.return_value = None
    monkeypatch.setattr(
        "collector.label_enrichment.routes._build_repository",
        lambda: fake_repo,
    )
    resp = handler.lambda_handler(_user_event("nope"), None)
    assert resp["statusCode"] == 404

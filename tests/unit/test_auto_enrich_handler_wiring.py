import json
from unittest.mock import MagicMock, patch


def _admin_event(method_path: str, body: dict | None = None) -> dict:
    return {
        "routeKey": method_path,
        "queryStringParameters": None,
        "pathParameters": {},
        "body": json.dumps(body) if body is not None else None,
        "requestContext": {"authorizer": {"lambda": {"is_admin": True, "user_id": "u1"}}},
    }


def test_get_auto_config_routed():
    from collector import handler
    repo = MagicMock()
    repo.get_config.return_value = None
    with patch("collector.label_enrichment.auto_routes._build_repository", return_value=repo):
        resp = handler.lambda_handler(_admin_event("GET /admin/auto-enrich/labels"), None)
    assert resp["statusCode"] == 200
    assert json.loads(resp["body"])["config"]["enabled"] is False


def test_put_auto_config_routed_returns_204():
    from collector import handler
    repo = MagicMock()
    with patch("collector.label_enrichment.auto_routes._build_repository", return_value=repo):
        resp = handler.lambda_handler(_admin_event(
            "PUT /admin/auto-enrich/labels",
            {"enabled": False},
        ), None)
    assert resp["statusCode"] == 204


def test_auto_config_requires_admin():
    from collector import handler
    event = _admin_event("GET /admin/auto-enrich/labels")
    event["requestContext"]["authorizer"]["lambda"]["is_admin"] = False
    resp = handler.lambda_handler(event, None)
    assert resp["statusCode"] == 403

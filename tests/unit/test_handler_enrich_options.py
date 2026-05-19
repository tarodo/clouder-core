"""GET /admin/labels/enrich/options exposes vendors + prompts for FE form."""

import json


def _admin_event() -> dict:
    return {
        "routeKey": "GET /admin/labels/enrich/options",
        "queryStringParameters": None,
        "pathParameters": {},
        "requestContext": {"authorizer": {"lambda": {"is_admin": True}}},
    }


def test_enrich_options_payload_shape():
    from collector import handler

    resp = handler.lambda_handler(_admin_event(), None)
    body = json.loads(resp["body"])
    assert resp["statusCode"] == 200
    assert "vendors" in body and set(body["vendors"]) <= {"gemini", "openai", "tavily_deepseek"}
    assert "prompt_versions" in body and len(body["prompt_versions"]) >= 1
    assert any(p.get("is_default") for p in body["prompt_versions"])
    assert "default_models" in body
    assert body["merge"]["vendor"] == "deepseek"

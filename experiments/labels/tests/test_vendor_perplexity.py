import json

import httpx
import pytest

from lab.schemas import LabelInfo
from lab.vendors.perplexity_sonar import PerplexitySonarAdapter


def _valid_payload() -> dict:
    return {
        "label_name": "Drumcode",
        "ai_reasoning": "No AI signals.",
        "summary": "Swedish techno label.",
        "confidence": 0.9,
    }


def _api_body(content_obj: dict, citations: list[str]) -> dict:
    return {
        "choices": [
            {
                "message": {"content": json.dumps(content_obj)},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 410, "completion_tokens": 280, "total_tokens": 690},
        "model": "sonar",
        "citations": citations,
    }


def test_run_parses_response():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/chat/completions"
        body = json.loads(request.content)
        assert body["model"] == "sonar"
        assert body["messages"][0]["role"] == "system"
        return httpx.Response(
            200,
            json=_api_body(_valid_payload(), ["https://example.com/x"]),
        )

    transport = httpx.MockTransport(handler)
    client = httpx.Client(transport=transport, base_url="https://api.perplexity.ai")
    adapter = PerplexitySonarAdapter(
        api_key="pplx-test",
        default_model="sonar",
        client=client,
    )
    resp = adapter.run(system="s", user="u", schema=LabelInfo)

    assert resp.error is None
    assert resp.parsed.label_name == "Drumcode"
    assert resp.citations == ["https://example.com/x"]
    assert resp.usage["input_tokens"] == 410
    assert resp.usage["output_tokens"] == 280
    assert resp.usage["cost_usd"] > 0
    assert resp.model == "sonar"


def test_run_returns_error_on_http_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="server error")

    transport = httpx.MockTransport(handler)
    client = httpx.Client(transport=transport, base_url="https://api.perplexity.ai")
    adapter = PerplexitySonarAdapter(
        api_key="pplx-test",
        default_model="sonar",
        client=client,
    )
    resp = adapter.run(system="s", user="u", schema=LabelInfo)
    assert resp.parsed is None
    assert resp.error is not None


def test_run_returns_error_on_bad_json():
    def handler(request: httpx.Request) -> httpx.Response:
        body = {
            "choices": [{"message": {"content": "not json"}}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1},
            "model": "sonar",
        }
        return httpx.Response(200, json=body)

    transport = httpx.MockTransport(handler)
    client = httpx.Client(transport=transport, base_url="https://api.perplexity.ai")
    adapter = PerplexitySonarAdapter(
        api_key="pplx-test",
        default_model="sonar",
        client=client,
    )
    resp = adapter.run(system="s", user="u", schema=LabelInfo)
    assert resp.parsed is None
    assert "parse error" in resp.error.lower()

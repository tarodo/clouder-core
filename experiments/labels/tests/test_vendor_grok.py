import json
from types import SimpleNamespace

import pytest

from lab.schemas import LabelInfo
from lab.vendors.xai_grok import XAIGrokAdapter


def _valid_payload_json() -> str:
    return json.dumps(
        {
            "label_name": "Drumcode",
            "ai_reasoning": "No AI signals.",
            "summary": "Swedish techno label.",
            "confidence": 0.9,
        }
    )


def _mock_response(content: str) -> SimpleNamespace:
    choice = SimpleNamespace(
        message=SimpleNamespace(content=content),
        finish_reason="stop",
    )
    usage = SimpleNamespace(prompt_tokens=400, completion_tokens=300, total_tokens=700)
    return SimpleNamespace(
        choices=[choice],
        usage=usage,
        model="grok-4",
        citations=["https://example.com/a", "https://example.com/b"],
    )


def test_run_parses_json_content(mocker):
    fake_client = mocker.MagicMock()
    fake_client.chat.completions.create.return_value = _mock_response(_valid_payload_json())

    adapter = XAIGrokAdapter(
        api_key="xai-test",
        default_model="grok-4",
        client=fake_client,
    )
    resp = adapter.run(system="sys", user="usr", schema=LabelInfo)

    assert resp.error is None
    assert resp.parsed.label_name == "Drumcode"
    assert resp.citations == ["https://example.com/a", "https://example.com/b"]
    assert resp.usage["input_tokens"] == 400
    assert resp.usage["output_tokens"] == 300
    assert resp.usage["cost_usd"] > 0

    call = fake_client.chat.completions.create.call_args.kwargs
    assert call["model"] == "grok-4"
    assert call["messages"][0]["role"] == "system"
    assert call["messages"][0]["content"] == "sys"
    assert call["messages"][1]["content"] == "usr"
    assert call["response_format"]["type"] == "json_schema"
    assert call["tools"] == [{"type": "live_search"}]
    assert "extra_body" not in call


def test_run_returns_error_on_bad_json(mocker):
    fake_client = mocker.MagicMock()
    fake_client.chat.completions.create.return_value = _mock_response("not json")
    adapter = XAIGrokAdapter(api_key="x", default_model="grok-4", client=fake_client)
    resp = adapter.run(system="s", user="u", schema=LabelInfo)
    assert resp.parsed is None
    assert resp.error is not None


def test_run_returns_error_on_exception(mocker):
    fake_client = mocker.MagicMock()
    fake_client.chat.completions.create.side_effect = RuntimeError("boom")
    adapter = XAIGrokAdapter(api_key="x", default_model="grok-4", client=fake_client)
    resp = adapter.run(system="s", user="u", schema=LabelInfo)
    assert resp.parsed is None
    assert "boom" in resp.error

from types import SimpleNamespace
from unittest.mock import MagicMock

from collector.label_enrichment.schemas import LabelInfo
from collector.label_enrichment.vendors.openai_gpt import OpenAIAdapter


def _fake_parsed() -> LabelInfo:
    return LabelInfo(
        label_name="Drumcode",
        ai_reasoning="none",
        summary="techno",
        confidence=0.9,
    )


def test_openai_uses_output_parsed():
    parsed = _fake_parsed()
    usage = SimpleNamespace(input_tokens=200, output_tokens=80)
    response = SimpleNamespace(
        output_parsed=parsed, usage=usage, citations=[], output=[]
    )
    client = MagicMock()
    client.responses.parse.return_value = response
    adapter = OpenAIAdapter(api_key="x", default_model="gpt-5.4-mini", client=client)

    resp = adapter.run(system="sys", user="user", schema=LabelInfo)
    assert resp.error is None
    assert resp.parsed.label_name == "Drumcode"
    assert resp.usage["input_tokens"] == 200
    assert resp.usage["cost_usd"] > 0.0


def test_openai_returns_error_when_no_parsed():
    response = SimpleNamespace(
        output_parsed=None, usage=None, citations=[], output=[]
    )
    client = MagicMock()
    client.responses.parse.return_value = response
    adapter = OpenAIAdapter(api_key="x", default_model="gpt-5.4-mini", client=client)

    resp = adapter.run(system="sys", user="user", schema=LabelInfo)
    assert resp.parsed is None
    assert "no output_parsed" in resp.error


def test_openai_returns_error_on_api_exception():
    client = MagicMock()
    client.responses.parse.side_effect = RuntimeError("rate limited")
    adapter = OpenAIAdapter(api_key="x", default_model="gpt-5.4-mini", client=client)

    resp = adapter.run(system="sys", user="user", schema=LabelInfo)
    assert resp.parsed is None
    assert "RuntimeError" in resp.error


def test_openai_client_built_with_timeout_and_no_retries(monkeypatch):
    # web_search runs are long; SDK retries compound the timeout (3x) and cost.
    # Build the client with the configured timeout and retries disabled — let
    # the SQS/worker layer own retry instead.
    import openai

    captured: dict = {}

    class _FakeClient:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr(openai, "OpenAI", _FakeClient)
    OpenAIAdapter(api_key="x", default_model="gpt-5", timeout_s=300.0)

    assert captured["api_key"] == "x"
    assert captured["timeout"] == 300.0
    assert captured["max_retries"] == 0

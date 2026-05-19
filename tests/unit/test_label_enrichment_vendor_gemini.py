from types import SimpleNamespace
from unittest.mock import MagicMock

from collector.label_enrichment.schemas import LabelInfo
from collector.label_enrichment.vendors.gemini import GeminiAdapter


def _fake_response(text: str, in_tok: int = 100, out_tok: int = 50) -> SimpleNamespace:
    usage = SimpleNamespace(prompt_token_count=in_tok, candidates_token_count=out_tok)
    return SimpleNamespace(text=text, usage_metadata=usage, candidates=[])


def test_gemini_parses_valid_payload():
    payload = (
        '{"label_name":"Drumcode","ai_reasoning":"none","summary":"techno","confidence":0.9}'
    )
    client = MagicMock()
    client.models.generate_content.return_value = _fake_response(payload)
    adapter = GeminiAdapter(api_key="x", default_model="gemini-3-flash-preview", client=client)

    resp = adapter.run(system="sys", user="user", schema=LabelInfo)

    assert resp.error is None
    assert resp.parsed.label_name == "Drumcode"
    assert resp.usage["input_tokens"] == 100
    assert resp.usage["output_tokens"] == 50
    assert resp.usage["cost_usd"] > 0.0


def test_gemini_returns_error_on_api_exception():
    client = MagicMock()
    client.models.generate_content.side_effect = RuntimeError("boom")
    adapter = GeminiAdapter(api_key="x", default_model="gemini-3-flash-preview", client=client)

    resp = adapter.run(system="sys", user="user", schema=LabelInfo)

    assert resp.parsed is None
    assert "RuntimeError" in resp.error
    assert resp.usage["cost_usd"] == 0.0


def test_gemini_handles_fenced_json():
    fenced = "```json\n{\"label_name\":\"X\",\"ai_reasoning\":\"r\",\"summary\":\"s\",\"confidence\":0.1}\n```"
    client = MagicMock()
    client.models.generate_content.return_value = _fake_response(fenced)
    adapter = GeminiAdapter(api_key="x", default_model="gemini-3-flash-preview", client=client)

    resp = adapter.run(system="sys", user="user", schema=LabelInfo)
    assert resp.error is None
    assert resp.parsed.label_name == "X"

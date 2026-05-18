import json
from types import SimpleNamespace
from unittest.mock import MagicMock

from collector.label_enrichment.schemas import LabelInfo
from collector.label_enrichment.vendors.tavily_deepseek import (
    TavilyDeepSeekAdapter,
    _build_search_query,
)


def test_search_query_extracts_quoted_label():
    user = 'Research label "Drumcode" in style "techno".\nFind: ...'
    assert _build_search_query(user) == '"Drumcode" techno music label'


def test_search_query_fallback_when_unquoted():
    assert _build_search_query("plain text") == "plain text"


def test_tavily_deepseek_happy_path():
    payload = {
        "label_name": "Drumcode",
        "ai_reasoning": "none",
        "summary": "Swedish techno",
        "confidence": 0.95,
    }
    tavily_resp = SimpleNamespace(
        raise_for_status=lambda: None,
        json=lambda: {"results": [{"url": "https://example.com", "title": "t", "content": "c"}]},
    )
    http = MagicMock()
    http.post.return_value = tavily_resp

    llm_resp = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(payload)))],
        usage=SimpleNamespace(prompt_tokens=300, completion_tokens=120),
    )
    llm = MagicMock()
    llm.chat.completions.create.return_value = llm_resp

    adapter = TavilyDeepSeekAdapter(
        tavily_api_key="t",
        deepseek_api_key="d",
        default_model="deepseek-v4-flash",
        http_client=http,
        llm_client=llm,
    )
    resp = adapter.run(system="sys", user='Research label "Drumcode" in style "techno".', schema=LabelInfo)

    assert resp.error is None
    assert resp.parsed.label_name == "Drumcode"
    assert resp.citations == ["https://example.com"]
    assert resp.usage["cost_usd"] > 0.0


def test_tavily_failure_returns_error_cell():
    http = MagicMock()
    http.post.side_effect = RuntimeError("network down")
    llm = MagicMock()
    adapter = TavilyDeepSeekAdapter(
        tavily_api_key="t",
        deepseek_api_key="d",
        default_model="deepseek-v4-flash",
        http_client=http,
        llm_client=llm,
    )
    resp = adapter.run(system="sys", user='Research label "X" in style "y".', schema=LabelInfo)
    assert resp.parsed is None
    assert "tavily error" in resp.error
    llm.chat.completions.create.assert_not_called()

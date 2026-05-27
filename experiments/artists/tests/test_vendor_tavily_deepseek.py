"""Tests for TavilyDeepSeekAdapter using httpx.MockTransport and MagicMock LLM."""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import MagicMock

import httpx
import pytest

from artlab.schemas import ArtistInfo
from artlab.vendors.tavily_deepseek import TavilyDeepSeekAdapter

_TAVILY_URL = "https://api.tavily.com/search"

_SAMPLE_RESULTS = [
    {"title": "Drumcode on RA", "url": "https://ra.co/labels/drumcode", "content": "Swedish techno label."},
    {"title": "Drumcode official", "url": "https://drumcode.se", "content": "Home of techno."},
    {"title": "Drumcode Discogs", "url": "https://discogs.com/label/drumcode", "content": "Discogs page."},
]

_SOCIAL_RESULTS = [
    {"title": "Drumcode YouTube", "url": "https://youtube.com/channel/drumcode", "content": "Official YouTube."},
]

_VALID_LABEL_JSON = json.dumps(
    {
        "artist_name": "Drumcode",
        "ai_reasoning": "No AI signals.",
        "summary": "Swedish techno label.",
        "confidence": 0.9,
        "sources": ["https://ra.co/labels/drumcode", "https://drumcode.se"],
    }
)


_VERBOSE_USER = (
    'Research label "Drumcode" in style "techno".\n'
    'Find: founding year, country, parent and sublabels, catalog and roster size, '
    'releases in the last 12 months, last release date, official channels '
    '(website, Bandcamp, Resident Advisor, Discogs, Beatport, SoundCloud), '
    'notable artists, distributor.\n'
    'Then assess AI-content status and explain your reasoning.'
)


def _tavily_ok_transport() -> httpx.MockTransport:
    """Handler that distinguishes general vs social pass by include_domains key."""
    general_body = json.dumps({"results": _SAMPLE_RESULTS}).encode()
    social_body = json.dumps({"results": _SOCIAL_RESULTS}).encode()

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        # The query must be a short focused form, not the verbose user prompt
        assert "Find: founding year" not in body["query"]
        assert '"Drumcode"' in body["query"] or "Drumcode" in body["query"]
        if "include_domains" in body:
            return httpx.Response(200, content=social_body, headers={"Content-Type": "application/json"})
        return httpx.Response(200, content=general_body, headers={"Content-Type": "application/json"})

    return httpx.MockTransport(handler)


def _tavily_error_transport() -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, content=b"internal error")

    return httpx.MockTransport(handler)


def _make_llm_client(content: str | None = None, side_effect: Exception | None = None) -> MagicMock:
    llm = MagicMock()
    if side_effect is not None:
        llm.chat.completions.create.side_effect = side_effect
    else:
        usage = SimpleNamespace(prompt_tokens=500, completion_tokens=200)
        message = SimpleNamespace(content=content)
        choice = SimpleNamespace(message=message)
        response = SimpleNamespace(choices=[choice], usage=usage)
        llm.chat.completions.create.return_value = response
    return llm


def _make_adapter(http_transport, llm_client) -> TavilyDeepSeekAdapter:
    http = httpx.Client(transport=http_transport, timeout=30.0)
    return TavilyDeepSeekAdapter(
        tavily_api_key="tav-key",
        deepseek_api_key="ds-key",
        default_model="deepseek-v4-flash",
        http_client=http,
        llm_client=llm_client,
    )


def test_happy_path():
    adapter = _make_adapter(
        http_transport=_tavily_ok_transport(),
        llm_client=_make_llm_client(content=_VALID_LABEL_JSON),
    )
    resp = adapter.run(system="sys", user=_VERBOSE_USER, schema=ArtistInfo)

    assert resp.error is None
    assert resp.parsed is not None
    assert resp.parsed.artist_name == "Drumcode"
    # General-pass citations
    assert "https://ra.co/labels/drumcode" in resp.citations
    assert "https://drumcode.se" in resp.citations
    # Social-pass citation merged in
    assert "https://youtube.com/channel/drumcode" in resp.citations
    assert len(resp.citations) == 4  # 3 general + 1 social (deduped)
    assert resp.usage["input_tokens"] == 500
    assert resp.usage["output_tokens"] == 200
    assert resp.model == "deepseek-v4-flash"


def test_tavily_http_error():
    adapter = _make_adapter(
        http_transport=_tavily_error_transport(),
        llm_client=_make_llm_client(content=_VALID_LABEL_JSON),
    )
    resp = adapter.run(system="sys", user="Drumcode techno label info", schema=ArtistInfo)

    assert resp.parsed is None
    assert resp.error is not None
    assert "tavily" in resp.error.lower()
    assert resp.usage == {"input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0}


def test_deepseek_exception():
    adapter = _make_adapter(
        http_transport=_tavily_ok_transport(),
        llm_client=_make_llm_client(side_effect=RuntimeError("connection refused")),
    )
    resp = adapter.run(system="sys", user="Drumcode techno label info", schema=ArtistInfo)

    assert resp.parsed is None
    assert resp.error is not None
    assert "deepseek" in resp.error.lower()
    # citations from tavily stage (general + social merged) should be present
    assert len(resp.citations) == 4


def test_bad_json_from_deepseek():
    adapter = _make_adapter(
        http_transport=_tavily_ok_transport(),
        llm_client=_make_llm_client(content="this is not json at all"),
    )
    resp = adapter.run(system="sys", user="Drumcode techno label info", schema=ArtistInfo)

    assert resp.parsed is None
    assert resp.error is not None
    assert "parse error" in resp.error
    # citations from tavily stage (general + social merged) should still be present
    assert len(resp.citations) == 4


def test_run_survives_social_pass_failure():
    """Second Tavily call fails — first-pass results still flow through."""
    call_count = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        if "include_domains" in body:
            return httpx.Response(500, text="oops")
        call_count["n"] += 1
        return httpx.Response(
            200,
            json={"results": [{"title": "General", "url": "https://general.example.com", "content": "info"}]},
            headers={"Content-Type": "application/json"},
        )

    transport = httpx.MockTransport(handler)
    http_client = httpx.Client(transport=transport, base_url="https://api.tavily.com")
    fake_llm = _make_llm_client(content=_VALID_LABEL_JSON)

    adapter = TavilyDeepSeekAdapter(
        tavily_api_key="t",
        deepseek_api_key="d",
        default_model="deepseek-v4-flash",
        http_client=http_client,
        llm_client=fake_llm,
    )
    resp = adapter.run(system="s", user="u", schema=ArtistInfo)
    assert resp.error is None
    assert "https://general.example.com" in resp.citations


def test_build_search_query_extracts_artist():
    from artlab.vendors.tavily_deepseek import _build_search_query

    user = (
        'Research the electronic-music artist "ANNA".\n'
        'Find: aliases and real name, country and city, years active...'
    )
    assert _build_search_query(user) == '"ANNA" music artist'


def test_build_search_query_includes_labels():
    from artlab.vendors.tavily_deepseek import _build_search_query

    user = (
        'Research the electronic-music artist "ANNA".\n'
        'Disambiguation context — this is the artist who released: Hidden Beauties; '
        'on labels: Drumcode, Kompakt; genre hint: techno.\n'
        'Find: aliases and real name...'
    )
    assert _build_search_query(user) == '"ANNA" Drumcode, Kompakt music artist'


def test_build_search_query_falls_back_for_unquoted():
    from artlab.vendors.tavily_deepseek import _build_search_query

    user = "no quoted strings here"
    assert _build_search_query(user) == user

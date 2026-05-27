from types import SimpleNamespace

import pytest

from artlab.schemas import ArtistInfo
from artlab.vendors.xai_grok import XAIGrokAdapter


def _valid_parsed() -> ArtistInfo:
    return ArtistInfo(
        artist_name="Drumcode",
        ai_reasoning="No AI signals.",
        summary="Swedish techno label.",
        confidence=0.9,
    )


def _mock_response(parsed: ArtistInfo | None, citations: list[str] | None = None) -> SimpleNamespace:
    usage = SimpleNamespace(input_tokens=400, output_tokens=300, total_tokens=700)
    return SimpleNamespace(
        output_parsed=parsed,
        output=[],
        usage=usage,
        model="grok-4",
        citations=citations or [],
    )


def test_run_returns_parsed(mocker):
    fake_client = mocker.MagicMock()
    fake_client.responses.parse.return_value = _mock_response(
        _valid_parsed(),
        citations=["https://example.com/a", "https://example.com/b"],
    )

    adapter = XAIGrokAdapter(api_key="x", default_model="grok-4", client=fake_client)
    resp = adapter.run(system="sys", user="usr", schema=ArtistInfo)

    assert resp.error is None
    assert resp.parsed.artist_name == "Drumcode"
    assert resp.citations == ["https://example.com/a", "https://example.com/b"]
    assert resp.usage["input_tokens"] == 400
    assert resp.usage["output_tokens"] == 300
    assert resp.usage["cost_usd"] > 0

    call = fake_client.responses.parse.call_args.kwargs
    assert call["model"] == "grok-4"
    assert call["instructions"] == "sys"
    assert call["input"] == [{"role": "user", "content": "usr"}]
    assert call["tools"] == [{"type": "web_search"}]
    assert call["text_format"] is ArtistInfo


def test_run_returns_error_when_no_parse(mocker):
    fake_client = mocker.MagicMock()
    fake_client.responses.parse.return_value = _mock_response(parsed=None)
    adapter = XAIGrokAdapter(api_key="x", default_model="grok-4", client=fake_client)
    resp = adapter.run(system="s", user="u", schema=ArtistInfo)
    assert resp.parsed is None
    assert "no output_parsed" in resp.error.lower()


def test_run_returns_error_on_exception(mocker):
    fake_client = mocker.MagicMock()
    fake_client.responses.parse.side_effect = RuntimeError("boom")
    adapter = XAIGrokAdapter(api_key="x", default_model="grok-4", client=fake_client)
    resp = adapter.run(system="s", user="u", schema=ArtistInfo)
    assert resp.parsed is None
    assert "boom" in resp.error

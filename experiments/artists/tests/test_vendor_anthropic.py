from types import SimpleNamespace

import pytest

from artlab.schemas import ArtistInfo
from artlab.vendors.anthropic_claude import AnthropicClaudeAdapter


def test_run_retries_on_rate_limit(mocker):
    class RateLimitError(Exception):
        def __init__(self, message: str = "429"):
            super().__init__(message)
            self.response = SimpleNamespace(headers={"retry-after": "0"})

    fake_client = mocker.MagicMock()
    fake_client.messages.create.side_effect = [
        RateLimitError(),
        RateLimitError(),
        _mock_response(_valid_payload()),
    ]
    mocker.patch("time.sleep")  # don't actually wait
    adapter = AnthropicClaudeAdapter(api_key="x", default_model="claude-sonnet-4-6", client=fake_client)
    resp = adapter.run(system="s", user="u", schema=ArtistInfo)
    assert resp.error is None
    assert resp.parsed.artist_name == "Drumcode"
    assert fake_client.messages.create.call_count == 3


def test_run_gives_up_after_max_retries(mocker):
    class RateLimitError(Exception):
        def __init__(self):
            super().__init__("429")
            self.response = SimpleNamespace(headers={"retry-after": "0"})

    fake_client = mocker.MagicMock()
    fake_client.messages.create.side_effect = RateLimitError()  # always fails
    mocker.patch("time.sleep")
    adapter = AnthropicClaudeAdapter(api_key="x", default_model="claude-sonnet-4-6", client=fake_client)
    resp = adapter.run(system="s", user="u", schema=ArtistInfo)
    assert resp.parsed is None
    assert resp.error is not None
    assert "RateLimitError" in resp.error or "429" in resp.error


def _mock_response(parsed_dict: dict) -> SimpleNamespace:
    """Mimic an anthropic.types.Message with a tool_use block."""
    tool_use = SimpleNamespace(
        type="tool_use",
        name="emit_artist_info",
        input=parsed_dict,
    )
    return SimpleNamespace(
        content=[tool_use],
        usage=SimpleNamespace(input_tokens=400, output_tokens=300),
        model="claude-sonnet-4-6",
        stop_reason="tool_use",
    )


def _valid_payload() -> dict:
    return {
        "artist_name": "Drumcode",
        "ai_reasoning": "No AI signals.",
        "summary": "Swedish techno label founded 1996.",
        "confidence": 0.9,
    }


def test_run_parses_tool_use(mocker):
    fake_client = mocker.MagicMock()
    fake_client.messages.create.return_value = _mock_response(_valid_payload())

    adapter = AnthropicClaudeAdapter(
        api_key="sk-test",
        default_model="claude-sonnet-4-6",
        client=fake_client,
    )
    resp = adapter.run(
        system="sys",
        user="usr",
        schema=ArtistInfo,
    )

    assert resp.error is None
    assert isinstance(resp.parsed, ArtistInfo)
    assert resp.parsed.artist_name == "Drumcode"
    assert resp.model == "claude-sonnet-4-6"
    assert resp.usage["input_tokens"] == 400
    assert resp.usage["output_tokens"] == 300
    assert resp.usage["cost_usd"] > 0
    fake_client.messages.create.assert_called_once()
    call = fake_client.messages.create.call_args.kwargs
    assert call["system"] == "sys"
    assert call["messages"][0]["content"] == "usr"
    assert any(t.get("name") == "web_search" for t in call["tools"])
    assert any(t.get("name") == "emit_artist_info" for t in call["tools"])


def test_run_uses_model_override(mocker):
    fake_client = mocker.MagicMock()
    fake_client.messages.create.return_value = _mock_response(_valid_payload())
    adapter = AnthropicClaudeAdapter(
        api_key="sk-test",
        default_model="claude-sonnet-4-6",
        client=fake_client,
    )
    adapter.run(system="s", user="u", schema=ArtistInfo, model="claude-opus-4-7")
    call = fake_client.messages.create.call_args.kwargs
    assert call["model"] == "claude-opus-4-7"


def test_run_returns_error_on_exception(mocker):
    fake_client = mocker.MagicMock()
    fake_client.messages.create.side_effect = RuntimeError("boom")
    adapter = AnthropicClaudeAdapter(
        api_key="sk-test",
        default_model="claude-sonnet-4-6",
        client=fake_client,
    )
    resp = adapter.run(system="s", user="u", schema=ArtistInfo)
    assert resp.parsed is None
    assert "boom" in resp.error
    assert resp.usage["cost_usd"] == 0.0


def test_run_returns_error_when_no_tool_use(mocker):
    fake_client = mocker.MagicMock()
    text_block = SimpleNamespace(type="text", text="no tool call")
    fake_client.messages.create.return_value = SimpleNamespace(
        content=[text_block],
        usage=SimpleNamespace(input_tokens=1, output_tokens=1),
        model="claude-sonnet-4-6",
        stop_reason="end_turn",
    )
    adapter = AnthropicClaudeAdapter(
        api_key="sk-test",
        default_model="claude-sonnet-4-6",
        client=fake_client,
    )
    resp = adapter.run(system="s", user="u", schema=ArtistInfo)
    assert resp.parsed is None
    assert "no tool_use" in resp.error.lower()


def test_run_retries_on_connection_error(mocker):
    class APIConnectionError(Exception):
        def __init__(self):
            super().__init__("Connection error.")

    fake_client = mocker.MagicMock()
    fake_client.messages.create.side_effect = [
        APIConnectionError(),
        _mock_response(_valid_payload()),
    ]
    mocker.patch("time.sleep")
    adapter = AnthropicClaudeAdapter(
        api_key="x", default_model="claude-sonnet-4-6", client=fake_client
    )
    resp = adapter.run(system="s", user="u", schema=ArtistInfo)
    assert resp.error is None
    assert fake_client.messages.create.call_count == 2


def test_run_returns_error_on_validation_failure(mocker):
    """Malformed tool_use input must NOT crash the adapter."""
    fake_client = mocker.MagicMock()
    tool_use = SimpleNamespace(
        type="tool_use",
        name="emit_artist_info",
        input={"artist_name": "x"},  # missing required ai_reasoning/summary/confidence
    )
    fake_client.messages.create.return_value = SimpleNamespace(
        content=[tool_use],
        usage=SimpleNamespace(input_tokens=10, output_tokens=20),
        model="claude-sonnet-4-6",
        stop_reason="tool_use",
    )
    adapter = AnthropicClaudeAdapter(
        api_key="sk-test",
        default_model="claude-sonnet-4-6",
        client=fake_client,
    )
    resp = adapter.run(system="s", user="u", schema=ArtistInfo)
    assert resp.parsed is None
    assert resp.error is not None
    assert "parse error" in resp.error.lower()

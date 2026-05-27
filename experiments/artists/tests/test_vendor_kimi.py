"""Tests for KimiAdapter using an injected fake OpenAI-compatible client."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from artlab.schemas import ArtistInfo
from artlab.vendors.kimi_k2 import KimiAdapter


# ---------------------------------------------------------------------------
# Helpers to build fake OpenAI-style chat.completions responses
# ---------------------------------------------------------------------------

def _tool_call(call_id: str, name: str, arguments: dict) -> SimpleNamespace:
    """Create a fake tool_call object."""
    return SimpleNamespace(
        id=call_id,
        function=SimpleNamespace(
            name=name,
            arguments=json.dumps(arguments),
        ),
    )


def _tool_calls_response(tool_calls: list, model: str = "kimi-k2.6") -> SimpleNamespace:
    """Fake response with finish_reason='tool_calls'."""
    usage = SimpleNamespace(prompt_tokens=200, completion_tokens=50, total_tokens=250)
    choice = SimpleNamespace(
        finish_reason="tool_calls",
        message=SimpleNamespace(
            content=None,
            tool_calls=tool_calls,
        ),
    )
    return SimpleNamespace(choices=[choice], usage=usage, model=model)


def _stop_response(content: str, model: str = "kimi-k2.6") -> SimpleNamespace:
    """Fake response with finish_reason='stop'."""
    usage = SimpleNamespace(prompt_tokens=400, completion_tokens=180, total_tokens=580)
    choice = SimpleNamespace(
        finish_reason="stop",
        message=SimpleNamespace(content=content, tool_calls=None),
    )
    return SimpleNamespace(choices=[choice], usage=usage, model=model)


def _valid_artist_json() -> str:
    return json.dumps({
        "artist_name": "Drumcode",
        "ai_reasoning": "No AI signals detected.",
        "summary": "Swedish techno label founded by Adam Beyer.",
        "confidence": 0.95,
    })


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_run_with_web_search_loop(mocker):
    """Happy path: first call returns tool_calls, second returns stop with JSON."""
    tc = _tool_call("tc-001", "$web_search", {"query": "Drumcode label info"})
    first_response = _tool_calls_response([tc])
    second_response = _stop_response(_valid_artist_json())

    fake_completions = mocker.MagicMock()
    fake_completions.create.side_effect = [first_response, second_response]

    fake_client = mocker.MagicMock()
    fake_client.chat.completions = fake_completions

    adapter = KimiAdapter(api_key="test-key", default_model="kimi-k2.6", client=fake_client)
    resp = adapter.run(system="sys", user="usr", schema=ArtistInfo)

    # Should have called create twice (one tool-call round, then the final answer).
    assert fake_completions.create.call_count == 2
    assert resp.error is None
    assert resp.parsed is not None
    assert resp.parsed.artist_name == "Drumcode"
    assert resp.parsed.confidence == pytest.approx(0.95)
    assert resp.model == "kimi-k2.6"
    assert resp.usage["input_tokens"] > 0
    assert resp.usage["output_tokens"] > 0

    # Verify the second call includes the tool result message in messages.
    second_call_messages = fake_completions.create.call_args_list[1].kwargs["messages"]
    tool_messages = [m for m in second_call_messages if isinstance(m, dict) and m.get("role") == "tool"]
    assert len(tool_messages) == 1
    assert tool_messages[0]["tool_call_id"] == "tc-001"
    assert tool_messages[0]["name"] == "$web_search"
    # Content is the JSON-serialised arguments echoed back.
    assert json.loads(tool_messages[0]["content"]) == {"query": "Drumcode label info"}


def test_run_no_search_stop_immediately(mocker):
    """When the model answers directly (finish_reason=stop on first call), no loop needed."""
    response = _stop_response(_valid_artist_json())

    fake_completions = mocker.MagicMock()
    fake_completions.create.return_value = response

    fake_client = mocker.MagicMock()
    fake_client.chat.completions = fake_completions

    adapter = KimiAdapter(api_key="test-key", default_model="kimi-k2.6", client=fake_client)
    resp = adapter.run(system="sys", user="usr", schema=ArtistInfo)

    # Only one create call — no tool-call loop needed.
    assert fake_completions.create.call_count == 1
    assert resp.error is None
    assert resp.parsed.artist_name == "Drumcode"


def test_run_captures_error_on_api_exception(mocker):
    """Exceptions from the API are captured into VendorResponse.error — never raised."""
    fake_completions = mocker.MagicMock()
    fake_completions.create.side_effect = RuntimeError("connection refused")

    fake_client = mocker.MagicMock()
    fake_client.chat.completions = fake_completions

    adapter = KimiAdapter(api_key="test-key", default_model="kimi-k2.6", client=fake_client)
    resp = adapter.run(system="sys", user="usr", schema=ArtistInfo)

    assert resp.parsed is None
    assert resp.error is not None
    assert "connection refused" in resp.error
    assert resp.usage["cost_usd"] == 0.0


def test_run_captures_parse_error(mocker):
    """Malformed JSON in the final response is captured as a parse error."""
    response = _stop_response("not valid json at all")

    fake_completions = mocker.MagicMock()
    fake_completions.create.return_value = response

    fake_client = mocker.MagicMock()
    fake_client.chat.completions = fake_completions

    adapter = KimiAdapter(api_key="test-key", default_model="kimi-k2.6", client=fake_client)
    resp = adapter.run(system="sys", user="usr", schema=ArtistInfo)

    assert resp.parsed is None
    assert resp.error is not None
    assert "parse error" in resp.error.lower()


def test_run_extracts_json_from_fenced_content(mocker):
    """JSON wrapped in markdown fences is extracted and parsed correctly."""
    fenced = f"Sure! Here is the result:\n```json\n{_valid_artist_json()}\n```"
    response = _stop_response(fenced)

    fake_completions = mocker.MagicMock()
    fake_completions.create.return_value = response

    fake_client = mocker.MagicMock()
    fake_client.chat.completions = fake_completions

    adapter = KimiAdapter(api_key="test-key", default_model="kimi-k2.6", client=fake_client)
    resp = adapter.run(system="sys", user="usr", schema=ArtistInfo)

    assert resp.error is None
    assert resp.parsed.artist_name == "Drumcode"


def test_run_tools_in_api_call(mocker):
    """The $web_search builtin tool is passed as tools in every API call."""
    response = _stop_response(_valid_artist_json())

    fake_completions = mocker.MagicMock()
    fake_completions.create.return_value = response

    fake_client = mocker.MagicMock()
    fake_client.chat.completions = fake_completions

    adapter = KimiAdapter(api_key="test-key", default_model="kimi-k2.6", client=fake_client)
    adapter.run(system="sys", user="usr", schema=ArtistInfo)

    call_kwargs = fake_completions.create.call_args.kwargs
    assert call_kwargs["model"] == "kimi-k2.6"
    tools = call_kwargs["tools"]
    assert len(tools) == 1
    assert tools[0]["type"] == "builtin_function"
    assert tools[0]["function"]["name"] == "$web_search"


def test_run_accumulates_tokens_across_loop_iterations(mocker):
    """Token counts from all loop iterations are summed."""
    tc = _tool_call("tc-002", "$web_search", {"query": "test"})
    first_response = _tool_calls_response([tc])   # 200 input + 50 output
    second_response = _stop_response(_valid_artist_json())  # 400 input + 180 output

    fake_completions = mocker.MagicMock()
    fake_completions.create.side_effect = [first_response, second_response]

    fake_client = mocker.MagicMock()
    fake_client.chat.completions = fake_completions

    adapter = KimiAdapter(api_key="test-key", default_model="kimi-k2.6", client=fake_client)
    resp = adapter.run(system="sys", user="usr", schema=ArtistInfo)

    assert resp.usage["input_tokens"] == 600   # 200 + 400
    assert resp.usage["output_tokens"] == 230  # 50 + 180
    assert resp.usage["cost_usd"] > 0

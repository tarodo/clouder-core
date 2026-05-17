from types import SimpleNamespace

import pytest

from lab.schemas import LabelInfo
from lab.vendors.anthropic_claude import AnthropicClaudeAdapter


def _mock_response(parsed_dict: dict) -> SimpleNamespace:
    """Mimic an anthropic.types.Message with a tool_use block."""
    tool_use = SimpleNamespace(
        type="tool_use",
        name="emit_label_info",
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
        "label_name": "Drumcode",
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
        schema=LabelInfo,
    )

    assert resp.error is None
    assert isinstance(resp.parsed, LabelInfo)
    assert resp.parsed.label_name == "Drumcode"
    assert resp.model == "claude-sonnet-4-6"
    assert resp.usage["input_tokens"] == 400
    assert resp.usage["output_tokens"] == 300
    assert resp.usage["cost_usd"] > 0
    fake_client.messages.create.assert_called_once()
    call = fake_client.messages.create.call_args.kwargs
    assert call["system"] == "sys"
    assert call["messages"][0]["content"] == "usr"
    assert any(t.get("name") == "web_search" for t in call["tools"])
    assert any(t.get("name") == "emit_label_info" for t in call["tools"])


def test_run_uses_model_override(mocker):
    fake_client = mocker.MagicMock()
    fake_client.messages.create.return_value = _mock_response(_valid_payload())
    adapter = AnthropicClaudeAdapter(
        api_key="sk-test",
        default_model="claude-sonnet-4-6",
        client=fake_client,
    )
    adapter.run(system="s", user="u", schema=LabelInfo, model="claude-opus-4-7")
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
    resp = adapter.run(system="s", user="u", schema=LabelInfo)
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
    resp = adapter.run(system="s", user="u", schema=LabelInfo)
    assert resp.parsed is None
    assert "no tool_use" in resp.error.lower()


def test_run_returns_error_on_validation_failure(mocker):
    """Malformed tool_use input must NOT crash the adapter."""
    fake_client = mocker.MagicMock()
    tool_use = SimpleNamespace(
        type="tool_use",
        name="emit_label_info",
        input={"label_name": "x"},  # missing required ai_reasoning/summary/confidence
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
    resp = adapter.run(system="s", user="u", schema=LabelInfo)
    assert resp.parsed is None
    assert resp.error is not None
    assert "parse error" in resp.error.lower()

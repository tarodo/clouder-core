"""Tests for GeminiFlashAdapter using injected fake clients."""

from __future__ import annotations

import json
from types import SimpleNamespace

from lab.schemas import LabelInfo
from lab.vendors.gemini_flash import GeminiFlashAdapter


def _valid_json() -> str:
    return json.dumps(
        {
            "label_name": "Drumcode",
            "ai_reasoning": "No AI signals.",
            "summary": "Swedish techno label.",
            "confidence": 0.9,
            "sources": [],
        }
    )


def _make_grounding_chunk(uri: str) -> SimpleNamespace:
    web = SimpleNamespace(uri=uri)
    return SimpleNamespace(web=web)


def _mock_response(text: str, citations: list[str] | None = None) -> SimpleNamespace:
    usage_meta = SimpleNamespace(prompt_token_count=400, candidates_token_count=300)
    grounding_chunks = [_make_grounding_chunk(u) for u in (citations or [])]
    grounding_metadata = SimpleNamespace(grounding_chunks=grounding_chunks)
    candidate = SimpleNamespace(grounding_metadata=grounding_metadata)
    return SimpleNamespace(
        text=text,
        usage_metadata=usage_meta,
        candidates=[candidate],
    )


def test_run_happy_path():
    valid_text = _valid_json()
    fake_response = _mock_response(
        text=valid_text,
        citations=["https://drumcode.se", "https://ra.co/labels/drumcode"],
    )

    class FakeModels:
        def generate_content(self, **kwargs):
            return fake_response

    fake_client = SimpleNamespace(models=FakeModels())

    adapter = GeminiFlashAdapter(
        api_key="test-key",
        default_model="gemini-2.5-flash",
        client=fake_client,
    )
    resp = adapter.run(system="sys", user="usr", schema=LabelInfo)

    assert resp.error is None
    assert resp.parsed is not None
    assert resp.parsed.label_name == "Drumcode"
    assert resp.citations == ["https://drumcode.se", "https://ra.co/labels/drumcode"]
    assert resp.usage["input_tokens"] == 400
    assert resp.usage["output_tokens"] == 300
    assert resp.model == "gemini-2.5-flash"


def test_run_bad_json():
    fake_response = _mock_response(text="not-valid-json")

    class FakeModels:
        def generate_content(self, **kwargs):
            return fake_response

    fake_client = SimpleNamespace(models=FakeModels())

    adapter = GeminiFlashAdapter(
        api_key="test-key",
        default_model="gemini-2.5-flash",
        client=fake_client,
    )
    resp = adapter.run(system="sys", user="usr", schema=LabelInfo)

    assert resp.parsed is None
    assert resp.error is not None
    assert "parse error" in resp.error


def test_run_exception_path():
    class FakeModels:
        def generate_content(self, **kwargs):
            raise RuntimeError("network failure")

    fake_client = SimpleNamespace(models=FakeModels())

    adapter = GeminiFlashAdapter(
        api_key="test-key",
        default_model="gemini-2.5-flash",
        client=fake_client,
    )
    resp = adapter.run(system="sys", user="usr", schema=LabelInfo)

    assert resp.parsed is None
    assert resp.error is not None
    assert "network failure" in resp.error
    assert resp.usage == {"input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0}

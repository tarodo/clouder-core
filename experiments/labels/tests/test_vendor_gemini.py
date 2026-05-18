"""Tests for GeminiFlashAdapter using injected fake clients."""

from __future__ import annotations

import json
from types import SimpleNamespace

from lab.schemas import LabelInfo
from lab.vendors.gemini_flash import GeminiFlashAdapter


def _valid_payload_text() -> str:
    return json.dumps(
        {
            "label_name": "Drumcode",
            "ai_reasoning": "No AI signals.",
            "summary": "Swedish techno label.",
            "confidence": 0.9,
            "sources": [],
        }
    )


def _valid_json() -> str:
    return _valid_payload_text()


def _make_grounding_chunk(uri: str) -> SimpleNamespace:
    web = SimpleNamespace(uri=uri)
    return SimpleNamespace(web=web)


def _mock_response(
    text: str,
    citations: list[str] | None = None,
    grounding_uris: list[str] | None = None,
) -> SimpleNamespace:
    # `grounding_uris` is an alias for `citations`; whichever is provided wins.
    uris = grounding_uris if grounding_uris is not None else (citations or [])
    usage_meta = SimpleNamespace(prompt_token_count=400, candidates_token_count=300)
    grounding_chunks = [_make_grounding_chunk(u) for u in uris]
    grounding_metadata = SimpleNamespace(grounding_chunks=grounding_chunks)
    candidate = SimpleNamespace(grounding_metadata=grounding_metadata)
    return SimpleNamespace(
        text=text,
        usage_metadata=usage_meta,
        candidates=[candidate],
    )


def test_run_happy_path():
    # Wrap JSON in markdown fences to prove _extract_json works end to end
    fenced_text = f"```json\n{_valid_json()}\n```"
    fake_response = _mock_response(
        text=fenced_text,
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


def test_run_retries_on_unavailable(mocker):
    """503 UNAVAILABLE errors are retried with exponential backoff."""

    class ServerError(Exception):
        pass

    unavailable_err = ServerError(
        "503 UNAVAILABLE. {'error': {'code': 503, 'message': 'This model is currently experiencing high demand.'}}"
    )

    fake_client = mocker.MagicMock()
    fake_client.models.generate_content.side_effect = [
        unavailable_err,
        unavailable_err,
        _mock_response(_valid_payload_text()),
    ]
    mocker.patch("time.sleep")
    adapter = GeminiFlashAdapter(
        api_key="x", default_model="gemini-2.5-flash", client=fake_client
    )
    resp = adapter.run(system="s", user="u", schema=LabelInfo)
    assert resp.error is None
    assert fake_client.models.generate_content.call_count == 3


def test_run_retries_on_quota_exhausted(mocker):
    """Quota errors are retried; success on the third attempt counts as ok."""

    class ClientError(Exception):
        pass

    quota_err = ClientError(
        "429 RESOURCE_EXHAUSTED. {'error': ..., 'details': [{'@type': 'RetryInfo', 'retryDelay': '0s'}]}"
    )

    fake_client = mocker.MagicMock()
    fake_client.models.generate_content.side_effect = [
        quota_err,
        quota_err,
        _mock_response(_valid_payload_text()),
    ]
    mocker.patch("time.sleep")

    adapter = GeminiFlashAdapter(
        api_key="x", default_model="gemini-2.5-flash", client=fake_client
    )
    resp = adapter.run(system="s", user="u", schema=LabelInfo)

    assert resp.error is None
    assert resp.parsed is not None
    assert resp.parsed.label_name == "Drumcode"
    assert fake_client.models.generate_content.call_count == 3


def test_run_falls_back_to_parsed_sources_for_citations(mocker):
    """When grounding_metadata has no URLs, copy parsed.sources into citations."""
    fake_client = mocker.MagicMock()
    # Response with empty grounding_chunks but populated `sources` in the JSON
    payload_json = json.dumps({
        "label_name": "Hessle Audio",
        "ai_reasoning": "—",
        "summary": "UK label",
        "confidence": 0.9,
        "sources": ["https://example.com/a", "https://example.com/b"],
    })
    fake_client.models.generate_content.return_value = _mock_response(
        payload_json,
        grounding_uris=[],  # no grounding chunks
    )
    adapter = GeminiFlashAdapter(
        api_key="x", default_model="gemini-2.5-flash", client=fake_client
    )
    resp = adapter.run(system="s", user="u", schema=LabelInfo)
    assert resp.error is None
    assert resp.citations == ["https://example.com/a", "https://example.com/b"]

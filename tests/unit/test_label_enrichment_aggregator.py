import json
from types import SimpleNamespace
from unittest.mock import MagicMock

from collector.label_enrichment.aggregator import (
    merge_cells,
    _filter_parseable,
    _merge_deterministic,
)


def _cell(vendor: str, parsed: dict | None, error: str | None = None) -> dict:
    return {
        "run_id": "r",
        "prompt": {"slug": "label_v3_app_fields", "version": "v1"},
        "vendor": {"name": vendor, "model": f"{vendor}-model"},
        "fixture": {"label_name": parsed.get("label_name", "") if parsed else ""},
        "response": {
            "parsed": parsed,
            "citations": [],
            "usage": {"input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0},
            "latency_ms": 100,
            "raw": {},
        },
        "error": error,
    }


def _base_parsed(**over) -> dict:
    base = {
        "label_name": "Drumcode",
        "ai_reasoning": "none",
        "summary": "techno",
        "confidence": 0.9,
        "country": "Sweden",
        "founded_year": 1996,
        "primary_styles": ["techno"],
        "notable_artists": ["Adam Beyer"],
        "ai_content": "none_detected",
        "status": "active",
        "activity": "steady",
    }
    base.update(over)
    return base


def _fake_deepseek_client(payload: dict):
    client = MagicMock()
    client.chat.completions.create.return_value = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(payload)))],
        usage=SimpleNamespace(prompt_tokens=300, completion_tokens=120),
    )
    return client


def test_filter_parseable_drops_errors_and_nulls():
    cells = [
        _cell("gemini", _base_parsed()),
        _cell("openai", None, error="boom"),
        _cell("tavily_deepseek", None),
    ]
    assert len(_filter_parseable(cells)) == 1


def test_deterministic_median_numeric():
    cells = [
        _cell("gemini", _base_parsed(founded_year=1996, catalog_size_estimate=500)),
        _cell("openai", _base_parsed(founded_year=1996, catalog_size_estimate=600)),
    ]
    merged, prov = _merge_deterministic(cells)
    assert merged["founded_year"] == 1996
    assert merged["catalog_size_estimate"] == 550
    assert prov["catalog_size_estimate"].startswith("median:")


def test_majority_with_unknown_abstention():
    cells = [
        _cell("gemini", _base_parsed(status="active")),
        _cell("openai", _base_parsed(status="unknown")),
        _cell("tavily_deepseek", _base_parsed(status="active")),
    ]
    merged, prov = _merge_deterministic(cells)
    assert merged["status"] == "active"
    assert "majority" in prov["status"] or "only definitive" in prov["status"]


def test_merge_cells_single_source_short_circuit():
    cells = [_cell("gemini", _base_parsed())]
    client = _fake_deepseek_client({})  # should NOT be called
    info, meta = merge_cells(cells, client)
    assert info.label_name == "Drumcode"
    assert meta["source_count"] == 1
    client.chat.completions.create.assert_not_called()


def test_merge_cells_multiple_sources_runs_narrative():
    cells = [
        _cell("gemini", _base_parsed()),
        _cell("openai", _base_parsed(summary="alt")),
    ]
    client = _fake_deepseek_client({
        "tagline": "Tag.",
        "summary": "Merged summary.",
        "ai_reasoning": "merged reasoning",
        "notes": None,
    })
    info, meta = merge_cells(cells, client)
    assert info.summary == "Merged summary."
    assert meta["source_count"] == 2
    assert "deepseek narrative" in meta["field_provenance"]["summary"]


def test_merge_cells_narrative_failure_falls_back():
    cells = [
        _cell("gemini", _base_parsed(confidence=0.9)),
        _cell("openai", _base_parsed(confidence=0.7, summary="LOW")),
    ]
    client = MagicMock()
    client.chat.completions.create.side_effect = RuntimeError("deepseek down")
    info, meta = merge_cells(cells, client)
    assert info.summary == "techno"  # max-confidence cell's summary
    assert meta.get("narrative_fallback") == "max_confidence"


def test_merge_cells_all_failed():
    cells = [
        _cell("gemini", None, error="boom"),
        _cell("openai", None, error="boom"),
    ]
    client = MagicMock()
    info, meta = merge_cells(cells, client)
    assert info.summary == "All vendor sources failed."
    assert meta["all_failed"] is True
    client.chat.completions.create.assert_not_called()

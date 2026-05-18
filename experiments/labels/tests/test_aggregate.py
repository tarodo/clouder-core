"""Tests for lab.aggregate."""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from lab.aggregate import (
    _filter_parseable,
    _merge_deterministic,
    merge_cells,
)
from lab.schemas import AIContentStatus, ActivityLevel, LabelInfo


def _cell(vendor: str, model: str, parsed: dict | None = None, error: str | None = None) -> dict:
    """Build a synthetic cell JSON for tests."""
    return {
        "run_id": "test-run",
        "prompt": {"slug": "label_v3_app_fields", "version": "v1"},
        "vendor": {"name": vendor, "model": model},
        "fixture": {"id": "drumcode", "label_name": "Drumcode", "style": "techno", "release_name": None},
        "rendered_user_prompt": "...",
        "response": {
            "parsed": parsed,
            "citations": [],
            "usage": {"input_tokens": 100, "output_tokens": 200, "cost_usd": 0.001},
            "latency_ms": 1234,
            "raw": {},
        },
        "error": error,
    }


def _parsed(**overrides) -> dict:
    """Build a synthetic LabelInfo dump with sensible defaults."""
    base = {
        "label_name": "Drumcode",
        "aliases": [],
        "parent_label": None,
        "sublabels": [],
        "country": "Sweden",
        "founded_year": 1996,
        "status": "active",
        "logo_url": None,
        "tagline": None,
        "catalog_size_estimate": None,
        "roster_size_estimate": None,
        "releases_last_12_months": None,
        "last_release_date": None,
        "activity": "unknown",
        "website": None,
        "bandcamp_url": None,
        "residentadvisor_url": None,
        "discogs_url": None,
        "beatport_url": None,
        "soundcloud_url": None,
        "instagram_url": None,
        "twitter_url": None,
        "notable_artists": [],
        "primary_styles": [],
        "distribution": None,
        "ai_content": "none_detected",
        "ai_signals": [],
        "ai_reasoning": "n/a",
        "summary": "Swedish techno label.",
        "confidence": 0.9,
        "sources": [],
        "notes": None,
    }
    base.update(overrides)
    return base


def test_filter_parseable_drops_errored_and_none_parsed():
    cells = [
        _cell("a", "ma", parsed=_parsed()),
        _cell("b", "mb", parsed=None, error="boom"),
        _cell("c", "mc", parsed=None),
        _cell("d", "md", parsed=_parsed(country="Norway"), error=None),
    ]
    filtered = _filter_parseable(cells)
    assert len(filtered) == 2
    assert filtered[0]["vendor"]["name"] == "a"
    assert filtered[1]["vendor"]["name"] == "d"


def test_merge_deterministic_numeric_median():
    cells = [
        _cell("a", "ma", parsed=_parsed(founded_year=1995, releases_last_12_months=20)),
        _cell("b", "mb", parsed=_parsed(founded_year=1996, releases_last_12_months=30)),
        _cell("c", "mc", parsed=_parsed(founded_year=1997, releases_last_12_months=None)),
    ]
    merged, prov = _merge_deterministic(cells)
    assert merged["founded_year"] == 1996
    assert prov["founded_year"] == "median:1996"
    assert merged["releases_last_12_months"] == 25  # median of [20, 30]
    assert prov["releases_last_12_months"] == "median:25"


def test_merge_deterministic_enum_majority():
    cells = [
        _cell("a", "ma", parsed=_parsed(activity="high", confidence=0.9)),
        _cell("b", "mb", parsed=_parsed(activity="high", confidence=0.7)),
        _cell("c", "mc", parsed=_parsed(activity="steady", confidence=1.0)),
    ]
    merged, prov = _merge_deterministic(cells)
    assert merged["activity"] == "high"
    assert prov["activity"].startswith("majority")


def test_merge_deterministic_enum_tie_breaks_on_confidence():
    cells = [
        _cell("a", "ma", parsed=_parsed(activity="high", confidence=0.8)),
        _cell("b", "mb", parsed=_parsed(activity="steady", confidence=0.95)),
    ]
    merged, prov = _merge_deterministic(cells)
    assert merged["activity"] == "steady"  # higher confidence wins on tie
    assert "tie" in prov["activity"]


def test_merge_deterministic_country_short_wins_tie():
    cells = [
        _cell("a", "ma", parsed=_parsed(country="United Kingdom")),
        _cell("b", "mb", parsed=_parsed(country="GB")),
    ]
    merged, prov = _merge_deterministic(cells)
    assert merged["country"] == "GB"
    assert "shortest" in prov["country"]


def test_merge_deterministic_list_union_top5_notable_artists():
    cells = [
        _cell("a", "ma", parsed=_parsed(notable_artists=["Adam Beyer", "Amelie Lens", "ANNA"])),
        _cell("b", "mb", parsed=_parsed(notable_artists=["Adam Beyer", "Alan Fitzpatrick", "Bart Skils", "Amelie Lens"])),
        _cell("c", "mc", parsed=_parsed(notable_artists=["Adam Beyer", "Layton Giordani"])),
    ]
    merged, prov = _merge_deterministic(cells)
    artists = merged["notable_artists"]
    assert "Adam Beyer" == artists[0]  # most frequent first
    assert "Amelie Lens" in artists
    assert len(artists) <= 5
    assert "union top-5" in prov["notable_artists"]


def test_merge_deterministic_url_max_confidence_wins():
    cells = [
        _cell("a", "ma", parsed=_parsed(bandcamp_url=None, confidence=0.95)),
        _cell("b", "mb", parsed=_parsed(bandcamp_url="https://drumcode.bandcamp.com/", confidence=0.7)),
        _cell("c", "mc", parsed=_parsed(bandcamp_url="https://drumcode.bandcamp.com", confidence=0.8)),
    ]
    merged, prov = _merge_deterministic(cells)
    assert merged["bandcamp_url"] == "https://drumcode.bandcamp.com"  # from cell c
    assert "highest confidence" in prov["bandcamp_url"]


def test_merge_deterministic_confidence_mean():
    cells = [
        _cell("a", "ma", parsed=_parsed(confidence=0.8)),
        _cell("b", "mb", parsed=_parsed(confidence=1.0)),
        _cell("c", "mc", parsed=_parsed(confidence=0.6)),
    ]
    merged, prov = _merge_deterministic(cells)
    assert merged["confidence"] == pytest.approx(0.8)
    assert prov["confidence"].startswith("mean")


def _mock_deepseek_response(content: str, prompt_tokens: int = 800, completion_tokens: int = 300):
    """Mimic openai SDK chat.completions.create return value."""
    msg = SimpleNamespace(content=content)
    choice = SimpleNamespace(message=msg, finish_reason="stop")
    usage = SimpleNamespace(
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=prompt_tokens + completion_tokens,
    )
    return SimpleNamespace(choices=[choice], usage=usage, model="deepseek-v4-flash")


def test_merge_cells_narrative_through_deepseek():
    payload = {
        "tagline": "Swedish techno powerhouse since 1996.",
        "summary": "Drumcode is a Swedish techno label founded in 1996 by Adam Beyer. It is widely respected for peak-time techno.",
        "ai_reasoning": "No AI signals across multiple vendors.",
        "notes": None,
    }
    fake_deepseek = MagicMock()
    fake_deepseek.chat.completions.create.return_value = _mock_deepseek_response(
        json.dumps(payload)
    )

    cells = [
        _cell("a", "ma", parsed=_parsed(
            tagline="Swedish techno legend.",
            summary="Drumcode, Swedish techno.",
            ai_reasoning="-",
            confidence=0.9,
        )),
        _cell("b", "mb", parsed=_parsed(
            tagline="Peak-time techno from Sweden.",
            summary="Founded 1996 by Adam Beyer.",
            ai_reasoning="-",
            confidence=0.95,
        )),
    ]

    merged, meta = merge_cells(cells, fake_deepseek, deepseek_model="deepseek-v4-flash")
    assert isinstance(merged, LabelInfo)
    assert merged.tagline == "Swedish techno powerhouse since 1996."
    assert "Adam Beyer" in merged.summary
    assert merged.country == "Sweden"
    assert merged.founded_year == 1996
    assert meta["narrative_cost_usd"] > 0
    assert meta["narrative_latency_ms"] >= 0
    assert "field_provenance" in meta
    assert meta["field_provenance"]["tagline"] == "deepseek narrative"
    fake_deepseek.chat.completions.create.assert_called_once()


def test_merge_cells_narrative_fallback_on_deepseek_error():
    fake_deepseek = MagicMock()
    fake_deepseek.chat.completions.create.side_effect = RuntimeError("boom")
    cells = [
        _cell("a", "ma", parsed=_parsed(
            tagline="Low-confidence tagline.",
            summary="Low-conf summary.",
            ai_reasoning="low",
            confidence=0.4,
        )),
        _cell("b", "mb", parsed=_parsed(
            tagline="High-confidence tagline.",
            summary="High-conf summary.",
            ai_reasoning="high",
            confidence=0.95,
        )),
    ]
    merged, meta = merge_cells(cells, fake_deepseek, deepseek_model="deepseek-v4-flash")
    assert merged.tagline == "High-confidence tagline."
    assert merged.summary == "High-conf summary."
    assert meta["narrative_fallback"] == "max_confidence"


def test_merge_cells_single_source_skips_deepseek():
    fake_deepseek = MagicMock()
    cells = [_cell("a", "ma", parsed=_parsed(summary="Single-source summary.", tagline="Single."))]
    merged, meta = merge_cells(cells, fake_deepseek)
    assert merged.summary == "Single-source summary."
    assert merged.tagline == "Single."
    assert meta["single_source"] is True
    assert meta["narrative_cost_usd"] == 0.0
    fake_deepseek.chat.completions.create.assert_not_called()


def test_merge_cells_all_failed_returns_placeholder():
    fake_deepseek = MagicMock()
    cells = [
        _cell("a", "ma", parsed=None, error="boom"),
        _cell("b", "mb", parsed=None),
    ]
    merged, meta = merge_cells(cells, fake_deepseek)
    assert merged.summary == "All vendor sources failed."
    assert merged.confidence == 0.0
    assert meta["all_failed"] is True
    fake_deepseek.chat.completions.create.assert_not_called()


def test_merge_cells_handles_malformed_deepseek_json():
    fake_deepseek = MagicMock()
    fake_deepseek.chat.completions.create.return_value = _mock_deepseek_response("not json")
    cells = [
        _cell("a", "ma", parsed=_parsed(tagline="A.", summary="A.", confidence=0.8)),
        _cell("b", "mb", parsed=_parsed(tagline="B.", summary="B.", confidence=0.95)),
    ]
    merged, meta = merge_cells(cells, fake_deepseek)
    assert meta["narrative_fallback"] == "max_confidence"
    assert merged.tagline == "B."


def test_merge_deterministic_numeric_median_even_length_rounds_to_int():
    """statistics.median of an even-length list yields a float; cast to int.

    Regression: pydantic int fields rejected the 4.5 float coming from
    statistics.median([4, 5]).
    """
    cells = [
        _cell("a", "ma", parsed=_parsed(catalog_size_estimate=4)),
        _cell("b", "mb", parsed=_parsed(catalog_size_estimate=5)),
    ]
    merged, prov = _merge_deterministic(cells)
    assert isinstance(merged["catalog_size_estimate"], int)
    assert merged["catalog_size_estimate"] in (4, 5)  # banker's rounding can go either way for .5
    assert prov["catalog_size_estimate"].startswith("median:")

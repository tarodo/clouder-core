"""Tests for artlab.aggregate."""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from collector.artist_enrichment.aggregator import _filter_parseable, _merge_deterministic, merge_cells
from collector.artist_enrichment.schemas import ArtistInfo


def _cell(vendor: str, model: str, parsed: dict | None = None, error: str | None = None) -> dict:
    return {
        "run_id": "test-run",
        "prompt": {"slug": "artist_v1", "version": "v1"},
        "vendor": {"name": vendor, "model": model},
        "fixture": {"id": "anna", "artist_name": "ANNA", "style": "techno",
                    "sample_tracks": [], "known_labels": []},
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
    base = {
        "artist_name": "ANNA",
        "aliases": [],
        "real_name": None,
        "artist_type": "solo",
        "members": [],
        "country": "Brazil",
        "city": None,
        "active_since": 2010,
        "status": "active",
        "primary_styles": [],
        "labels": [],
        "notable_collaborators": [],
        "notable_releases": [],
        "spotify_url": None,
        "soundcloud_url": None,
        "bandcamp_url": None,
        "beatport_url": None,
        "residentadvisor_url": None,
        "discogs_url": None,
        "instagram_url": None,
        "twitter_url": None,
        "website": None,
        "tagline": None,
        "bio": None,
        "summary": "Brazilian techno DJ.",
        "ai_content": "none_detected",
        "ai_signals": [],
        "ai_reasoning": "n/a",
        "confidence": 0.9,
        "sources": [],
        "notes": None,
    }
    base.update(overrides)
    return base


def test_filter_parseable_drops_errored_and_none():
    cells = [
        _cell("a", "ma", parsed=_parsed()),
        _cell("b", "mb", parsed=None, error="boom"),
        _cell("c", "mc", parsed=None),
        _cell("d", "md", parsed=_parsed(country="Germany")),
    ]
    filtered = _filter_parseable(cells)
    assert len(filtered) == 2
    assert filtered[0]["vendor"]["name"] == "a"
    assert filtered[1]["vendor"]["name"] == "d"


def test_merge_deterministic_numeric_median():
    cells = [
        _cell("a", "ma", parsed=_parsed(active_since=2008)),
        _cell("b", "mb", parsed=_parsed(active_since=2010)),
        _cell("c", "mc", parsed=_parsed(active_since=2012)),
    ]
    merged, prov = _merge_deterministic(cells)
    assert merged["active_since"] == 2010
    assert prov["active_since"] == "median:2010"


def test_merge_deterministic_enum_majority():
    cells = [
        _cell("a", "ma", parsed=_parsed(status="active", confidence=0.9)),
        _cell("b", "mb", parsed=_parsed(status="active", confidence=0.7)),
        _cell("c", "mc", parsed=_parsed(status="inactive", confidence=1.0)),
    ]
    merged, prov = _merge_deterministic(cells)
    assert merged["status"] == "active"
    assert prov["status"].startswith("majority")


def test_merge_deterministic_enum_tie_breaks_on_confidence():
    cells = [
        _cell("a", "ma", parsed=_parsed(status="active", confidence=0.8)),
        _cell("b", "mb", parsed=_parsed(status="inactive", confidence=0.95)),
    ]
    merged, prov = _merge_deterministic(cells)
    assert merged["status"] == "inactive"
    assert "tie" in prov["status"]


def test_merge_deterministic_country_short_wins_tie():
    cells = [
        _cell("a", "ma", parsed=_parsed(country="United Kingdom")),
        _cell("b", "mb", parsed=_parsed(country="GB")),
    ]
    merged, prov = _merge_deterministic(cells)
    assert merged["country"] == "GB"
    assert "shortest" in prov["country"]


def test_merge_deterministic_releases_union_top5():
    cells = [
        _cell("a", "ma", parsed=_parsed(notable_releases=["Hidden Beauties", "Forsaken", "Remixes"], confidence=1.0)),
        _cell("b", "mb", parsed=_parsed(notable_releases=["Hidden Beauties", "Spline", "Mira", "Forsaken"], confidence=0.8)),
        _cell("c", "mc", parsed=_parsed(notable_releases=["Hidden Beauties", "Odd Concept"], confidence=0.6)),
    ]
    merged, prov = _merge_deterministic(cells)
    releases = merged["notable_releases"]
    assert releases[0] == "Hidden Beauties"
    assert len(releases) <= 5
    assert "union top-5 round-robin" in prov["notable_releases"]


def test_merge_deterministic_url_max_confidence_wins():
    cells = [
        _cell("a", "ma", parsed=_parsed(spotify_url=None, confidence=0.95)),
        _cell("b", "mb", parsed=_parsed(spotify_url="https://open.spotify.com/artist/x", confidence=0.7)),
        _cell("c", "mc", parsed=_parsed(spotify_url="https://open.spotify.com/artist/y", confidence=0.8)),
    ]
    merged, prov = _merge_deterministic(cells)
    assert merged["spotify_url"] == "https://open.spotify.com/artist/y"
    assert "highest confidence" in prov["spotify_url"]


def test_merge_deterministic_confidence_mean():
    cells = [
        _cell("a", "ma", parsed=_parsed(confidence=0.8)),
        _cell("b", "mb", parsed=_parsed(confidence=1.0)),
        _cell("c", "mc", parsed=_parsed(confidence=0.6)),
    ]
    merged, prov = _merge_deterministic(cells)
    assert merged["confidence"] == pytest.approx(0.8)
    assert prov["confidence"].startswith("mean")


def test_merge_deterministic_unknown_abstains_from_enum_vote():
    cells = [
        _cell("a", "ma", parsed=_parsed(ai_content="none_detected", confidence=1.0)),
        _cell("b", "mb", parsed=_parsed(ai_content="unknown", confidence=0.6)),
        _cell("c", "mc", parsed=_parsed(ai_content="unknown", confidence=0.8)),
    ]
    merged, prov = _merge_deterministic(cells)
    assert merged["ai_content"] == "none_detected"
    assert "definitive" in prov["ai_content"]


def _mock_deepseek_response(content: str, prompt_tokens: int = 800, completion_tokens: int = 300):
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
        "tagline": "Brazilian techno force.",
        "bio": "ANNA is a Brazilian DJ and producer.",
        "summary": "ANNA, born Ana Miranda, is a Brazilian techno artist.",
        "ai_reasoning": "No AI signals across vendors.",
        "notes": None,
    }
    fake = MagicMock()
    fake.chat.completions.create.return_value = _mock_deepseek_response(json.dumps(payload))

    cells = [
        _cell("a", "ma", parsed=_parsed(tagline="t1", bio="b1", summary="s1", confidence=0.9)),
        _cell("b", "mb", parsed=_parsed(tagline="t2", bio="b2", summary="s2", confidence=0.95)),
    ]
    merged, meta = merge_cells(cells, fake, deepseek_model="deepseek-v4-flash")
    assert isinstance(merged, ArtistInfo)
    assert merged.tagline == "Brazilian techno force."
    assert merged.bio == "ANNA is a Brazilian DJ and producer."
    assert merged.country == "Brazil"
    assert merged.active_since == 2010
    assert meta["narrative_cost_usd"] > 0
    assert meta["field_provenance"]["tagline"] == "deepseek narrative"
    fake.chat.completions.create.assert_called_once()


def test_merge_cells_narrative_fallback_on_error():
    fake = MagicMock()
    fake.chat.completions.create.side_effect = RuntimeError("boom")
    cells = [
        _cell("a", "ma", parsed=_parsed(tagline="low", summary="low s", confidence=0.4)),
        _cell("b", "mb", parsed=_parsed(tagline="high", summary="high s", confidence=0.95)),
    ]
    merged, meta = merge_cells(cells, fake)
    assert merged.tagline == "high"
    assert merged.summary == "high s"
    assert meta["narrative_fallback"] == "max_confidence"


def test_merge_cells_single_source_skips_deepseek():
    fake = MagicMock()
    cells = [_cell("a", "ma", parsed=_parsed(summary="single s", tagline="single"))]
    merged, meta = merge_cells(cells, fake)
    assert merged.summary == "single s"
    assert merged.tagline == "single"
    assert meta["single_source"] is True
    assert meta["narrative_cost_usd"] == 0.0
    fake.chat.completions.create.assert_not_called()


def test_merge_cells_all_failed_returns_placeholder():
    fake = MagicMock()
    cells = [_cell("a", "ma", parsed=None, error="boom"), _cell("b", "mb", parsed=None)]
    merged, meta = merge_cells(cells, fake)
    assert merged.summary == "All vendor sources failed."
    assert merged.confidence == 0.0
    assert meta["all_failed"] is True
    fake.chat.completions.create.assert_not_called()


def test_merge_cells_handles_malformed_deepseek_json():
    fake = MagicMock()
    fake.chat.completions.create.return_value = _mock_deepseek_response("not json")
    cells = [
        _cell("a", "ma", parsed=_parsed(tagline="A", summary="A", confidence=0.8)),
        _cell("b", "mb", parsed=_parsed(tagline="B", summary="B", confidence=0.95)),
    ]
    merged, meta = merge_cells(cells, fake)
    assert meta["narrative_fallback"] == "max_confidence"
    assert merged.tagline == "B"


def test_merge_cells_narrative_fallback_on_missing_key():
    fake = MagicMock()
    fake.chat.completions.create.return_value = _mock_deepseek_response(
        json.dumps({"tagline": "only tagline"})  # missing bio/summary/ai_reasoning/notes
    )
    cells = [
        _cell("a", "ma", parsed=_parsed(tagline="A", summary="A", confidence=0.8)),
        _cell("b", "mb", parsed=_parsed(tagline="B", summary="B", confidence=0.95)),
    ]
    merged, meta = merge_cells(cells, fake)
    assert meta["narrative_fallback"] == "max_confidence"
    assert merged.tagline == "B"

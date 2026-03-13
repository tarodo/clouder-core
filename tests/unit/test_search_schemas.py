"""Tests for AI search Pydantic schemas."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from collector.search.schemas import (
    AIContentStatus,
    LabelAge,
    LabelSearchResult,
    LabelSize,
)


def _valid_label_result(**overrides) -> dict:
    base = {
        "label_name": "Test Label",
        "style": "Techno",
        "size": "small",
        "size_details": "About 100 releases",
        "age": "established",
        "age_details": "Founded in 2010",
        "ai_content": "none_detected",
        "ai_content_details": "No AI content found",
        "summary": "A small techno label",
        "confidence": 0.8,
    }
    base.update(overrides)
    return base


def test_valid_label_search_result() -> None:
    result = LabelSearchResult(**_valid_label_result())

    assert result.label_name == "Test Label"
    assert result.size == LabelSize.SMALL
    assert result.age == LabelAge.ESTABLISHED
    assert result.ai_content == AIContentStatus.NONE_DETECTED
    assert result.confidence == 0.8
    assert result.founded_year is None
    assert result.notable_artists == []
    assert result.sources == []


def test_label_search_result_with_optional_fields() -> None:
    result = LabelSearchResult(
        **_valid_label_result(
            founded_year=2010,
            country="Germany",
            website="https://example.com",
            notable_artists=["Artist A", "Artist B"],
            sources=["https://source.com"],
        )
    )

    assert result.founded_year == 2010
    assert result.country == "Germany"
    assert result.notable_artists == ["Artist A", "Artist B"]


def test_confidence_must_be_between_0_and_1() -> None:
    with pytest.raises(ValidationError):
        LabelSearchResult(**_valid_label_result(confidence=1.5))

    with pytest.raises(ValidationError):
        LabelSearchResult(**_valid_label_result(confidence=-0.1))


def test_invalid_size_enum() -> None:
    with pytest.raises(ValidationError):
        LabelSearchResult(**_valid_label_result(size="gigantic"))


def test_model_dump_roundtrip() -> None:
    original = LabelSearchResult(**_valid_label_result())
    data = original.model_dump()
    restored = LabelSearchResult(**data)

    assert restored == original


def test_model_validate_json() -> None:
    import json

    data = _valid_label_result()
    raw = json.dumps(data)
    result = LabelSearchResult.model_validate_json(raw)

    assert result.label_name == "Test Label"

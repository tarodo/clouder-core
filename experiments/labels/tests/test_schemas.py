import pytest
from pydantic import ValidationError

from lab.schemas import (
    ActivityLevel,
    AIContentStatus,
    AISignal,
    AISignalKind,
    LabelInfo,
)


def test_label_info_minimal_valid():
    info = LabelInfo(
        label_name="Drumcode",
        ai_reasoning="No AI signals found in available sources.",
        summary="Swedish techno label founded 1996 by Adam Beyer.",
        confidence=0.9,
    )
    assert info.label_name == "Drumcode"
    assert info.activity == ActivityLevel.UNKNOWN
    assert info.ai_content == AIContentStatus.UNKNOWN
    assert info.aliases == []
    assert info.notable_artists == []


def test_label_info_full():
    info = LabelInfo(
        label_name="NeuroBeats AI",
        country="US",
        founded_year=2023,
        catalog_size_estimate=412,
        releases_last_12_months=388,
        activity=ActivityLevel.FIRE_HOSE,
        ai_content=AIContentStatus.CONFIRMED,
        ai_signals=[
            AISignal(
                kind=AISignalKind.VOLUME,
                description="388 releases in 12 months from 4 artists",
                source_url="https://example.com/catalog",
            ),
        ],
        ai_reasoning="Volume + named tool credits.",
        summary="Heavy AI signals.",
        confidence=0.85,
    )
    assert info.activity == ActivityLevel.FIRE_HOSE
    assert info.ai_signals[0].kind == AISignalKind.VOLUME


def test_confidence_bounds():
    with pytest.raises(ValidationError):
        LabelInfo(
            label_name="x",
            ai_reasoning="x",
            summary="x",
            confidence=1.5,
        )

    with pytest.raises(ValidationError):
        LabelInfo(
            label_name="x",
            ai_reasoning="x",
            summary="x",
            confidence=-0.1,
        )


def test_label_info_accepts_new_app_fields():
    info = LabelInfo(
        label_name="Drumcode",
        logo_url="https://example.com/drumcode-avatar.png",
        tagline="Swedish techno powerhouse since 1996.",
        instagram_url="https://www.instagram.com/drumcode_se",
        twitter_url="https://x.com/drumcode",
        ai_reasoning="No AI signals.",
        summary="Swedish techno label.",
        confidence=0.9,
    )
    assert info.logo_url == "https://example.com/drumcode-avatar.png"
    assert info.tagline == "Swedish techno powerhouse since 1996."
    assert info.instagram_url == "https://www.instagram.com/drumcode_se"
    assert info.twitter_url == "https://x.com/drumcode"


def test_label_info_new_fields_optional():
    info = LabelInfo(
        label_name="Anjunadeep",
        ai_reasoning="-",
        summary="-",
        confidence=0.5,
    )
    assert info.logo_url is None
    assert info.tagline is None
    assert info.instagram_url is None
    assert info.twitter_url is None

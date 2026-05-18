from collector.label_enrichment.schemas import (
    ActivityLevel,
    AIContentStatus,
    AISignal,
    AISignalKind,
    LabelInfo,
)


def test_label_info_minimal_round_trip():
    info = LabelInfo(
        label_name="Drumcode",
        ai_reasoning="No AI signals detected.",
        summary="Swedish techno label.",
        confidence=0.9,
    )
    dumped = info.model_dump()
    reloaded = LabelInfo.model_validate(dumped)
    assert reloaded.label_name == "Drumcode"
    assert reloaded.status == "unknown"  # default
    assert reloaded.activity == ActivityLevel.UNKNOWN
    assert reloaded.ai_content == AIContentStatus.UNKNOWN
    assert reloaded.primary_styles == []


def test_label_info_status_enum_validates():
    import pytest
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        LabelInfo(
            label_name="x",
            ai_reasoning="x",
            summary="x",
            confidence=0.5,
            status="hibernating",  # not in Literal
        )


def test_ai_signal_round_trip():
    sig = AISignal(
        kind=AISignalKind.VOLUME,
        description="Suspicious volume of releases.",
        source_url="https://example.com",
    )
    assert AISignal.model_validate(sig.model_dump()) == sig

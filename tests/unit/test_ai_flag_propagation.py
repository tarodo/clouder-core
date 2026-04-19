"""Unit tests for propagating ai_content findings onto canonical rows."""

from __future__ import annotations

from collector.search.schemas import AIContentStatus, LabelAge, LabelSearchResult, LabelSize
from collector.search_handler import propagate_ai_flag


def _result(ai_content: AIContentStatus, confidence: float) -> LabelSearchResult:
    return LabelSearchResult(
        label_name="X",
        style="Y",
        size=LabelSize.SMALL,
        size_details="",
        age=LabelAge.NEW,
        age_details="",
        ai_content=ai_content,
        ai_content_details="",
        summary="",
        confidence=confidence,
    )


class FakeRepo:
    def __init__(self) -> None:
        self.updates: list[tuple[str, str, bool]] = []

    def update_entity_is_ai_suspected(
        self,
        entity_type: str,
        entity_id: str,
        value: bool,
        transaction_id: str | None = None,
    ) -> None:
        self.updates.append((entity_type, entity_id, value))


def test_confirmed_above_threshold_sets_flag() -> None:
    repo = FakeRepo()
    propagate_ai_flag(
        repo,
        entity_type="label",
        entity_id="L1",
        result=_result(AIContentStatus.CONFIRMED, 0.8),
        threshold=0.6,
    )
    assert repo.updates == [("label", "L1", True)]


def test_suspected_above_threshold_sets_flag() -> None:
    repo = FakeRepo()
    propagate_ai_flag(
        repo,
        entity_type="label",
        entity_id="L1",
        result=_result(AIContentStatus.SUSPECTED, 0.7),
        threshold=0.6,
    )
    assert repo.updates == [("label", "L1", True)]


def test_none_detected_clears_flag() -> None:
    repo = FakeRepo()
    propagate_ai_flag(
        repo,
        entity_type="label",
        entity_id="L1",
        result=_result(AIContentStatus.NONE_DETECTED, 0.9),
        threshold=0.6,
    )
    assert repo.updates == [("label", "L1", False)]


def test_low_confidence_no_update() -> None:
    repo = FakeRepo()
    propagate_ai_flag(
        repo,
        entity_type="label",
        entity_id="L1",
        result=_result(AIContentStatus.CONFIRMED, 0.4),
        threshold=0.6,
    )
    assert repo.updates == []


def test_unknown_status_no_update() -> None:
    repo = FakeRepo()
    propagate_ai_flag(
        repo,
        entity_type="label",
        entity_id="L1",
        result=_result(AIContentStatus.UNKNOWN, 0.95),
        threshold=0.6,
    )
    assert repo.updates == []

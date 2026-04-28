from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from collector.curation import OrderMismatchError, ValidationError
from collector.curation.categories_repository import CategoriesRepository
from collector.curation.categories_service import (
    normalize_category_name,
    validate_category_name,
    validate_reorder_set,
)
from collector.curation.triage_repository import TriageRepository


# ---- normalize_category_name -----------------------------------------------

def test_normalize_lowercases_and_trims() -> None:
    assert normalize_category_name("  Tech House  ") == "tech house"


def test_normalize_collapses_internal_whitespace() -> None:
    assert normalize_category_name("Tech    House") == "tech house"


def test_normalize_handles_unicode() -> None:
    assert normalize_category_name("Délicat") == "délicat"


def test_normalize_handles_emoji() -> None:
    assert normalize_category_name("Hot 🔥 House") == "hot 🔥 house"


def test_normalize_pure_whitespace_yields_empty() -> None:
    assert normalize_category_name("   \t  ") == ""


# ---- validate_category_name ------------------------------------------------

def test_validate_accepts_normal_name() -> None:
    validate_category_name("Tech House")  # no exception


def test_validate_rejects_empty() -> None:
    with pytest.raises(ValidationError):
        validate_category_name("")


def test_validate_rejects_whitespace_only() -> None:
    with pytest.raises(ValidationError):
        validate_category_name("   ")


def test_validate_rejects_too_long() -> None:
    with pytest.raises(ValidationError):
        validate_category_name("x" * 65)


def test_validate_accepts_64_chars() -> None:
    validate_category_name("x" * 64)


def test_validate_rejects_control_chars() -> None:
    with pytest.raises(ValidationError):
        validate_category_name("Tech\x00House")


def test_validate_rejects_newlines() -> None:
    with pytest.raises(ValidationError):
        validate_category_name("Tech\nHouse")


# ---- validate_reorder_set --------------------------------------------------

def test_reorder_set_passes_on_exact_match() -> None:
    validate_reorder_set(actual={"a", "b", "c"}, requested=["a", "b", "c"])


def test_reorder_set_passes_on_reordered_match() -> None:
    validate_reorder_set(actual={"a", "b", "c"}, requested=["c", "a", "b"])


def test_reorder_set_rejects_missing_id() -> None:
    with pytest.raises(OrderMismatchError):
        validate_reorder_set(actual={"a", "b", "c"}, requested=["a", "b"])


def test_reorder_set_rejects_extra_id() -> None:
    with pytest.raises(OrderMismatchError):
        validate_reorder_set(actual={"a", "b"}, requested=["a", "b", "c"])


def test_reorder_set_rejects_duplicates() -> None:
    with pytest.raises(OrderMismatchError):
        validate_reorder_set(actual={"a", "b"}, requested=["a", "a"])


# ---- Spec-D side-effects (T16): create snapshot + soft_delete inactivate ----

def _now() -> datetime:
    return datetime(2026, 4, 28, 12, 0, tzinfo=timezone.utc)


def _data_api_for_create(returned_category_id: str = "c1") -> MagicMock:
    data_api = MagicMock()
    data_api.transaction.return_value.__enter__.return_value = "tx-test"
    data_api.transaction.return_value.__exit__.return_value = False
    # 1: style row, 2: max_pos, 3: INSERT RETURNING category row.
    # snapshot_category_into_active_blocks is monkeypatched out so its
    # internal SELECT/INSERT statements are never reached.
    data_api.execute.side_effect = [
        [{"id": "s1", "name": "House"}],
        [{"max_pos": -1}],
        [
            {
                "id": returned_category_id,
                "user_id": "u1",
                "style_id": "s1",
                "style_name": "House",
                "name": "Tech",
                "normalized_name": "tech",
                "position": 0,
                "track_count": 0,
                "created_at": "2026-04-28T12:00:00Z",
                "updated_at": "2026-04-28T12:00:00Z",
            }
        ],
    ]
    return data_api


def test_create_invokes_snapshot_into_active_blocks(monkeypatch) -> None:
    """Spec-D D7: a successful category INSERT must trigger
    TriageRepository.snapshot_category_into_active_blocks within the same TX.
    """
    snapshot_calls: list[dict] = []

    def fake_snapshot(self, **kwargs):
        snapshot_calls.append(kwargs)
        return 2  # pretend we inserted into 2 active blocks

    monkeypatch.setattr(
        TriageRepository,
        "snapshot_category_into_active_blocks",
        fake_snapshot,
    )

    data_api = _data_api_for_create()
    repo = CategoriesRepository(data_api=data_api)

    row = repo.create(
        user_id="u1",
        style_id="s1",
        category_id="c1",
        name="Tech",
        normalized_name="tech",
        now=_now(),
        correlation_id="cid-T16",
    )

    assert row.id == "c1"
    assert len(snapshot_calls) == 1
    call = snapshot_calls[0]
    assert call["user_id"] == "u1"
    assert call["style_id"] == "s1"
    assert call["category_id"] == "c1"
    assert call["transaction_id"] is not None
    assert call["transaction_id"] == "tx-test"


def test_create_does_not_invoke_snapshot_on_style_not_found(monkeypatch) -> None:
    """Snapshot must not run if the INSERT path was never reached."""
    from collector.curation import NotFoundError

    snapshot_calls: list[dict] = []

    def fake_snapshot(self, **kwargs):
        snapshot_calls.append(kwargs)
        return 0

    monkeypatch.setattr(
        TriageRepository,
        "snapshot_category_into_active_blocks",
        fake_snapshot,
    )

    data_api = MagicMock()
    data_api.transaction.return_value.__enter__.return_value = "tx-test"
    data_api.transaction.return_value.__exit__.return_value = False
    data_api.execute.side_effect = [[]]  # style lookup empty
    repo = CategoriesRepository(data_api=data_api)

    with pytest.raises(NotFoundError):
        repo.create(
            user_id="u1",
            style_id="missing",
            category_id="c1",
            name="Tech",
            normalized_name="tech",
            now=_now(),
        )
    assert snapshot_calls == []


def test_soft_delete_invokes_mark_staging_inactive(monkeypatch) -> None:
    """Spec-D D8: a successful soft-delete must trigger
    TriageRepository.mark_staging_inactive_for_category within the same TX.
    """
    inactive_calls: list[dict] = []

    def fake_mark_inactive(self, **kwargs):
        inactive_calls.append(kwargs)
        return 3  # pretend 3 STAGING buckets were flipped

    monkeypatch.setattr(
        TriageRepository,
        "mark_staging_inactive_for_category",
        fake_mark_inactive,
    )

    data_api = MagicMock()
    data_api.transaction.return_value.__enter__.return_value = "tx-soft"
    data_api.transaction.return_value.__exit__.return_value = False
    # UPDATE categories ... RETURNING -> one row (success)
    data_api.execute.side_effect = [[{"id": "c1"}]]
    repo = CategoriesRepository(data_api=data_api)

    deleted = repo.soft_delete(
        user_id="u1",
        category_id="c1",
        now=_now(),
        correlation_id="cid-T16",
    )

    assert deleted is True
    assert len(inactive_calls) == 1
    call = inactive_calls[0]
    assert call["user_id"] == "u1"
    assert call["category_id"] == "c1"
    assert call["transaction_id"] is not None
    assert call["transaction_id"] == "tx-soft"


def test_soft_delete_skips_inactivate_when_category_missing(
    monkeypatch,
) -> None:
    """No rows updated -> no STAGING bucket inactivation."""
    inactive_calls: list[dict] = []

    def fake_mark_inactive(self, **kwargs):
        inactive_calls.append(kwargs)
        return 0

    monkeypatch.setattr(
        TriageRepository,
        "mark_staging_inactive_for_category",
        fake_mark_inactive,
    )

    data_api = MagicMock()
    data_api.transaction.return_value.__enter__.return_value = "tx-soft"
    data_api.transaction.return_value.__exit__.return_value = False
    data_api.execute.side_effect = [[]]  # UPDATE returned no rows
    repo = CategoriesRepository(data_api=data_api)

    deleted = repo.soft_delete(
        user_id="u1",
        category_id="missing",
        now=_now(),
    )
    assert deleted is False
    assert inactive_calls == []

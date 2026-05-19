"""LabelEnrichmentRepository: user label preference CRUD."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import pytest

from collector.label_enrichment.repository import LabelEnrichmentRepository


class FakeDataApi:
    """Minimal stub: records (sql, params) per call, returns scripted rows."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.scripted: list[list[dict[str, Any]]] = []

    def script(self, *batches: list[dict[str, Any]]) -> None:
        self.scripted.extend(batches)

    def execute(self, sql: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        self.calls.append((sql, dict(params or {})))
        if self.scripted:
            return self.scripted.pop(0)
        return []


def _fixed_now() -> datetime:
    return datetime(2026, 5, 19, 12, 0, tzinfo=timezone.utc)


def test_upsert_user_label_pref_emits_upsert_sql():
    api = FakeDataApi()
    repo = LabelEnrichmentRepository(data_api=api, now=_fixed_now)

    repo.upsert_user_label_pref(user_id="u-1", label_id="lbl-1", status="liked")

    assert len(api.calls) == 1
    sql, params = api.calls[0]
    assert "INSERT INTO clouder_user_label_prefs" in sql
    assert "ON CONFLICT" in sql
    assert params == {
        "user_id": "u-1",
        "label_id": "lbl-1",
        "status": "liked",
        "ts": _fixed_now(),
    }


def test_upsert_rejects_unknown_status():
    api = FakeDataApi()
    repo = LabelEnrichmentRepository(data_api=api, now=_fixed_now)
    with pytest.raises(ValueError):
        repo.upsert_user_label_pref(user_id="u-1", label_id="lbl-1", status="loved")


def test_delete_user_label_pref_emits_delete_sql():
    api = FakeDataApi()
    repo = LabelEnrichmentRepository(data_api=api, now=_fixed_now)

    repo.delete_user_label_pref(user_id="u-1", label_id="lbl-1")

    sql, params = api.calls[0]
    assert sql.strip().startswith("DELETE FROM clouder_user_label_prefs")
    assert params == {"user_id": "u-1", "label_id": "lbl-1"}

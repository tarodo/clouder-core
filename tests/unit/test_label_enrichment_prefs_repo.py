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


def test_list_user_label_prefs_paginates_and_filters_by_status():
    api = FakeDataApi()
    api.script(
        [
            {"id": "lbl-1", "name": "Fokuz", "status": "liked"},
            {"id": "lbl-2", "name": "Drumcode", "status": "liked"},
        ],
        [{"c": 7}],
    )
    repo = LabelEnrichmentRepository(data_api=api, now=_fixed_now)

    items, total = repo.list_user_label_prefs(
        user_id="u-1", status="liked", page=2, limit=2,
    )

    assert total == 7
    assert [it["id"] for it in items] == ["lbl-1", "lbl-2"]
    assert all(it["my_preference"] == "liked" for it in items)

    sql, params = api.calls[0]
    assert "FROM clouder_user_label_prefs p" in sql
    assert "JOIN clouder_labels lbl" in sql
    assert "p.status = :status" in sql
    assert params == {
        "user_id": "u-1",
        "status": "liked",
        "lim": 2,
        "off": 2,  # (page-1)*limit = (2-1)*2
    }


def test_list_labels_projects_my_preference_via_left_join():
    api = FakeDataApi()
    api.script(
        [
            {
                "id": "lbl-1", "name": "Fokuz", "dominant_style": "drum-and-bass",
                "track_count": 3, "status": "completed",
                "tagline": "t", "country": "NL", "founded_year": 2007,
                "primary_styles": ["liquid"], "activity": "steady",
                "ai_content": "none_detected", "updated_at": _fixed_now(),
                "my_preference": "liked",
            },
        ],
        [{"c": 1}],
    )
    repo = LabelEnrichmentRepository(data_api=api, now=_fixed_now)

    items, total = repo.list_labels(
        style=None, q=None, sort="name", page=1, limit=50,
        user_id="u-1", my="all",
    )

    assert total == 1
    assert items[0]["my_preference"] == "liked"

    main_sql, _ = api.calls[0]
    assert "LEFT JOIN clouder_user_label_prefs ulp" in main_sql
    assert "ulp.user_id = :pref_user_id" in main_sql
    assert "ulp.status AS my_preference" in main_sql


def test_list_labels_my_liked_uses_inner_filter():
    api = FakeDataApi()
    api.script([], [{"c": 0}])
    repo = LabelEnrichmentRepository(data_api=api, now=_fixed_now)

    repo.list_labels(
        style=None, q=None, sort="name", page=1, limit=50,
        user_id="u-1", my="liked",
    )

    main_sql, params = api.calls[0]
    assert "ulp.status = 'liked'" in main_sql
    assert params["pref_user_id"] == "u-1"


def test_list_labels_my_unrated_uses_anti_join():
    api = FakeDataApi()
    api.script([], [{"c": 0}])
    repo = LabelEnrichmentRepository(data_api=api, now=_fixed_now)

    repo.list_labels(
        style=None, q=None, sort="name", page=1, limit=50,
        user_id="u-1", my="unrated",
    )

    main_sql, _ = api.calls[0]
    assert "ulp.user_id IS NULL" in main_sql


def test_get_label_info_for_user_includes_my_preference_when_info_present():
    api = FakeDataApi()
    api.script(
        [{
            "merged": {
                "label_name": "Fokuz",
                "country": "NL",
                "summary": "Rotterdam liquid label.",
                "ai_content": "none_detected",
            },
            "my_preference": "liked",
        }],
    )
    repo = LabelEnrichmentRepository(data_api=api, now=_fixed_now)

    out = repo.get_label_info_for_user("lbl-1", user_id="u-1")

    assert out is not None
    assert out["label_name"] == "Fokuz"
    assert out["my_preference"] == "liked"


def test_get_label_info_for_user_returns_minimal_payload_when_info_missing():
    api = FakeDataApi()
    # First call (merged JSONB) — no info row.
    # Second call (fallback) — label exists; pref returned as None.
    api.script(
        [],
        [{"label_name": "Drumcode", "my_preference": None}],
    )
    repo = LabelEnrichmentRepository(data_api=api, now=_fixed_now)

    out = repo.get_label_info_for_user("lbl-2", user_id="u-1")

    assert out == {"label_name": "Drumcode", "my_preference": None}


def test_get_label_info_for_user_returns_none_when_label_missing():
    api = FakeDataApi()
    api.script([], [])  # info miss, label miss
    repo = LabelEnrichmentRepository(data_api=api, now=_fixed_now)
    assert repo.get_label_info_for_user("nope", user_id="u-1") is None

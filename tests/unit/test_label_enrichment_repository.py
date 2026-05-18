import json
from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from collector.label_enrichment.repository import (
    LabelEnrichmentRepository,
    RunSpec,
)


def _now():
    return datetime(2026, 5, 18, 21, 0, 0, tzinfo=timezone.utc)


def _repo_with_fake():
    data_api = MagicMock()
    repo = LabelEnrichmentRepository(data_api=data_api, now=_now)
    return repo, data_api


def test_create_run_inserts_with_correct_cells_total():
    repo, data_api = _repo_with_fake()
    data_api.execute.return_value = []  # INSERT returns no rows

    spec = RunSpec(
        prompt_slug="label_v3_app_fields",
        prompt_version="v1",
        vendors=["gemini", "openai", "tavily_deepseek"],
        models={"gemini": "gemini-3-flash-preview", "openai": "gpt-5.4-mini",
                "tavily_deepseek": "deepseek-v4-flash"},
        merge_vendor="deepseek",
        merge_model="deepseek-v4-flash",
        requested_labels=4,
        created_by_user_id="user-1",
    )
    run_id = repo.create_run(spec)

    assert isinstance(run_id, str) and len(run_id) == 36
    sql, params = data_api.execute.call_args[0]
    assert "INSERT INTO clouder_label_enrichment_runs" in sql
    assert params["cells_total"] == 4 * 3
    assert params["requested_labels"] == 4
    assert params["status"] == "queued"


def test_upsert_label_by_name_returns_existing_id():
    repo, data_api = _repo_with_fake()
    data_api.execute.side_effect = [
        [{"id": "existing-id"}],   # SELECT match
    ]
    label_id = repo.upsert_label_by_name("Drumcode")
    assert label_id == "existing-id"


def test_upsert_label_by_name_creates_new_row_when_missing():
    repo, data_api = _repo_with_fake()
    data_api.execute.side_effect = [
        [],                        # SELECT no match
        [],                        # INSERT
    ]
    label_id = repo.upsert_label_by_name("Brand New Label")
    assert isinstance(label_id, str) and len(label_id) == 36
    insert_sql, insert_params = data_api.execute.call_args_list[1][0]
    assert "INSERT INTO clouder_labels" in insert_sql
    assert insert_params["name"] == "Brand New Label"
    assert insert_params["normalized_name"] == "brand new label"


def test_get_run_returns_dict_or_none():
    repo, data_api = _repo_with_fake()
    data_api.execute.return_value = [{
        "id": "r1", "status": "running", "prompt_slug": "label_v3_app_fields",
        "prompt_version": "v1", "vendors": ["gemini"], "models": {"gemini": "x"},
        "merge_vendor": "deepseek", "merge_model": "deepseek-v4-flash",
        "requested_labels": 1, "cells_total": 1, "cells_ok": 0, "cells_error": 0,
        "cost_usd": 0,
    }]
    row = repo.get_run("r1")
    assert row["id"] == "r1"

    data_api.execute.return_value = []
    assert repo.get_run("missing") is None


from collector.label_enrichment.vendors.base import VendorResponse
from collector.label_enrichment.schemas import LabelInfo


def _ok_vendor_response() -> VendorResponse:
    info = LabelInfo(
        label_name="Drumcode",
        ai_reasoning="none",
        summary="techno",
        confidence=0.9,
    )
    return VendorResponse(
        parsed=info,
        raw={"foo": "bar"},
        citations=["https://example.com"],
        usage={"input_tokens": 100, "output_tokens": 50, "cost_usd": 0.001},
        latency_ms=1234,
        model="gemini-3-flash-preview",
    )


def test_insert_cell_ok_uses_on_conflict_do_nothing():
    repo, data_api = _repo_with_fake()
    data_api.execute.return_value = []
    resp = _ok_vendor_response()
    repo.insert_cell(run_id="r", label_id="l", vendor="gemini", response=resp)
    sql, params = data_api.execute.call_args[0]
    assert "ON CONFLICT" in sql
    assert "DO NOTHING" in sql
    assert params["status"] == "ok"
    assert params["error"] is None
    assert params["vendor"] == "gemini"
    assert params["model"] == "gemini-3-flash-preview"


def test_insert_cell_error_serialises_error_payload():
    repo, data_api = _repo_with_fake()
    data_api.execute.return_value = []
    resp = VendorResponse(
        parsed=None,
        raw={},
        citations=[],
        usage={"input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0},
        latency_ms=50,
        model="openai-x",
        error="RateLimitError: 429",
    )
    repo.insert_cell(run_id="r", label_id="l", vendor="openai", response=resp)
    _, params = data_api.execute.call_args[0]
    assert params["status"] == "error"
    error_payload = json.loads(params["error"])
    assert error_payload["message"] == "RateLimitError: 429"


def test_mark_run_running_only_flips_queued_to_running():
    repo, data_api = _repo_with_fake()
    data_api.execute.return_value = []
    repo.mark_run_running("r-1")
    sql, params = data_api.execute.call_args[0]
    assert "status = 'running'" in sql
    assert "started_at = :ts" in sql
    assert "WHERE id = :id AND status = 'queued'" in sql
    assert params["id"] == "r-1"


def test_upsert_label_info_writes_denormalized_columns():
    repo, data_api = _repo_with_fake()
    data_api.execute.return_value = []
    merged = LabelInfo(
        label_name="Drumcode",
        ai_reasoning="none",
        summary="techno",
        confidence=0.9,
        country="Sweden",
        founded_year=1996,
        status="active",
        primary_styles=["techno", "peak-time techno"],
        tagline="Swedish techno powerhouse since 1996.",
        last_release_date="2026-04-01",
    )
    provenance = {"status": "majority(2/3 definitive)"}
    repo.upsert_label_info(
        label_id="lbl-1",
        last_run_id="run-1",
        prompt_slug="label_v3_app_fields",
        prompt_version="v1",
        merged=merged,
        provenance=provenance,
    )
    sql, params = data_api.execute.call_args[0]
    assert "INSERT INTO clouder_label_info" in sql
    assert "ON CONFLICT (label_id) DO UPDATE SET" in sql
    assert params["status"] == "active"
    assert params["country"] == "Sweden"
    assert params["founded_year"] == 1996
    assert params["primary_styles"] == ["techno", "peak-time techno"]
    assert params["tagline"] == "Swedish techno powerhouse since 1996."
    assert params["ai_content"] == "unknown"  # default
    from decimal import Decimal
    assert params["ai_confidence"] == Decimal("0.90") or float(params["ai_confidence"]) == 0.9
    assert params["last_release_date"] == "2026-04-01"


def test_project_ai_suspected_sets_true_when_confirmed_high_confidence():
    repo, data_api = _repo_with_fake()
    data_api.execute.return_value = []
    merged = LabelInfo(
        label_name="X", ai_reasoning="r", summary="s", confidence=0.8,
        ai_content="confirmed",
    )
    repo.project_ai_suspected("lbl-1", merged, threshold=0.5)
    sql, params = data_api.execute.call_args[0]
    assert "UPDATE clouder_labels" in sql
    assert "is_ai_suspected = :value" in sql
    assert params["value"] is True
    assert params["id"] == "lbl-1"


def test_project_ai_suspected_sets_false_when_none_detected_high_confidence():
    repo, data_api = _repo_with_fake()
    data_api.execute.return_value = []
    merged = LabelInfo(
        label_name="X", ai_reasoning="r", summary="s", confidence=0.6,
        ai_content="none_detected",
    )
    repo.project_ai_suspected("lbl-1", merged, threshold=0.5)
    _, params = data_api.execute.call_args[0]
    assert params["value"] is False


def test_project_ai_suspected_no_op_when_below_threshold():
    repo, data_api = _repo_with_fake()
    merged = LabelInfo(
        label_name="X", ai_reasoning="r", summary="s", confidence=0.3,
        ai_content="confirmed",
    )
    repo.project_ai_suspected("lbl-1", merged, threshold=0.5)
    data_api.execute.assert_not_called()


def test_get_label_info_joins_label_name():
    repo, data_api = _repo_with_fake()
    data_api.execute.return_value = [{
        "label_id": "lbl-1",
        "label_name": "Drumcode",
        "last_run_id": "run-1",
        "prompt_slug": "label_v3_app_fields",
        "prompt_version": "v1",
        "merged": {"label_name": "Drumcode"},
        "provenance": {},
        "ai_content": "none_detected",
        "ai_confidence": 0.9,
        "status": "active",
        "primary_styles": ["techno"],
        "tagline": None, "country": "Sweden",
        "founded_year": 1996, "activity": "steady",
        "last_release_date": None,
        "updated_at": "2026-05-18T21:00:00+00:00",
    }]
    row = repo.get_label_info("lbl-1")
    assert row["label_name"] == "Drumcode"
    sql, _ = data_api.execute.call_args[0]
    assert "JOIN clouder_labels" in sql


def test_get_run_parses_jsonb_strings_from_data_api():
    """Regression: Data API returns JSONB columns as JSON-encoded strings.
    The repository must parse vendors/models and cast cost_usd to float so
    the API response matches openapi.yaml.
    """
    from decimal import Decimal as _Decimal

    repo, data_api = _repo_with_fake()
    data_api.execute.return_value = [{
        "id": "r1", "status": "running", "prompt_slug": "label_v3_app_fields",
        "prompt_version": "v1",
        "vendors": '["gemini", "openai"]',
        "models": '{"gemini": "gemini-3-flash-preview"}',
        "merge_vendor": "deepseek", "merge_model": "deepseek-v4-flash",
        "requested_labels": 1, "cells_total": 1, "cells_ok": 0, "cells_error": 0,
        "cost_usd": _Decimal("0.0123"),
    }]
    row = repo.get_run("r1")
    assert row["vendors"] == ["gemini", "openai"]
    assert row["models"] == {"gemini": "gemini-3-flash-preview"}
    assert isinstance(row["cost_usd"], float)
    assert row["cost_usd"] == 0.0123


def test_get_label_info_parses_jsonb_strings_from_data_api():
    """Regression: Data API returns merged/provenance as JSON-encoded strings
    and ai_confidence as Decimal. Parse + cast for API response correctness.
    """
    from decimal import Decimal as _Decimal

    repo, data_api = _repo_with_fake()
    data_api.execute.return_value = [{
        "label_id": "lbl-1",
        "label_name": "Drumcode",
        "last_run_id": "run-1",
        "prompt_slug": "label_v3_app_fields",
        "prompt_version": "v1",
        "merged": '{"label_name": "Drumcode", "confidence": 0.9}',
        "provenance": '{"status": "majority(2/3 definitive)"}',
        "ai_content": "none_detected",
        "ai_confidence": _Decimal("0.9"),
        "status": "active",
        "primary_styles": ["techno"],
        "tagline": None, "country": "Sweden",
        "founded_year": 1996, "activity": "steady",
        "last_release_date": None,
        "updated_at": "2026-05-18T21:00:00+00:00",
    }]
    row = repo.get_label_info("lbl-1")
    assert row["merged"] == {"label_name": "Drumcode", "confidence": 0.9}
    assert row["provenance"] == {"status": "majority(2/3 definitive)"}
    assert isinstance(row["ai_confidence"], float)
    assert row["ai_confidence"] == 0.9


def test_increment_run_counters_atomic_update_only():
    repo, data_api = _repo_with_fake()
    data_api.execute.return_value = []
    repo.increment_run_counters(
        run_id="r-1",
        ok_delta=2,
        error_delta=1,
        cost_delta=0.03,
    )
    sql, params = data_api.execute.call_args[0]
    assert sql.count("UPDATE clouder_label_enrichment_runs") == 1
    assert "cells_ok = cells_ok + :ok" in sql
    assert "cells_error = cells_error + :err" in sql
    assert "cost_usd = cost_usd + :cost" in sql
    assert "CASE WHEN cells_ok + cells_error + :ok + :err >= cells_total" in sql
    assert "THEN 'completed'" in sql
    assert "ELSE status" in sql
    assert "finished_at = CASE" in sql
    assert params["ok"] == 2
    assert params["err"] == 1

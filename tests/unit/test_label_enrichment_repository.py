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

import json
from datetime import datetime, timezone
from unittest.mock import MagicMock

from collector.label_enrichment.auto_repository import AutoEnrichRepository


def _now():
    return datetime(2026, 5, 25, 12, 0, 0, tzinfo=timezone.utc)


def _repo():
    data_api = MagicMock()
    return AutoEnrichRepository(data_api=data_api, now=_now), data_api


def test_get_config_returns_none_when_absent():
    repo, data_api = _repo()
    data_api.execute.return_value = []
    assert repo.get_config("labels") is None


def test_get_config_parses_jsonb_strings():
    repo, data_api = _repo()
    data_api.execute.return_value = [{
        "kind": "labels", "enabled": True,
        "vendors": json.dumps(["gemini"]), "models": json.dumps({"gemini": "g"}),
        "prompt_slug": "s", "prompt_version": "v",
        "merge_vendor": "deepseek", "merge_model": "m",
    }]
    cfg = repo.get_config("labels")
    assert cfg["enabled"] is True
    assert cfg["vendors"] == ["gemini"]
    assert cfg["models"] == {"gemini": "g"}


def test_upsert_config_writes_all_columns():
    repo, data_api = _repo()
    data_api.execute.return_value = []
    repo.upsert_config(
        kind="labels", enabled=True, vendors=["gemini"], models={"gemini": "g"},
        prompt_slug="s", prompt_version="v", merge_vendor="deepseek",
        merge_model="m", user_id="user-1",
    )
    sql, params = data_api.execute.call_args[0]
    assert "INSERT INTO auto_enrich_config" in sql
    assert "ON CONFLICT (kind) DO UPDATE" in sql
    assert params["kind"] == "labels"
    assert params["enabled"] is True
    assert params["vendors"] == ["gemini"]
    assert params["models"] == {"gemini": "g"}
    assert params["updated_by_user_id"] == "user-1"

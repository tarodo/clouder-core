import json
from unittest.mock import MagicMock, patch

import pytest

from collector.label_enrichment_handler import lambda_handler


def _sqs_event(body: dict) -> dict:
    return {"Records": [{"body": json.dumps(body)}]}


def _run_row() -> dict:
    return {
        "id": "run-1",
        "status": "running",
        "prompt_slug": "label_v3_app_fields",
        "prompt_version": "v1",
        "vendors": ["gemini"],
        "models": {"gemini": "gemini-3-flash-preview"},
        "merge_vendor": "deepseek",
        "merge_model": "deepseek-v4-flash",
        "cells_total": 1,
        "cells_ok": 0,
        "cells_error": 0,
    }


@pytest.fixture
def worker_patches(monkeypatch):
    repo = MagicMock()
    repo.get_run.return_value = _run_row()
    auto_repo = MagicMock()

    monkeypatch.setattr(
        "collector.label_enrichment_handler._build_clients",
        lambda: (repo, auto_repo),
    )

    settings_obj = MagicMock(
        gemini_api_key="g", openai_api_key="o",
        tavily_api_key="t", deepseek_api_key="d",
        request_timeout_s=30.0,
        ai_flag_confidence_threshold=0.5,
    )
    monkeypatch.setattr(
        "collector.label_enrichment_handler.get_label_enrichment_worker_settings",
        lambda: settings_obj,
    )

    enrich_calls: list[dict] = []

    def fake_enrich(**kwargs):
        enrich_calls.append(kwargs)

    monkeypatch.setattr(
        "collector.label_enrichment_handler.enrich_label_for_run",
        fake_enrich,
    )

    # Don't actually build adapters
    monkeypatch.setattr(
        "collector.label_enrichment_handler.build_adapters_from_run_config",
        lambda **_: [MagicMock(name="gemini")],
    )

    # Don't actually build the merge client
    monkeypatch.setattr(
        "collector.label_enrichment_handler._build_merge_client",
        lambda *a, **k: MagicMock(),
    )

    yield repo, enrich_calls


def test_worker_dispatches_orchestrator(worker_patches):
    repo, enrich_calls = worker_patches
    event = _sqs_event({
        "run_id": "run-1", "label_id": "lbl-1",
        "label_name": "Drumcode", "style": "techno",
    })
    result = lambda_handler(event, None)
    assert result == {"processed": 1}
    assert len(enrich_calls) == 1
    call = enrich_calls[0]
    assert call["run_id"] == "run-1"
    assert call["label_id"] == "lbl-1"
    assert call["label_name"] == "Drumcode"
    assert call["ai_flag_threshold"] == 0.5


def test_worker_drops_invalid_message(worker_patches):
    repo, enrich_calls = worker_patches
    event = _sqs_event({"run_id": "", "label_id": "x", "label_name": "y", "style": "z"})
    result = lambda_handler(event, None)
    assert result == {"processed": 0}
    assert enrich_calls == []


def test_worker_raises_when_run_missing(worker_patches):
    repo, _ = worker_patches
    repo.get_run.return_value = None
    event = _sqs_event({
        "run_id": "missing", "label_id": "lbl-1",
        "label_name": "x", "style": "y",
    })
    with pytest.raises(RuntimeError, match="run not found"):
        lambda_handler(event, None)


def test_worker_parses_jsonb_strings_from_data_api(monkeypatch):
    """Regression: production Data API returns JSONB columns as JSON-encoded
    strings, not Python list/dict. The worker must parse them before calling
    build_adapters_from_run_config.
    """
    repo = MagicMock()
    repo.get_run.return_value = {
        "id": "run-1",
        "status": "running",
        "prompt_slug": "label_v3_app_fields",
        "prompt_version": "v1",
        # These two come back as JSON strings from the Data API.
        "vendors": '["gemini", "openai"]',
        "models": '{"gemini": "gemini-3-flash-preview", "openai": "gpt-5.4-mini"}',
        "merge_vendor": "deepseek",
        "merge_model": "deepseek-v4-flash",
    }
    auto_repo = MagicMock()
    monkeypatch.setattr(
        "collector.label_enrichment_handler._build_clients",
        lambda: (repo, auto_repo),
    )
    settings_obj = MagicMock(
        gemini_api_key="g", openai_api_key="o",
        tavily_api_key="t", deepseek_api_key="d",
        request_timeout_s=30.0,
        ai_flag_confidence_threshold=0.5,
    )
    monkeypatch.setattr(
        "collector.label_enrichment_handler.get_label_enrichment_worker_settings",
        lambda: settings_obj,
    )

    captured: dict = {}

    def fake_build_adapters(*, vendor_names, models, secrets, request_timeout_s):
        captured["vendor_names"] = vendor_names
        captured["models"] = models
        return [MagicMock(name="adapter")]

    monkeypatch.setattr(
        "collector.label_enrichment_handler.build_adapters_from_run_config",
        fake_build_adapters,
    )
    monkeypatch.setattr(
        "collector.label_enrichment_handler.enrich_label_for_run",
        lambda **kwargs: None,
    )
    monkeypatch.setattr(
        "collector.label_enrichment_handler._build_merge_client",
        lambda *a, **k: MagicMock(),
    )

    event = _sqs_event({
        "run_id": "run-1", "label_id": "lbl-1",
        "label_name": "Drumcode", "style": "techno",
    })
    result = lambda_handler(event, None)
    assert result == {"processed": 1}
    assert captured["vendor_names"] == ["gemini", "openai"]
    assert captured["models"] == {
        "gemini": "gemini-3-flash-preview",
        "openai": "gpt-5.4-mini",
    }


def test_worker_build_repository_passes_kwargs_from_settings(monkeypatch):
    """Regression: _build_repository was called with no args and TypeError'd."""
    from types import SimpleNamespace
    from collector import label_enrichment_handler

    fake_settings = SimpleNamespace(
        is_configured=True,
        aurora_cluster_arn="arn:aws:rds:cluster",
        aurora_secret_arn="arn:aws:secretsmanager:abc",
        aurora_database="postgres",
    )
    monkeypatch.setattr(
        "collector.label_enrichment_handler.get_data_api_settings",
        lambda: fake_settings,
    )

    captured: dict = {}

    def fake_create_client(*, resource_arn, secret_arn, database):
        captured["resource_arn"] = resource_arn
        captured["secret_arn"] = secret_arn
        captured["database"] = database
        return MagicMock(name="data-api-client")

    monkeypatch.setattr(
        "collector.label_enrichment_handler.create_default_data_api_client",
        fake_create_client,
    )

    repo = label_enrichment_handler._build_repository()
    assert repo is not None
    assert captured == {
        "resource_arn": "arn:aws:rds:cluster",
        "secret_arn": "arn:aws:secretsmanager:abc",
        "database": "postgres",
    }


def test_worker_build_repository_raises_when_not_configured(monkeypatch):
    from types import SimpleNamespace
    from collector import label_enrichment_handler

    monkeypatch.setattr(
        "collector.label_enrichment_handler.get_data_api_settings",
        lambda: SimpleNamespace(
            is_configured=False,
            aurora_cluster_arn=None,
            aurora_secret_arn=None,
            aurora_database="postgres",
        ),
    )
    with pytest.raises(RuntimeError, match="not configured"):
        label_enrichment_handler._build_repository()

"""Tests for AI search worker lambda handler."""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock

import pytest

from collector.settings import reset_settings_cache
from collector.search_handler import lambda_handler


class FakeSearchRepo:
    """Minimal repo mock for search worker."""

    def __init__(self) -> None:
        self.saved_results: list[dict[str, Any]] = []
        self.ai_suspected_updates: list[tuple[str, str, bool]] = []

    def save_search_result(
        self,
        result_id: str,
        entity_type: str,
        entity_id: str,
        prompt_slug: str,
        prompt_version: str,
        result: dict,
        searched_at,
    ) -> None:
        self.saved_results.append(
            {
                "result_id": result_id,
                "entity_type": entity_type,
                "entity_id": entity_id,
                "prompt_slug": prompt_slug,
                "prompt_version": prompt_version,
                "result": result,
            }
        )

    def update_entity_is_ai_suspected(
        self,
        entity_type: str,
        entity_id: str,
        value: bool,
        transaction_id: str | None = None,
    ) -> None:
        self.ai_suspected_updates.append((entity_type, entity_id, value))


def _sqs_event(body: dict[str, Any]) -> dict[str, Any]:
    return {
        "Records": [
            {
                "body": json.dumps(body),
                "messageAttributes": {
                    "correlation_id": {
                        "stringValue": "test-cid",
                        "dataType": "String",
                    }
                },
            }
        ]
    }


def _setup_search_worker(monkeypatch, repo=None, search_result=None):
    reset_settings_cache()
    monkeypatch.setenv("PERPLEXITY_API_KEY", "test-key")
    repo = repo or FakeSearchRepo()
    monkeypatch.setattr(
        "collector.search_handler.create_clouder_repository_from_env", lambda: repo
    )

    if search_result is None:
        from collector.search.schemas import LabelSearchResult

        search_result = LabelSearchResult(
            label_name="Test Label",
            style="Techno",
            size="small",
            size_details="About 100 releases",
            age="established",
            age_details="Founded in 2010",
            ai_content="none_detected",
            ai_content_details="No AI content found",
            summary="A small techno label",
            confidence=0.8,
        )

    monkeypatch.setattr(
        "collector.search_handler.search_label",
        lambda label_name, style, config, api_key: search_result,
    )
    return repo


def test_happy_path_processes_label(monkeypatch) -> None:
    repo = _setup_search_worker(monkeypatch)

    event = _sqs_event(
        {
            "label_id": "label-123",
            "label_name": "Test Label",
            "styles": "Techno, House",
            "prompt_slug": "label_info",
            "prompt_version": "v1",
        }
    )
    response = lambda_handler(event, context=None)

    assert response == {"processed": 1}
    assert len(repo.saved_results) == 1
    saved = repo.saved_results[0]
    assert saved["entity_type"] == "label"
    assert saved["entity_id"] == "label-123"
    assert saved["prompt_slug"] == "label_info"
    assert saved["prompt_version"] == "v1"
    assert saved["result"]["label_name"] == "Test Label"
    reset_settings_cache()


def test_invalid_message_is_skipped(monkeypatch) -> None:
    _setup_search_worker(monkeypatch)

    event = {
        "Records": [
            {
                "body": "{bad-json}",
                "messageAttributes": {},
            }
        ]
    }
    response = lambda_handler(event, context=None)

    assert response == {"processed": 0}
    reset_settings_cache()


def test_no_records_returns_zero(monkeypatch) -> None:
    _setup_search_worker(monkeypatch)

    response = lambda_handler({"Records": []}, context=None)

    assert response == {"processed": 0}
    reset_settings_cache()


def test_non_list_records_returns_zero() -> None:
    response = lambda_handler({"no_records": True}, context=None)

    assert response == {"processed": 0}


def test_permanent_error_does_not_reraise(monkeypatch) -> None:
    """ValueError (permanent) should NOT re-raise."""
    _setup_search_worker(monkeypatch)
    monkeypatch.setattr(
        "collector.search_handler.search_label",
        lambda label_name, style, config, api_key: (_ for _ in ()).throw(
            ValueError("bad data")
        ),
    )

    event = _sqs_event(
        {
            "label_id": "label-err",
            "label_name": "Bad Label",
            "styles": "Techno",
            "prompt_slug": "label_info",
            "prompt_version": "v1",
        }
    )
    response = lambda_handler(event, context=None)

    assert response == {"processed": 0}
    reset_settings_cache()


def test_transient_error_reraises_for_sqs_retry(monkeypatch) -> None:
    """RuntimeError (transient) should re-raise."""
    _setup_search_worker(monkeypatch)
    monkeypatch.setattr(
        "collector.search_handler.search_label",
        lambda label_name, style, config, api_key: (_ for _ in ()).throw(
            RuntimeError("API timeout")
        ),
    )

    event = _sqs_event(
        {
            "label_id": "label-transient",
            "label_name": "Timeout Label",
            "styles": "Techno",
            "prompt_slug": "label_info",
            "prompt_version": "v1",
        }
    )

    with pytest.raises(RuntimeError, match="API timeout"):
        lambda_handler(event, context=None)

    reset_settings_cache()


def test_missing_aurora_config_raises(monkeypatch) -> None:
    reset_settings_cache()
    monkeypatch.setenv("PERPLEXITY_API_KEY", "test-key")
    monkeypatch.setattr(
        "collector.search_handler.create_clouder_repository_from_env", lambda: None
    )

    with pytest.raises(RuntimeError, match="AURORA Data API"):
        lambda_handler({"Records": [{"body": "{}"}]}, context=None)

    reset_settings_cache()


def test_happy_path_accepts_entity_search_message(monkeypatch) -> None:
    repo = _setup_search_worker(monkeypatch)

    event = _sqs_event(
        {
            "entity_type": "label",
            "entity_id": "label-456",
            "prompt_slug": "label_info",
            "prompt_version": "v1",
            "context": {"label_name": "Entity Label", "styles": "House"},
        }
    )
    response = lambda_handler(event, context=None)

    assert response == {"processed": 1}
    assert len(repo.saved_results) == 1
    saved = repo.saved_results[0]
    assert saved["entity_type"] == "label"
    assert saved["entity_id"] == "label-456"
    assert saved["result"]["label_name"] == "Test Label"
    reset_settings_cache()


def test_unknown_entity_type_is_skipped(monkeypatch) -> None:
    repo = _setup_search_worker(monkeypatch)

    event = _sqs_event(
        {
            "entity_type": "artist",
            "entity_id": "artist-1",
            "prompt_slug": "artist_info",
            "prompt_version": "v1",
            "context": {},
        }
    )
    response = lambda_handler(event, context=None)

    assert response == {"processed": 0}
    assert repo.saved_results == []
    reset_settings_cache()


def test_label_search_skipped_when_context_missing_keys(monkeypatch) -> None:
    repo = _setup_search_worker(monkeypatch)

    event = _sqs_event(
        {
            "entity_type": "label",
            "entity_id": "label-789",
            "prompt_slug": "label_info",
            "prompt_version": "v1",
            "context": {},
        }
    )
    response = lambda_handler(event, context=None)

    assert response == {"processed": 0}
    assert repo.saved_results == []
    reset_settings_cache()

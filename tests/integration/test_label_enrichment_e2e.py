"""End-to-end: POST /admin/labels/enrich → SQS stub → worker → DB.

Real DB writes go through the existing integration repository (or a
FakeDataApi if the suite doesn't stand up Aurora — see comment in
Step 1 for how this is normally wired).
"""

import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from collector.handler import lambda_handler as api_handler
from collector.label_enrichment_handler import lambda_handler as worker_handler
from collector.label_enrichment.schemas import LabelInfo
from collector.label_enrichment.vendors.base import VendorResponse


def _admin_event(body: dict) -> dict:
    return {
        "routeKey": "POST /admin/labels/enrich",
        "body": json.dumps(body),
        "pathParameters": {},
        "requestContext": {
            "authorizer": {"lambda": {"is_admin": True, "user_id": "user-1"}},
        },
    }


def _stub_vendor_response(vendor: str) -> VendorResponse:
    return VendorResponse(
        parsed=LabelInfo(
            label_name="Drumcode",
            ai_reasoning="none",
            summary="Swedish techno",
            confidence=0.9,
            country="Sweden",
            founded_year=1996,
            status="active",
            primary_styles=["techno"],
        ),
        raw={}, citations=[],
        usage={"input_tokens": 100, "output_tokens": 50, "cost_usd": 0.002},
        latency_ms=200, model=f"{vendor}-model",
    )


@pytest.fixture
def repo_and_sqs(monkeypatch):
    """Wire repository + SQS to a shared stub so the API & worker see the same state."""
    captured_messages: list[str] = []

    class FakeSqs:
        def send_message(self, *, QueueUrl, MessageBody):
            captured_messages.append(MessageBody)

    real_repo = MagicMock()
    real_repo.upsert_label_by_name.side_effect = lambda name: f"lbl-{name.lower().replace(' ', '-')}"
    real_repo.create_run.return_value = "run-1"

    run_state = {
        "id": "run-1",
        "status": "queued",
        "prompt_slug": "label_v3_app_fields",
        "prompt_version": "v1",
        "vendors": ["gemini", "openai", "tavily_deepseek"],
        "models": {
            "gemini": "gemini-3-flash-preview",
            "openai": "gpt-5.4-mini",
            "tavily_deepseek": "deepseek-v4-flash",
        },
        "merge_vendor": "deepseek",
        "merge_model": "deepseek-v4-flash",
        "cells_total": 3,
        "cells_ok": 0, "cells_error": 0,
    }
    real_repo.get_run.return_value = run_state

    monkeypatch.setattr(
        "collector.label_enrichment.routes._build_repository", lambda: real_repo,
    )
    monkeypatch.setattr(
        "collector.label_enrichment.routes._build_sqs_client", lambda: FakeSqs(),
    )
    # The worker builds both the label repo and an auto-enrich repo via
    # _build_clients(); the auto repo only stamps label_auto_enrich_state
    # outcomes, which this e2e doesn't assert on — a bare mock suffices.
    monkeypatch.setattr(
        "collector.label_enrichment_handler._build_clients",
        lambda: (real_repo, MagicMock()),
    )
    monkeypatch.setenv("LABEL_ENRICHMENT_QUEUE_URL", "https://sqs.example/q")

    # Stub vendor factory in the worker
    def fake_adapters(*, vendor_names, models, secrets, request_timeout_s):
        adapters = []
        for v in vendor_names:
            a = MagicMock()
            a.name = v
            a.default_model = models[v]
            a.run.return_value = _stub_vendor_response(v)
            adapters.append(a)
        return adapters

    monkeypatch.setattr(
        "collector.label_enrichment_handler.build_adapters_from_run_config",
        fake_adapters,
    )

    # Stub merge client
    merge = MagicMock()
    merge.chat.completions.create.return_value = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps({
            "tagline": "Swedish techno powerhouse.",
            "summary": "Established techno label.",
            "ai_reasoning": "No AI signals.",
            "notes": None,
        })))],
        usage=SimpleNamespace(prompt_tokens=200, completion_tokens=80),
    )
    monkeypatch.setattr(
        "collector.label_enrichment_handler._build_merge_client", lambda *a, **k: merge,
    )

    # Stub settings
    monkeypatch.setattr(
        "collector.label_enrichment_handler.get_label_enrichment_worker_settings",
        lambda: MagicMock(
            gemini_api_key="g", openai_api_key="o",
            tavily_api_key="t", deepseek_api_key="d",
            request_timeout_s=30.0,
            ai_flag_confidence_threshold=0.5,
        ),
    )
    yield real_repo, captured_messages


def test_e2e_post_then_worker_writes_full_chain(repo_and_sqs):
    real_repo, captured_messages = repo_and_sqs

    # 1) POST creates the run + enqueues messages
    body = {
        "labels": [{"label_name": "Drumcode", "style": "techno"}],
        "vendors": ["gemini", "openai", "tavily_deepseek"],
        "models": {
            "gemini": "gemini-3-flash-preview",
            "openai": "gpt-5.4-mini",
            "tavily_deepseek": "deepseek-v4-flash",
        },
        "prompt_slug": "label_v3_app_fields",
        "prompt_version": "v1",
        "merge_vendor": "deepseek",
        "merge_model": "deepseek-v4-flash",
    }
    resp = api_handler(_admin_event(body), None)
    assert resp["statusCode"] == 202
    assert len(captured_messages) == 1

    # 2) Worker processes the message
    sqs_event = {"Records": [{"body": captured_messages[0]}]}
    result = worker_handler(sqs_event, None)
    assert result == {"processed": 1}

    # 3) Repository was driven correctly
    real_repo.mark_run_running.assert_called_once_with("run-1")
    assert real_repo.insert_cell.call_count == 3
    real_repo.upsert_label_info.assert_called_once()
    real_repo.project_ai_suspected.assert_called_once()
    real_repo.increment_run_counters.assert_called_once()

    counters = real_repo.increment_run_counters.call_args.kwargs
    assert counters["ok_delta"] == 3
    assert counters["error_delta"] == 0
    assert counters["cost_delta"] > 0.0


def test_e2e_post_by_label_id_writes_full_chain(repo_and_sqs):
    real_repo, captured_messages = repo_and_sqs
    real_repo.get_label_by_id.return_value = {
        "id": "lbl-fokuz",
        "name": "Fokuz Recordings",
    }
    real_repo.derive_style_for_label.return_value = "drum and bass"

    body = {
        "labels": [{"label_id": "lbl-fokuz"}],
        "vendors": ["gemini", "openai", "tavily_deepseek"],
        "models": {
            "gemini": "gemini-3-flash-preview",
            "openai": "gpt-5.4-mini",
            "tavily_deepseek": "deepseek-v4-flash",
        },
        "prompt_slug": "label_v3_app_fields",
        "prompt_version": "v1",
        "merge_vendor": "deepseek",
        "merge_model": "deepseek-v4-flash",
    }
    resp = api_handler(_admin_event(body), None)
    assert resp["statusCode"] == 202
    assert len(captured_messages) == 1
    msg = json.loads(captured_messages[0])
    assert msg["label_id"] == "lbl-fokuz"
    assert msg["label_name"] == "Fokuz Recordings"
    assert msg["style"] == "drum and bass"

    sqs_event = {"Records": [{"body": captured_messages[0]}]}
    result = worker_handler(sqs_event, None)
    assert result == {"processed": 1}
    assert real_repo.insert_cell.call_count == 3
    real_repo.upsert_label_info.assert_called_once()

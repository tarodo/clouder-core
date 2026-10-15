"""Out-of-credit vendor errors reach the logs and page by email (infra/enrichment_alarms.tf)."""

from __future__ import annotations

import re
from pathlib import Path
from types import SimpleNamespace

import pytest

from collector.artist_enrichment import orchestrator as artist_orch
from collector.label_enrichment import orchestrator as label_orch
from collector.label_enrichment.vendors.base import VendorResponse

TF = Path(__file__).resolve().parents[2] / "infra" / "enrichment_alarms.tf"

OPENAI_NO_QUOTA = (
    "RateLimitError: Error code: 429 - {'error': {'message': 'You exceeded your current "
    "quota', 'type': 'insufficient_quota', 'code': 'insufficient_quota'}}"
)


def _failed(error: str) -> VendorResponse:
    return VendorResponse(
        parsed=None, raw={}, citations=[], usage={}, latency_ms=1, model="m", error=error
    )


@pytest.mark.parametrize(
    ("orch", "call"),
    [
        (label_orch, lambda r: label_orch._cell_payload(SimpleNamespace(name="openai"), r, "L")),
        (artist_orch, lambda r: artist_orch._cell_payload(SimpleNamespace(name="openai"), r, "A")),
    ],
)
def test_vendor_error_is_logged(monkeypatch, orch, call) -> None:
    # Vendor errors used to land only in the run's DB cells, invisible to alarms.
    events = []
    monkeypatch.setattr(orch, "log_event", lambda level, msg, **f: events.append((level, msg, f)))
    call(_failed(OPENAI_NO_QUOTA))
    assert events == [
        (
            "WARNING",
            "enrichment_vendor_error",
            {"vendor": "openai", "error_message": OPENAI_NO_QUOTA},
        )
    ]


def test_successful_vendor_call_logs_nothing(monkeypatch) -> None:
    events = []
    monkeypatch.setattr(label_orch, "log_event", lambda *a, **f: events.append(a))
    ok = VendorResponse(parsed=None, raw={}, citations=[], usage={}, latency_ms=1, model="m")
    label_orch._cell_payload(SimpleNamespace(name="openai"), ok, "L")
    assert events == []


def _blocks(kind: str) -> list[str]:
    return re.findall(rf'resource "{kind}" "[a-z_]+" \{{(.*?)\n\}}', TF.read_text(), re.S)


def test_filters_watch_both_enricher_log_groups_for_credit_errors() -> None:
    (f,) = _blocks("aws_cloudwatch_log_metric_filter")
    assert "for_each       = local.enrichment_credit_log_groups" in f
    groups = set(re.findall(r"aws_cloudwatch_log_group\.(\w+)\.name", TF.read_text()))
    assert groups == {"label_enricher_worker", "artist_enricher_worker"}
    assert "402 Payment Required" in f  # Tavily, DeepSeek
    assert "insufficient_quota" in f  # OpenAI


def test_alarm_emails_on_first_credit_error() -> None:
    (alarm,) = _blocks("aws_cloudwatch_metric_alarm")
    assert re.search(r"threshold\s*=\s*1\b", alarm)
    assert re.search(r'treat_missing_data\s*=\s*"notBreaching"', alarm)
    assert re.search(r"alarm_actions\s*=\s*local\.alarm_actions", alarm)

"""The overview dashboard shows every signal an alarm watches."""

from __future__ import annotations

import re
from pathlib import Path

INFRA = Path(__file__).resolve().parents[2] / "infra"


def _dashboard() -> str:
    tf = INFRA / "dashboard.tf"
    assert tf.exists(), "infra/dashboard.tf is missing"
    return tf.read_text()


def test_overview_dashboard_is_defined_as_code() -> None:
    assert re.search(r'dashboard_name\s*=\s*"\$\{local\.name_prefix\}-overview"', _dashboard())


def test_dashboard_covers_every_alarmed_signal() -> None:
    body = _dashboard()
    for needle in (
        "for fn in local.all_lambdas",  # errors of every function
        '"AWS/Lambda", "Errors"',
        '"AWS/ApiGateway", "5xx"',
        '"AWS/ApiGateway", "Latency"',
        '"AWS/SQS", "ApproximateAgeOfOldestMessage"',
        "for q in local.dlq_queues",
        '"AWS/SQS", "ApproximateNumberOfMessagesVisible"',
        '"AWS/RDS", "ServerlessDatabaseCapacity"',
        "local.data_quality_namespace, \"FailedChecks\"",
        '"CLOUDER/AutoIngest", "AutoIngestRunFailed"',
        '"AWS/Firehose", "DeliveryToS3.DataFreshness"',
    ):
        assert needle in body, needle


def test_dashboard_charts_every_data_quality_slo() -> None:
    from collector.data_quality import CHECKS

    body = _dashboard()
    for check in CHECKS:
        if check.threshold is None:
            continue  # recorded only, no SLO
        assert f'"{check.name}"' in body, check.name
        if check.comparison == "min":
            assert re.search(rf"value\s*=\s*{check.threshold:g}\b", body), check.name  # SLO line


def test_dashboard_opens_on_a_week_with_each_widget_period() -> None:
    # Data-quality metrics land once a night: the 3 h default range would show them empty.
    body = _dashboard()
    assert re.search(r'start\s*=\s*"-P7D"', body)
    assert re.search(r'periodOverride\s*=\s*"inherit"', body)

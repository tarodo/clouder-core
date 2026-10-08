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

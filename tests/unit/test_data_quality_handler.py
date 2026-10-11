"""Publishing data-quality results and the Lambda entry point."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from botocore.exceptions import ClientError

from collector import data_quality_handler
from collector.data_quality import CheckResult
from collector.settings import reset_settings_cache

NOW = datetime(2026, 10, 7, 0, 10, tzinfo=UTC)


class FakeCloudWatch:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def put_metric_data(self, **kwargs) -> None:
        self.calls.append(kwargs)


def _results() -> list[CheckResult]:
    return [
        CheckResult("stuck_ingest_runs", 1.0, 0, "max", False),
        CheckResult("isrc_coverage_pct", None, 99, "min", True),
        CheckResult("spotify_match_pct", 96.9, 95, "min", True),
    ]


def test_publish_skips_checks_without_value() -> None:
    cw = FakeCloudWatch()

    failed = data_quality_handler.publish(_results(), cw, now=NOW)

    (call,) = cw.calls
    assert call["Namespace"] == "CLOUDER/DataQuality"
    assert [(m["MetricName"], m["Value"]) for m in call["MetricData"]] == [
        ("stuck_ingest_runs", 1.0),
        ("spotify_match_pct", 96.9),
        ("FailedChecks", 1),
    ]
    assert failed == 1


def test_handler_runs_checks_publishes_and_reports(monkeypatch) -> None:
    cw = FakeCloudWatch()
    monkeypatch.setenv("AURORA_CLUSTER_ARN", "arn:aws:rds:us-east-1:000000000000:cluster:c")
    monkeypatch.setenv(
        "AURORA_SECRET_ARN", "arn:aws:secretsmanager:us-east-1:000000000000:secret:s"
    )
    monkeypatch.setenv("AURORA_DATABASE", "clouder")
    reset_settings_cache()  # get_data_api_settings is lru_cached
    monkeypatch.setattr(
        data_quality_handler, "create_default_data_api_client", lambda **_: object()
    )
    monkeypatch.setattr(data_quality_handler, "run_checks", lambda client, today: _results())
    monkeypatch.setattr(data_quality_handler, "wake_database", lambda client: None)
    monkeypatch.setattr(data_quality_handler, "_cloudwatch", lambda: cw)

    out = data_quality_handler.lambda_handler({}, None)

    assert out["failed_checks"] == 1
    assert [r["name"] for r in out["results"]] == [
        "stuck_ingest_runs",
        "isrc_coverage_pct",
        "spotify_match_pct",
    ]
    assert len(cw.calls) == 1
    reset_settings_cache()


def _resuming() -> ClientError:
    return ClientError(
        {"Error": {"Code": "DatabaseResumingException", "Message": "resuming"}}, "ExecuteStatement"
    )


class Waking:
    def __init__(self, failures: int, error=_resuming) -> None:
        self.failures, self.error, self.calls = failures, error, 0

    def execute(self, sql, params=None, transaction_id=None):
        self.calls += 1
        if self.calls <= self.failures:
            raise self.error()
        return [{"?column?": 1}]


def test_wake_database_waits_for_a_resuming_aurora() -> None:
    client = Waking(failures=3)

    data_quality_handler.wake_database(
        client, deadline_s=60, sleep=lambda s: None, clock=iter(range(0, 1000, 5)).__next__
    )

    assert client.calls == 4


def test_wake_database_gives_up_after_the_deadline() -> None:
    client = Waking(failures=10**6)

    with pytest.raises(ClientError):
        data_quality_handler.wake_database(
            client, deadline_s=60, sleep=lambda s: None, clock=iter(range(0, 1000, 20)).__next__
        )
    assert client.calls == 3


def test_wake_database_does_not_hide_other_errors() -> None:
    other = lambda: ClientError({"Error": {"Code": "BadRequestException"}}, "ExecuteStatement")  # noqa: E731
    client = Waking(failures=1, error=other)

    with pytest.raises(ClientError):
        data_quality_handler.wake_database(
            client, deadline_s=60, sleep=lambda s: None, clock=iter(range(0, 1000, 5)).__next__
        )

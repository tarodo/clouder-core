"""Scheduled Lambda: run the data-quality checks and publish them to CloudWatch.

EventBridge triggers it nightly at 00:10 UTC. The 00:00 catalog export usually
leaves Aurora awake (it auto-pauses after 300 s idle), but not always, so the run
first waits for the database with a wake-up probe. Read-only; its own role may only
call the Data API, read the cluster secret and put metrics into CLOUDER/DataQuality.
"""

from __future__ import annotations

import time
from dataclasses import asdict
from datetime import datetime, timezone
from typing import Any, Callable, Mapping, Sequence

from botocore.exceptions import ClientError

from .data_api import create_default_data_api_client
from .data_quality import NAMESPACE, CheckResult, run_checks
from .logging_utils import log_event
from .settings import get_data_api_settings


def _cloudwatch() -> Any:
    import boto3

    return boto3.client("cloudwatch")


def wake_database(
    client: Any,
    *,
    deadline_s: float = 60.0,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> None:
    """Probe with SELECT 1 until a resuming Aurora answers or the deadline passes.

    A resume can outlast the Data API client's own retries; without the probe
    every check would be recorded as failed and the alarm would fire on a paused
    database instead of bad data. Other errors, and a resume that never ends,
    propagate so the Lambda fails and EventBridge retries it.
    """
    start = clock()
    while True:
        try:
            client.execute("SELECT 1")
            return
        except ClientError as exc:
            resuming = exc.response.get("Error", {}).get("Code") == "DatabaseResumingException"
            if not resuming or clock() - start >= deadline_s:
                raise
            sleep(5)


def publish(results: Sequence[CheckResult], cloudwatch: Any, *, now: datetime) -> int:
    failed = sum(1 for r in results if not r.passed)
    metric_data = [
        {"MetricName": r.name, "Value": r.value, "Unit": "None", "Timestamp": now}
        for r in results
        if r.value is not None
    ]
    metric_data.append({"MetricName": "FailedChecks", "Value": failed, "Unit": "Count", "Timestamp": now})
    cloudwatch.put_metric_data(Namespace=NAMESPACE, MetricData=metric_data)
    return failed


def lambda_handler(event: Mapping[str, Any] | None, context: Any) -> dict[str, Any]:
    settings = get_data_api_settings()
    if not settings.is_configured:
        raise RuntimeError("Aurora Data API not configured")
    client = create_default_data_api_client(
        resource_arn=str(settings.aurora_cluster_arn),
        secret_arn=str(settings.aurora_secret_arn),
        database=settings.aurora_database,
    )
    wake_database(client)
    now = datetime.now(timezone.utc)
    results = run_checks(client, now.date())
    for r in results:
        log_event(
            "INFO" if r.passed else "WARNING", "dq_check_result",
            check=r.name, value=r.value, threshold=r.threshold, passed=r.passed,
        )
    failed = publish(results, _cloudwatch(), now=now)
    log_event("INFO", "dq_run_completed", failed_checks=failed, count=len(results))
    return {"failed_checks": failed, "results": [asdict(r) for r in results]}

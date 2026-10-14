from __future__ import annotations

import re
from pathlib import Path

TF = "\n".join(p.read_text() for p in Path("infra").glob("*.tf"))


def _block(kind: str, name: str) -> str:
    m = re.search(rf'resource "{kind}" "{name}" \{{(.*?)\n\}}', TF, re.S)
    assert m, f"{kind}.{name} missing"
    return m.group(1)


def test_concurrency_is_bounded_by_the_trigger_alone() -> None:
    # AWS rejects an SQS trigger whose maximum_concurrency (>= 2) exceeds the
    # function's reserved concurrency, so the trigger cap is the only bound.
    worker = _block("aws_lambda_function", "youtube_search_worker")
    assert "reserved_concurrent_executions" not in worker
    esm = _block("aws_lambda_event_source_mapping", "youtube_search_queue")
    assert "maximum_concurrency = var.youtube_search_max_concurrency" in esm


def test_worker_gets_its_pace_and_queue() -> None:
    body = _block("aws_lambda_function", "youtube_search_worker")
    for env in (
        "YOUTUBE_SEARCH_QUEUE_URL",
        "YOUTUBE_SEARCH_SINCE",
        "YOUTUBE_SEARCH_MIN_INTERVAL_MS",
        "YOUTUBE_SEARCH_BAN_SECONDS",
        "FUZZY_MATCH_THRESHOLD",
    ):
        assert env in body


def test_canonicalization_can_start_the_sweep() -> None:
    assert "YOUTUBE_SEARCH_QUEUE_URL" in _block("aws_lambda_function", "canonicalization_worker")
    assert (
        "aws_sqs_queue.youtube_search.arn"
        in TF.split('module "role_canonicalization_worker"')[1].split("module ")[0]
    )


def test_dlq_is_alarmed() -> None:
    assert "youtube_search_dlq.name" in TF


def test_throttled_messages_are_not_dead_lettered_early() -> None:
    # Reserved concurrency 1 under an SQS trigger throttles extra polls; each
    # throttle counts as a receive (AWS advises maxReceiveCount >= 5).
    body = _block("aws_sqs_queue", "youtube_search")
    assert int(re.search(r"maxReceiveCount\s*=\s*(\d+)", body).group(1)) >= 10

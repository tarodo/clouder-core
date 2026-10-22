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
        "YOUTUBE_SEARCH_MIN_INTERVAL_MS",
        "YOUTUBE_SEARCH_BAN_SECONDS",
        "FUZZY_MATCH_THRESHOLD",
    ):
        assert env in body


def test_an_hourly_rule_queues_one_batch() -> None:
    rule = _block("aws_cloudwatch_event_rule", "youtube_search_hourly")
    assert 'schedule_expression = "rate(1 hour)"' in rule
    target = _block("aws_cloudwatch_event_target", "youtube_search_hourly")
    assert "arn       = aws_sqs_queue.youtube_search.arn" in target
    assert "batch_size = var.youtube_search_batch_size" in target
    policy = _block("aws_sqs_queue_policy", "youtube_search")
    assert "events.amazonaws.com" in policy
    assert "aws_cloudwatch_event_rule.youtube_search_hourly.arn" in policy


def test_neither_ingest_nor_the_worker_queues_searches() -> None:
    # The hourly rule is the only producer: no post-ingest start, no chaining.
    assert "YOUTUBE_SEARCH_QUEUE_URL" not in _block(
        "aws_lambda_function", "canonicalization_worker"
    )
    assert "YOUTUBE_SEARCH_QUEUE_URL" not in _block("aws_lambda_function", "youtube_search_worker")
    senders = [
        line
        for line in TF.splitlines()
        if '"sqs:SendMessage"' in line and "aws_sqs_queue.youtube_search.arn" in line
    ]
    assert senders == []


def test_dlq_is_alarmed() -> None:
    assert "youtube_search_dlq.name" in TF


def test_throttled_messages_are_not_dead_lettered_early() -> None:
    # Reserved concurrency 1 under an SQS trigger throttles extra polls; each
    # throttle counts as a receive (AWS advises maxReceiveCount >= 5).
    body = _block("aws_sqs_queue", "youtube_search")
    assert int(re.search(r"maxReceiveCount\s*=\s*(\d+)", body).group(1)) >= 10

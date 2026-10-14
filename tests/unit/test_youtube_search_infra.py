from __future__ import annotations

import re
from pathlib import Path

TF = "\n".join(p.read_text() for p in Path("infra").glob("*.tf"))


def _block(kind: str, name: str) -> str:
    m = re.search(rf'resource "{kind}" "{name}" \{{(.*?)\n\}}', TF, re.S)
    assert m, f"{kind}.{name} missing"
    return m.group(1)


def test_one_worker_at_a_time() -> None:
    assert "reserved_concurrent_executions = 1" in _block("aws_lambda_function", "youtube_search_worker")


def test_worker_gets_its_pace_and_queue() -> None:
    body = _block("aws_lambda_function", "youtube_search_worker")
    for env in ("YOUTUBE_SEARCH_QUEUE_URL", "YOUTUBE_SEARCH_SINCE", "YOUTUBE_SEARCH_MIN_INTERVAL_MS",
                "YOUTUBE_SEARCH_BAN_SECONDS", "FUZZY_MATCH_THRESHOLD"):
        assert env in body


def test_canonicalization_can_start_the_sweep() -> None:
    assert "YOUTUBE_SEARCH_QUEUE_URL" in _block("aws_lambda_function", "canonicalization_worker")
    assert "aws_sqs_queue.youtube_search.arn" in TF.split('module "role_canonicalization_worker"')[1].split("module ")[0]


def test_dlq_is_alarmed() -> None:
    assert "youtube_search_dlq.name" in TF

"""The Spotify search queue is drained by a bounded number of paced workers."""

from __future__ import annotations

import re
from pathlib import Path

INFRA = Path(__file__).resolve().parents[2] / "infra"
TF = "\n".join(p.read_text() for p in sorted(INFRA.glob("*.tf")))


def _block(header: str) -> str:
    start = TF.index(header)
    return TF[start : TF.index("\n}\n", start)]


def test_the_queue_trigger_caps_parallel_workers() -> None:
    esm = _block('resource "aws_lambda_event_source_mapping" "spotify_search_queue"')
    assert re.search(r"maximum_concurrency\s*=\s*var\.spotify_search_max_concurrency", esm)
    var = _block('variable "spotify_search_max_concurrency"')
    assert re.search(r"default\s*=\s*2\b", var)  # the SQS trigger's minimum


def test_each_worker_paces_its_spotify_calls() -> None:
    fn = _block('resource "aws_lambda_function" "spotify_search_worker"')
    assert re.search(
        r"SPOTIFY_MIN_REQUEST_INTERVAL_MS\s*=\s*var\.spotify_min_request_interval_ms", fn
    )
    var = _block('variable "spotify_min_request_interval_ms"')
    assert re.search(r"default\s*=\s*650\b", var)  # two workers stay near 3 requests a second

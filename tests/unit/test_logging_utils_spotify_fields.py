"""Spotify coverage numbers must survive the ALLOWED_LOG_FIELDS whitelist.

`spotify_search_completed` passes total_tracks/found/not_found to log_event,
but none of them were whitelisted, so structlog dropped exactly the numbers the
event exists to report — the line reached CloudWatch with only correlation_id
and s3_key, and coverage could only be recovered from S3.
"""

from __future__ import annotations

import json

from collector import logging_utils as lu


def test_spotify_coverage_fields_are_whitelisted() -> None:
    for field in ("total_tracks", "found", "not_found", "batch_id", "batch_size", "track_count"):
        assert field in lu.ALLOWED_LOG_FIELDS, field


def test_spotify_search_completed_keeps_its_numbers(capsys) -> None:
    lu.log_event(
        "INFO",
        "spotify_search_completed",
        correlation_id="cid-1",
        batch_id="b1",
        total_tracks=1422,
        found=1379,
        not_found=43,
        s3_key="raw/sp/tracks/date=2026-09-13/cid-1/b1/results.json.gz",
    )

    payload = json.loads(capsys.readouterr().out.strip().splitlines()[-1])

    assert payload["total_tracks"] == 1422
    assert payload["found"] == 1379
    assert payload["not_found"] == 43
    assert payload["batch_id"] == "b1"


def test_whitelist_still_drops_unknown_fields(capsys) -> None:
    lu.log_event("INFO", "spotify_search_completed", made_up_field="leak")

    payload = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert "made_up_field" not in payload

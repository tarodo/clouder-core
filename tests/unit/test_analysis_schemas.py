"""Request schemas of the analysis API: field limits and the ai_detect result shape."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from collector.schemas import (
    AnalysisClaimRequest,
    AnalysisRequeueRequest,
    AnalysisResultsRequest,
)

LEASE = "6f1c2a4e-0000-4000-8000-000000000000"


def _item(**over) -> dict:
    item = {
        "track_id": "t1",
        "analyzer": "ai_detect",
        "version": "artifactnet-9.4/rms0.1/median/0.225",
        "status": "ok",
        "result": {"ai_detected": True, "score": 0.71, "segments": [0.7, 0.8]},
        "error": None,
        "audio_sha256": "a" * 64,
        "video_id": "dQw4w9WgXcQ",
    }
    return {**item, **over}


def _results(*items: dict) -> AnalysisResultsRequest:
    return AnalysisResultsRequest.model_validate({"lease_id": LEASE, "results": list(items)})


def test_claim_defaults_and_limits() -> None:
    assert AnalysisClaimRequest.model_validate({"analyzers": ["ai_detect"]}).limit == 20
    for bad in (
        {"analyzers": ["ai_detect"], "limit": 0},
        {"analyzers": ["ai_detect"], "limit": 51},
        {"analyzers": []},
        {"analyzers": ["a" + str(i) for i in range(9)]},
        {"analyzers": ["AI"]},
        {"analyzers": ["ai_detect", "ai_detect"]},
        {"analyzers": ["ai_detect"], "extra": 1},
    ):
        with pytest.raises(ValidationError):
            AnalysisClaimRequest.model_validate(bad)


def test_results_accept_a_valid_batch() -> None:
    failed = _item(track_id="t2", status="failed", result=None, error="Video unavailable")
    req = _results(_item(), failed)
    assert [r.status for r in req.results] == ["ok", "failed"]


@pytest.mark.parametrize(
    "over",
    [
        {"status": "ok", "result": None},
        {"status": "failed", "result": None, "error": None},
        {"status": "failed", "error": "x"},  # failed must not carry a result
        {"status": "done"},
        {"version": ""},
        {"version": "v" * 65},
        {"error": "e" * 501, "status": "failed", "result": None},
        {"audio_sha256": "A" * 64},
        {"audio_sha256": "a" * 63},
        {"video_id": "v" * 33},
        {"analyzer": "Bad"},
    ],
)
def test_results_reject_bad_items(over) -> None:
    with pytest.raises(ValidationError):
        _results(_item(**over))


@pytest.mark.parametrize(
    "result",
    [
        {"score": 0.5},
        {"ai_detected": "yes", "score": 0.5},
        {"ai_detected": True},
        {"ai_detected": True, "score": 1.5},
        {"ai_detected": True, "score": -0.1},
        {"ai_detected": True, "score": float("nan")},
        {"ai_detected": True, "score": True},
    ],
)
def test_ai_detect_ok_result_needs_flag_and_score(result) -> None:
    with pytest.raises(ValidationError):
        _results(_item(result=result))


def test_other_analyzers_results_are_opaque() -> None:
    req = _results(_item(analyzer="embed", result={"vector_ref": "x"}))
    assert req.results[0].result == {"vector_ref": "x"}


def test_result_over_32_kb_is_rejected() -> None:
    big = {"ai_detected": True, "score": 0.5, "pad": "x" * 33_000}
    with pytest.raises(ValidationError):
        _results(_item(result=big))


def test_results_batch_limits_and_duplicates() -> None:
    with pytest.raises(ValidationError):
        AnalysisResultsRequest.model_validate({"lease_id": LEASE, "results": []})
    with pytest.raises(ValidationError):
        _results(*[_item(track_id=f"t{i}") for i in range(101)])
    with pytest.raises(ValidationError):
        _results(_item(), _item())
    with pytest.raises(ValidationError):
        AnalysisResultsRequest.model_validate({"lease_id": "nope", "results": [_item()]})


def test_requeue_scopes() -> None:
    assert AnalysisRequeueRequest.model_validate({"analyzer": "ai_detect", "scope": "all"})
    ok = AnalysisRequeueRequest.model_validate(
        {"analyzer": "ai_detect", "scope": "recent", "days": 7, "include_failed": True}
    )
    assert (ok.days, ok.include_failed) == (7, True)
    for bad in (
        {"analyzer": "ai_detect", "scope": "recent"},
        {"analyzer": "ai_detect", "scope": "recent", "days": 366},
        {"analyzer": "ai_detect", "scope": "all", "days": 3},
        {"analyzer": "ai_detect", "scope": "everything"},
    ):
        with pytest.raises(ValidationError):
            AnalysisRequeueRequest.model_validate(bad)

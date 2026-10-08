"""Precision per match tier and a recall estimate from hand labels."""

from __future__ import annotations

import pytest

from collector.spotify_gold import evaluate

RECORDS = [
    {"kind": "population", "isrc": 900, "isrc_neighbour": 40, "metadata": 60, "no_payload": 0, "not_found": 100},
    *({"kind": "match", "tier": "isrc", "track_id": f"i{n}"} for n in range(10)),
    *({"kind": "match", "tier": "metadata", "track_id": f"m{n}"} for n in range(4)),
    *({"kind": "not_found", "track_id": f"x{n}"} for n in range(5)),
]


def test_precision_per_tier_and_recall_estimate() -> None:
    # True = correct match / truly absent from Spotify; read_labels() turns y/n into these.
    labels = {f"i{n}": True for n in range(10)}
    labels |= {"m0": True, "m1": True, "m2": True, "m3": False}
    labels |= {"x0": True, "x1": True, "x2": True, "x3": True, "x4": False}  # False = it was on Spotify

    result = evaluate(RECORDS, labels)

    assert result["tiers"]["isrc"] == {"labelled": 10, "correct": 10, "precision": 1.0, "population": 900}
    assert result["tiers"]["metadata"]["precision"] == 0.75
    assert result["tiers"]["isrc_neighbour"]["precision"] is None  # nothing labelled
    assert result["missed_estimate"] == pytest.approx(20.0)  # 1 in 5 of 100 not-found
    # correct matches: 900·1.0 + 60·0.75 = 945 (unlabelled tier left out); recall = 945 / (945 + 20)
    assert result["recall_estimate"] == pytest.approx(945 / 965)


def test_no_labels_gives_no_estimates() -> None:
    result = evaluate(RECORDS, {})
    assert result["recall_estimate"] is None and result["missed_estimate"] is None

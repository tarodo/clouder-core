"""Offline evaluation of the YT Music fuzzy matcher."""

from __future__ import annotations

from dataclasses import replace

from collector.providers.base import VendorTrackRef
from collector.vendor_match.evaluate import (
    GoldItem,
    best_threshold,
    drifted,
    load_gold,
    read_labels,
    render_report,
    sweep,
    top_score,
)


def _ref(vid: str, title: str, artists: tuple[str, ...] = ("Artist A",),
         duration_ms: int | None = 300_000) -> VendorTrackRef:
    return VendorTrackRef(vendor="ytmusic", vendor_track_id=vid, isrc=None,
                          artist_names=artists, title=title, duration_ms=duration_ms,
                          album_name=None, raw_payload={})


def _item(track_id: str, candidates, source: str = "review_accept") -> GoldItem:
    return GoldItem(track_id=track_id, artist="Artist A", title="Night Drive",
                    duration_ms=300_000, album=None, candidates=tuple(candidates),
                    source=source)


def _raw(vid: str | None, title: str, artist: str = "Artist A") -> dict:
    raw = {"title": title, "artists": [{"name": artist}], "duration_seconds": 300}
    if vid is not None:
        raw["videoId"] = vid
    return raw


def test_top_score_reports_best_candidate_and_its_label() -> None:
    item = _item("t1", [(_ref("bad", "Something Else", ("Other",)), False),
                        (_ref("good", "Night Drive"), True)])

    score, is_match = top_score(item)

    assert score > 0.9 and is_match is True


def test_top_score_is_none_without_candidates() -> None:
    assert top_score(_item("t0", [])) is None


def test_sweep_counts_accepts_mistakes_and_review() -> None:
    exact_right = _item("a", [(_ref("a1", "Night Drive"), True)])
    exact_wrong = _item("b", [(_ref("b1", "Night Drive"), False)])
    weak_right = _item("c", [(_ref("c1", "Night Drive (Club Edit)"), True)])
    no_candidates = _item("d", [])
    weak = top_score(weak_right)[0]
    high = top_score(exact_right)[0]
    assert weak < high

    below_weak, above_weak = sweep(
        [exact_right, exact_wrong, weak_right, no_candidates],
        thresholds=(round(weak - 0.01, 3), round(weak + 0.01, 3)),
    )

    assert (below_weak.auto_accepted, below_weak.auto_correct, below_weak.auto_wrong,
            below_weak.review) == (3, 2, 1, 1)
    assert (above_weak.auto_accepted, above_weak.auto_wrong, above_weak.review) == (2, 1, 2)
    assert above_weak.precision == 0.5
    assert above_weak.cost == 1 * 10.0 + 2 * 1.0


def test_best_threshold_takes_lowest_cost_then_higher_threshold() -> None:
    right = _item("a", [(_ref("a1", "Night Drive"), True)])
    results = sweep([right], thresholds=(0.5, 0.6))

    assert best_threshold(results).threshold == 0.6  # same cost, safer threshold wins


def test_load_gold_labels_candidates_by_chosen_id() -> None:
    record = {"kind": "review_accept", "track_id": "t1", "artist": "Artist A",
              "title": "Night Drive", "duration_ms": 300_000, "album": None,
              "chosen_id": "v2", "candidates": [_raw("v1", "Night"), _raw("v2", "Night Drive")]}

    (item,) = load_gold([record])

    assert item.source == "review_accept"
    assert [(ref.vendor_track_id, ok) for ref, ok in item.candidates] == [("v1", False), ("v2", True)]


def test_load_gold_marks_pasted_url_as_manual() -> None:
    record = {"kind": "review_accept", "track_id": "t1", "artist": "Artist A",
              "title": "Night Drive", "duration_ms": None, "album": None,
              "chosen_id": "pasted", "candidates": [_raw("v1", "Night Drive")]}

    (item,) = load_gold([record])
    (result,) = sweep([item], thresholds=(0.0,))

    assert item.source == "review_manual_url"
    assert result.auto_correct == 0 and result.auto_wrong == 1


def test_load_gold_skips_candidates_without_video_id() -> None:
    record = {"kind": "review_accept", "track_id": "t1", "artist": "Artist A",
              "title": "Night Drive", "duration_ms": None, "album": None,
              "chosen_id": "v2", "candidates": [_raw(None, "Night Drive"), _raw("v2", "Night Drive")]}

    (item,) = load_gold([record])

    assert [ref.vendor_track_id for ref, _ in item.candidates] == ["v2"]


def test_load_gold_keeps_only_labelled_auto_samples() -> None:
    sample = {"kind": "auto_sample", "artist": "Artist A", "title": "Night Drive",
              "duration_ms": 300_000, "album": None, "confidence": 0.97}
    records = [
        {**sample, "track_id": "s1", "candidate": _raw("y1", "Night Drive")},
        {**sample, "track_id": "s2", "candidate": _raw("y2", "Night Drive")},
        {"kind": "duplicate_artists", "name_groups": 3},
    ]

    items = load_gold(records, labels={"s1": False})

    assert [(i.track_id, i.source, i.candidates[0][1]) for i in items] == [("s1", "auto_sample", False)]


def test_read_labels_accepts_y_n_and_skips_blank() -> None:
    lines = ["track_id,query,candidate,url,label", "s1,q,c,u,y", "s2,q,c,u,N", "s3,q,c,u,"]

    assert read_labels(lines) == {"s1": True, "s2": False}


def test_report_states_current_and_best_threshold_and_duplicates() -> None:
    items = [_item("a", [(_ref("a1", "Night Drive"), True)]),
             _item("s", [(_ref("s1", "Night Drive"), True)], source="auto_sample")]
    results = sweep(items)

    report = render_report(items, results, current=0.92, fp_cost=10.0, review_cost=1.0,
                           duplicates={"name_groups": 4, "artists_in_groups": 9,
                                       "groups_with_non_beatport_artist": 1})

    assert "| 0.92 |" in report
    assert "Lowest-cost threshold" in report
    assert "4 name groups (9 artists)" in report


def test_report_flags_unmeasured_precision_without_labels() -> None:
    items = [_item("a", [(_ref("a1", "Night Drive"), True)])]

    report = render_report(items, sweep(items), current=0.92, fp_cost=10.0, review_cost=1.0)

    assert "not measured" in report


def test_report_handles_empty_gold_set() -> None:
    report = render_report([], sweep([]), current=0.92, fp_cost=10.0, review_cost=1.0)

    assert "Gold items: 0" in report


# ── final-review fixes ────────────────────────────────────────────────


def test_load_gold_carries_production_score() -> None:
    record = {"kind": "review_accept", "track_id": "t1", "artist": "Artist A",
              "title": "Night Drive", "duration_ms": 300_000, "album": None,
              "chosen_id": "v1", "stored_top_score": 0.95,
              "candidates": [_raw("v1", "Night Drive")]}

    (item,) = load_gold([record])

    assert item.stored_score == 0.95


def test_rescoring_drift_is_detected() -> None:
    item = _item("a", [(_ref("a1", "Night Drive"), True)])
    top = top_score(item)[0]

    assert not drifted(replace(item, stored_score=top))
    assert drifted(replace(item, stored_score=round(top - 0.05, 3)))
    assert not drifted(item)  # no production score to compare against


def test_report_lists_items_that_rescore_differently() -> None:
    items = [_item("a", [(_ref("a1", "Night Drive"), True)])]

    report = render_report(items, sweep(items), current=0.92, fp_cost=10.0,
                           review_cost=1.0, drifted_items=2)

    assert "2 items re-score differently" in report


def test_auto_samples_stand_for_their_population() -> None:
    sample = {"kind": "auto_sample", "artist": "Artist A", "title": "Night Drive",
              "duration_ms": 300_000, "album": None, "confidence": 0.95}
    records = [
        {**sample, "track_id": "s1", "candidate": _raw("y1", "Night Drive")},
        {**sample, "track_id": "s2", "candidate": _raw("y2", "Night Drive")},
        {"kind": "auto_population", "fuzzy": 10},
    ]

    items = load_gold(records, labels={"s1": True, "s2": False})
    (result,) = sweep(items, thresholds=(0.5,))

    assert [i.weight for i in items] == [5.0, 5.0]
    assert (result.auto_accepted, result.auto_correct, result.auto_wrong) == (10.0, 5.0, 5.0)


def test_best_threshold_can_be_capped() -> None:
    weak_wrong = _item("w", [(_ref("w1", "Night Drive (Club Edit)"), False)])
    results = sweep([weak_wrong], thresholds=(0.70, 0.92, 1.0))

    assert best_threshold(results).threshold == 1.0
    assert best_threshold(results, max_threshold=0.92).threshold == 0.92


def test_report_without_labels_never_recommends_above_current() -> None:
    items = [_item("w", [(_ref("w1", "Night Drive (Club Edit)"), False)])]

    report = render_report(items, sweep(items), current=0.92, fp_cost=10.0, review_cost=1.0)

    assert "Lowest-cost threshold 0.92" in report


def test_report_states_precision_of_newly_accepted_band() -> None:
    items = [_item("c1", [(_ref("c1", "Night Drive (Club Edit)"), True)]),
             _item("c2", [(_ref("c2", "Night Drive (Club Edit)"), True)])]

    report = render_report(items, sweep(items), current=0.92, fp_cost=10.0, review_cost=1.0)

    assert "Newly auto-accepted below 0.92: 2 items, precision 100.0%" in report


def test_read_labels_handles_bom_and_semicolons() -> None:
    lines = ["﻿track_id;query;candidate;url;label", "s1;q;c;u;y", "s2;q;c;u;n"]

    assert read_labels(lines) == {"s1": True, "s2": False}

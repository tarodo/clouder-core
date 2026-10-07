"""Offline evaluation of the YT Music fuzzy matcher against human decisions.

Gold items come from the review queue (a person accepted one of the scored
candidates, or pasted a URL outside them) and, optionally, from a hand-labelled
sample of auto-accepted matches. Every item is re-scored with the production
scorer, so a threshold — or a scorer change — is judged on what people chose.
Not used by any Lambda; scripts/eval_vendor_match.py drives it.
"""

from __future__ import annotations

import csv
from collections import Counter
from dataclasses import dataclass, replace
from typing import Any, Iterable, Mapping, Sequence

from ..providers.base import VendorTrackRef
from ..providers.ytmusic.normalize import result_to_ref
from .scorer import score_candidate

THRESHOLDS: tuple[float, ...] = tuple(round(0.70 + 0.01 * i, 2) for i in range(31))
DRIFT_TOLERANCE = 0.0005  # scorer totals are rounded to 3 decimals

_YES = {"y", "yes", "1", "true"}
_NO = {"n", "no", "0", "false"}


@dataclass(frozen=True)
class GoldItem:
    track_id: str
    artist: str
    title: str
    duration_ms: int | None
    album: str | None
    candidates: tuple[tuple[VendorTrackRef, bool], ...]  # (candidate, is the right match)
    source: str  # review_accept | review_manual_url | auto_sample
    stored_score: float | None = None  # what production scored at match time
    weight: float = 1.0  # how many real matches this item stands for


@dataclass(frozen=True)
class ThresholdResult:
    threshold: float
    items: float  # weighted: a labelled auto sample stands for its share of the population
    auto_accepted: float
    auto_correct: float
    auto_wrong: float
    review: float
    precision: float | None
    cost: float


def top_score(item: GoldItem) -> tuple[float, bool] | None:
    """Score and label of the candidate production would pick (first of equal best)."""
    best: tuple[float, bool] | None = None
    for ref, is_match in item.candidates:
        total = score_candidate(
            candidate=ref, artist=item.artist, title=item.title,
            duration_ms=item.duration_ms, album=item.album,
        ).total
        if best is None or total > best[0]:
            best = (total, is_match)
    return best


def drifted(item: GoldItem, tolerance: float = DRIFT_TOLERANCE) -> bool:
    """True when re-scoring today's metadata no longer reproduces production's score."""
    if item.stored_score is None:
        return False
    top = top_score(item)
    return top is None or abs(top[0] - item.stored_score) > tolerance


def sweep(
    items: Sequence[GoldItem],
    thresholds: Sequence[float] = THRESHOLDS,
    *,
    fp_cost: float = 10.0,
    review_cost: float = 1.0,
) -> list[ThresholdResult]:
    scored = [(top_score(item), item.weight) for item in items]
    total = sum(weight for _, weight in scored)
    results: list[ThresholdResult] = []
    for threshold in thresholds:
        accepted = [(top[1], w) for top, w in scored if top is not None and top[0] >= threshold]
        accepted_w = sum(w for _, w in accepted)
        correct = sum(w for ok, w in accepted if ok)
        wrong = accepted_w - correct
        review = total - accepted_w
        results.append(
            ThresholdResult(
                threshold=threshold,
                items=total,
                auto_accepted=accepted_w,
                auto_correct=correct,
                auto_wrong=wrong,
                review=review,
                precision=correct / accepted_w if accepted_w else None,
                cost=wrong * fp_cost + review * review_cost,
            )
        )
    return results


def best_threshold(
    results: Sequence[ThresholdResult], max_threshold: float | None = None
) -> ThresholdResult:
    """Lowest expected cost; ties go to the higher (safer) threshold.

    `max_threshold` caps the search when nothing above it was measured (no
    hand-labelled auto matches): raising the threshold would move unseen matches
    into review, which the gold set cannot price.
    """
    eligible = [r for r in results if max_threshold is None or r.threshold <= max_threshold + 1e-9]
    return min(eligible or results, key=lambda r: (r.cost, -r.threshold))


def load_gold(
    records: Iterable[Mapping[str, Any]], labels: Mapping[str, bool] | None = None
) -> list[GoldItem]:
    labels = labels or {}
    records_list = list(records)
    items: list[GoldItem] = []
    for rec in records_list:
        kind = rec.get("kind")
        if kind == "review_accept":
            refs = [ref for ref in map(result_to_ref, rec.get("candidates") or []) if ref]
            chosen = rec.get("chosen_id")
            candidates = tuple((ref, ref.vendor_track_id == chosen) for ref in refs)
            source = "review_accept" if any(ok for _, ok in candidates) else "review_manual_url"
            stored = rec.get("stored_top_score")
        elif kind == "auto_sample" and rec.get("track_id") in labels:
            ref = result_to_ref(rec.get("candidate") or {})
            if ref is None:
                continue
            candidates = ((ref, labels[rec["track_id"]]),)
            source = "auto_sample"
            stored = rec.get("confidence")
        else:
            continue
        items.append(
            GoldItem(
                track_id=str(rec["track_id"]),
                artist=rec.get("artist") or "",
                title=rec.get("title") or "",
                duration_ms=rec.get("duration_ms"),
                album=rec.get("album"),
                candidates=candidates,
                source=source,
                stored_score=float(stored) if stored is not None else None,
            )
        )
    population = next(
        (int(r["fuzzy"]) for r in records_list if r.get("kind") == "auto_population"), None
    )
    labelled = sum(1 for item in items if item.source == "auto_sample")
    if population and labelled:
        share = population / labelled
        items = [replace(i, weight=share) if i.source == "auto_sample" else i for i in items]
    return items


def read_labels(lines: Iterable[str]) -> dict[str, bool]:
    """`track_id,…,label` CSV; label y/n, blank rows are unlabelled.

    Spreadsheet re-saves are tolerated: a UTF-8 BOM and `;` or tab delimiters
    (Excel in many locales) parse the same as the exported `,` file.
    """
    rows = list(lines)
    if rows:
        rows[0] = rows[0].lstrip("\ufeff")
    delimiter = max(",;\t", key=lambda d: rows[0].count(d)) if rows else ","
    out: dict[str, bool] = {}
    for row in csv.DictReader(rows, delimiter=delimiter):
        label = (row.get("label") or "").strip().lower()
        if label in _YES:
            out[row["track_id"]] = True
        elif label in _NO:
            out[row["track_id"]] = False
    return out


def _fmt_precision(value: float | None) -> str:
    return "—" if value is None else f"{value:.1%}"


def _n(value: float) -> str:
    return f"{round(value, 1):g}"


def _row(r: ThresholdResult, mark: str) -> str:
    return (
        f"| {r.threshold:.2f} | {_n(r.auto_accepted)} | {_n(r.auto_correct)} | {_n(r.auto_wrong)} "
        f"| {_fmt_precision(r.precision)} | {_n(r.review)} | {_n(r.cost)} |{mark}"
    )


def render_report(
    items: Sequence[GoldItem],
    results: Sequence[ThresholdResult],
    *,
    current: float,
    fp_cost: float,
    review_cost: float,
    duplicates: Mapping[str, Any] | None = None,
    drifted_items: int = 0,
) -> str:
    by_source = Counter(item.source for item in items)
    current_row = min(results, key=lambda r: abs(r.threshold - current))
    measured_above = by_source["auto_sample"] > 0
    best = best_threshold(results, max_threshold=None if measured_above else current)
    lines = [
        "# YT Music matcher evaluation",
        "",
        f"Gold items: {len(items)} — review accepts with the right answer among the candidates: "
        f"{by_source['review_accept']}; accepted from a pasted URL (right answer not among the "
        f"candidates): {by_source['review_manual_url']}; hand-labelled auto matches: "
        f"{by_source['auto_sample']}.",
        f"Cost model: wrong auto-match = {fp_cost:g}, item sent to review = {review_cost:g}. "
        "Each hand-labelled auto match is weighted by its share of all automatic matches.",
        "",
        "| threshold | auto-accepted | correct | wrong | precision | to review | cost |",
        "|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for r in results:
        if round(r.threshold * 100) % 2 == 0 or r is current_row or r is best:
            mark = " current" if r is current_row else ""
            mark += " lowest cost" if r is best else ""
            lines.append(_row(r, mark))
    lines += [
        "",
        f"Current threshold {current_row.threshold:.2f}: precision "
        f"{_fmt_precision(current_row.precision)}, {_n(current_row.review)} of "
        f"{_n(current_row.items)} to review.",
        f"Lowest-cost threshold {best.threshold:.2f}: precision {_fmt_precision(best.precision)}, "
        f"{_n(best.review)} of {_n(best.items)} to review.",
    ]
    if best.threshold < current_row.threshold:
        band = [
            top[1]
            for item in items
            if item.source != "auto_sample"
            for top in [top_score(item)]
            if top is not None and best.threshold <= top[0] < current_row.threshold
        ]
        if band:
            lines.append(
                f"Newly auto-accepted below {current_row.threshold:.2f}: {len(band)} items, "
                f"precision {sum(band) / len(band):.1%}."
            )
    if drifted_items:
        lines.append(
            f"{drifted_items} items re-score differently from production (track metadata changed "
            "since the match) and are left out of the table."
        )
    if not measured_above:
        lines.append(
            f"Precision of matches scoring at or above {current:.2f} is not measured: no "
            "hand-labelled auto matches were provided, so thresholds above it are not "
            "recommended."
        )
    if duplicates:
        lines.append(
            f"Duplicate artist names: {duplicates.get('name_groups', 0)} name groups "
            f"({duplicates.get('artists_in_groups', 0)} artists); "
            f"{duplicates.get('groups_with_non_beatport_artist', 0)} include an artist without "
            "a Beatport identity."
        )
    return "\n".join(lines) + "\n"

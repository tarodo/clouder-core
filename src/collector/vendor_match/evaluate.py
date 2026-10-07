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
from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Sequence

from ..providers.base import VendorTrackRef
from ..providers.ytmusic.normalize import result_to_ref
from .scorer import score_candidate

THRESHOLDS: tuple[float, ...] = tuple(round(0.70 + 0.01 * i, 2) for i in range(31))

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


@dataclass(frozen=True)
class ThresholdResult:
    threshold: float
    items: int
    auto_accepted: int
    auto_correct: int
    auto_wrong: int
    review: int
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


def sweep(
    items: Sequence[GoldItem],
    thresholds: Sequence[float] = THRESHOLDS,
    *,
    fp_cost: float = 10.0,
    review_cost: float = 1.0,
) -> list[ThresholdResult]:
    tops = [top_score(item) for item in items]
    results: list[ThresholdResult] = []
    for threshold in thresholds:
        accepted = [top[1] for top in tops if top is not None and top[0] >= threshold]
        correct = sum(accepted)
        wrong = len(accepted) - correct
        review = len(items) - len(accepted)
        results.append(
            ThresholdResult(
                threshold=threshold,
                items=len(items),
                auto_accepted=len(accepted),
                auto_correct=correct,
                auto_wrong=wrong,
                review=review,
                precision=correct / len(accepted) if accepted else None,
                cost=wrong * fp_cost + review * review_cost,
            )
        )
    return results


def best_threshold(results: Sequence[ThresholdResult]) -> ThresholdResult:
    """Lowest expected cost; ties go to the higher (safer) threshold."""
    return min(results, key=lambda r: (r.cost, -r.threshold))


def load_gold(
    records: Iterable[Mapping[str, Any]], labels: Mapping[str, bool] | None = None
) -> list[GoldItem]:
    labels = labels or {}
    items: list[GoldItem] = []
    for rec in records:
        kind = rec.get("kind")
        if kind == "review_accept":
            refs = [ref for ref in map(result_to_ref, rec.get("candidates") or []) if ref]
            chosen = rec.get("chosen_id")
            candidates = tuple((ref, ref.vendor_track_id == chosen) for ref in refs)
            source = "review_accept" if any(ok for _, ok in candidates) else "review_manual_url"
        elif kind == "auto_sample" and rec.get("track_id") in labels:
            ref = result_to_ref(rec.get("candidate") or {})
            if ref is None:
                continue
            candidates = ((ref, labels[rec["track_id"]]),)
            source = "auto_sample"
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
            )
        )
    return items


def read_labels(lines: Iterable[str]) -> dict[str, bool]:
    """`track_id,…,label` CSV; label y/n, blank rows are unlabelled."""
    out: dict[str, bool] = {}
    for row in csv.DictReader(lines):
        label = (row.get("label") or "").strip().lower()
        if label in _YES:
            out[row["track_id"]] = True
        elif label in _NO:
            out[row["track_id"]] = False
    return out


def _fmt_precision(value: float | None) -> str:
    return "—" if value is None else f"{value:.1%}"


def _row(r: ThresholdResult, mark: str) -> str:
    return (
        f"| {r.threshold:.2f} | {r.auto_accepted} | {r.auto_correct} | {r.auto_wrong} "
        f"| {_fmt_precision(r.precision)} | {r.review} | {r.cost:g} |{mark}"
    )


def render_report(
    items: Sequence[GoldItem],
    results: Sequence[ThresholdResult],
    *,
    current: float,
    fp_cost: float,
    review_cost: float,
    duplicates: Mapping[str, Any] | None = None,
) -> str:
    by_source = Counter(item.source for item in items)
    current_row = min(results, key=lambda r: abs(r.threshold - current))
    best = best_threshold(results)
    lines = [
        "# YT Music matcher evaluation",
        "",
        f"Gold items: {len(items)} — review accepts with the right answer among the candidates: "
        f"{by_source['review_accept']}; accepted from a pasted URL (right answer not among the "
        f"candidates): {by_source['review_manual_url']}; hand-labelled auto matches: "
        f"{by_source['auto_sample']}.",
        f"Cost model: wrong auto-match = {fp_cost:g}, item sent to review = {review_cost:g}.",
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
        f"{_fmt_precision(current_row.precision)}, {current_row.review} of {current_row.items} "
        f"to review.",
        f"Lowest-cost threshold {best.threshold:.2f}: precision {_fmt_precision(best.precision)}, "
        f"{best.review} of {best.items} to review.",
    ]
    if not by_source["auto_sample"]:
        lines.append(
            f"Precision of matches scoring at or above {current:.2f} is not measured: no "
            "hand-labelled auto matches were provided, and review items all scored below it."
        )
    if duplicates:
        lines.append(
            f"Duplicate artist names: {duplicates.get('name_groups', 0)} name groups "
            f"({duplicates.get('artists_in_groups', 0)} artists); "
            f"{duplicates.get('groups_with_non_beatport_artist', 0)} include an artist without "
            "a Beatport identity."
        )
    return "\n".join(lines) + "\n"

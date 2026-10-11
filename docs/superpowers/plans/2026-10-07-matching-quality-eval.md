# Matching Quality Evaluation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Measure how accurate the YouTube Music fuzzy matcher really is, using the decisions people already made in the review queue, and turn the hand-picked 0.92 threshold into a data-backed one.

**Architecture:** A pure evaluator (`collector.vendor_match.evaluate`) re-scores gold items with the production scorer and sweeps thresholds (auto-accept precision, review load, cost). A read-only extractor (`collector.vendor_match.gold`) builds the gold set from `match_review_queue` accepts, a deterministic sample of auto-accepted fuzzy matches and a duplicate-artist summary; the owner runs it against production with `scripts/export_match_gold.py` (agent prod-DB reads are blocked). `scripts/eval_vendor_match.py` prints a markdown report that feeds `docs/data/entity-resolution.md`.

**Tech Stack:** Python 3.12, RDS Data API (`collector.data_api.DataAPIClient`), PostgreSQL 16 (tests via `tests/db/` psycopg stand-in), pytest.

**Spec:** inline — "Spec" section below (source: hiring audit §15.3 "B").

## Global Constraints

- Runtime code under `src/collector` never imports psycopg (ADR-0001); the new modules are pure Python + Data API.
- Data API cannot bind arrays; no list parameters are needed here.
- Only YouTube Music has fuzzy matching and a review queue; Spotify uses ISRC + metadata fallback without human labels — out of scope for measured precision.
- Export output (`match_gold_*`) contains catalog rows: git-ignored, never committed.
- No money figures in docs.
- Branch `feat/matching-quality-eval` from `origin/main`; commits and PR text via `caveman:caveman-commit`, no AI attribution; `.venv` at the main repo root (`$VENV`).

## Spec

**Problem.** Matching coverage is known (Spotify 96.9 %; YouTube Music 568 matches = 472 automatic fuzzy + 96 manual), but correctness is not. The fuzzy score `0.5·title_sim + 0.4·artist_sim + 0.05·duration_ok + 0.05·album_match` auto-accepts at a hand-picked 0.92; everything below goes to a human review queue (99 items so far: 93 resolved, 3 pending, 3 rejected). Nobody knows the precision of auto-accepted matches or how much review work a different threshold would save.

**Ground truth already exists.** For every resolved queue item the database keeps the scored top-5 candidates (`match_review_queue.candidates[].ref` = raw YT search result) and the human's choice (`vendor_track_map.match_type='manual'`). The chosen candidate is a positive, the other candidates are negatives; if the person pasted a URL outside the list, all candidates are negatives. Rejected items lose their candidates (`resolve_review_reject` deletes the row), so they cannot be used. Auto-accepted matches have no labels; a deterministic sample is exported for optional hand labelling.

**Goals.**
1. Offline evaluator: per threshold — auto-accepted, correct, wrong, precision, sent to review, cost (`wrong × fp_cost + review × review_cost`, defaults 10 and 1); lowest-cost threshold, ties to the higher threshold.
2. Read-only gold-set export the owner runs in one command (prod or any Postgres), plus a labels CSV for the auto-accepted sample.
3. Duplicate-artist measurement before any merge work: name-collision groups and how many involve an artist without a Beatport identity.
4. `docs/data/entity-resolution.md` in the before/after format: Why, Before, What changed, After (from the owner's export), What it buys.

**Non-goals.** Changing the threshold or scorer before the data supports it; artist merge tooling (decided after the duplicate numbers); Spotify precision (no labels); any write to production.

**Success criteria.** Evaluator and extractor tested (unit + real Postgres); export runs read-only in one command; docs carry the "before" facts and the method; after the owner's export, the report states measured precision and the review-load change at the chosen threshold.

## Review Focus

1. **A track resolved more than once** (several `resolved` rows) → exported once, from the latest resolution. Test: `test_review_accepts_keeps_latest_resolution_per_track` (Task 2).
2. **Accept from a pasted URL** (chosen id not among candidates) → the item never counts as a correct auto-accept. Test: `test_load_gold_marks_pasted_url_as_manual` (Task 1).
3. **Unplayable candidates** (no `videoId`) → skipped, no crash. Test: `test_load_gold_skips_candidates_without_video_id` (Task 1).
4. **No hand labels at all** → the report says precision above the current threshold is unmeasured. Test: `test_report_flags_unmeasured_precision_without_labels` (Task 1).
5. **Empty gold set** → report renders zeros, no division by zero. Test: `test_report_handles_empty_gold_set` (Task 1).

---

### Task 0: Branch and database

- [ ] **Step 1: Worktree from `origin/main`, plan copied, Postgres migrated**

```bash
cd <repo>
git fetch origin
git worktree add -b feat/matching-quality-eval ../clouder-core-er origin/main
cp docs/superpowers/plans/2026-10-07-matching-quality-eval.md ../clouder-core-er/docs/superpowers/plans/
cd ../clouder-core-er
export VENV=<repo>/.venv/bin
docker run -d --rm --name er-pg -p 55433:5432 -e POSTGRES_PASSWORD=postgres postgres:16   # skip if already running
PYTHONPATH=src ALEMBIC_DATABASE_URL=postgresql+psycopg://postgres:postgres@localhost:55433/postgres $VENV/alembic upgrade head
export TEST_DATABASE_URL=postgresql://postgres:postgres@localhost:55433/postgres
```

- [ ] **Step 2: Commit the plan** — `docs(plans): matching quality evaluation plan`

---

### Task 1: Evaluator

**Files:**
- Create: `src/collector/vendor_match/evaluate.py`
- Test: `tests/unit/test_vendor_match_evaluate.py`

**Interfaces:**
- Consumes: `collector.vendor_match.scorer.score_candidate(*, candidate, artist, title, duration_ms, album) -> FuzzyScore`; `collector.providers.ytmusic.normalize.result_to_ref(raw) -> VendorTrackRef | None`.
- Produces: `GoldItem`, `ThresholdResult`, `THRESHOLDS`, `top_score(item) -> tuple[float, bool] | None`, `sweep(items, thresholds=THRESHOLDS, *, fp_cost=10.0, review_cost=1.0) -> list[ThresholdResult]`, `best_threshold(results) -> ThresholdResult`, `load_gold(records, labels=None) -> list[GoldItem]`, `read_labels(lines) -> dict[str, bool]`, `render_report(items, results, *, current, fp_cost, review_cost, duplicates=None) -> str`.

- [ ] **Step 1: Write the failing tests**

`tests/unit/test_vendor_match_evaluate.py`:

```python
"""Offline evaluation of the YT Music fuzzy matcher."""

from __future__ import annotations

from collector.providers.base import VendorTrackRef
from collector.vendor_match.evaluate import (
    GoldItem,
    best_threshold,
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
```

- [ ] **Step 2: Run to verify RED**

Run: `PYTHONPATH=src $VENV/python -m pytest tests/unit/test_vendor_match_evaluate.py -q`
Expected: collection error `ModuleNotFoundError: No module named 'collector.vendor_match.evaluate'`.

- [ ] **Step 3: Implement**

`src/collector/vendor_match/evaluate.py`:

```python
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
```

- [ ] **Step 4: Run to verify GREEN**

Run: `PYTHONPATH=src $VENV/python -m pytest tests/unit/test_vendor_match_evaluate.py -q`
Expected: all pass.

- [ ] **Step 5: Commit** — `feat(vendor-match): offline matcher evaluator`

---

### Task 2: Gold-set extraction and export script

**Files:**
- Create: `src/collector/vendor_match/gold.py`
- Create: `scripts/export_match_gold.py`
- Create: `tests/db/test_vendor_match_gold_pg.py`
- Modify: `.gitignore` (append `match_gold_*`)

**Interfaces:**
- Consumes: a Data API–compatible client (`execute(sql, params=None, transaction_id=None) -> list[dict]`).
- Produces: `review_accepts(client) -> list[dict]` (records `kind="review_accept"`, keys `track_id, artist, title, duration_ms, album, chosen_id, candidates`), `auto_sample(client, n) -> list[dict]` (`kind="auto_sample"`, keys `track_id, artist, title, duration_ms, album, confidence, candidate`), `duplicate_artists(client) -> dict` (`kind="duplicate_artists"`, `name_groups, artists_in_groups, groups_with_non_beatport_artist`).

- [ ] **Step 1: Write the failing real-Postgres tests**

`tests/db/test_vendor_match_gold_pg.py`:

```python
"""Gold-set extraction against a real Postgres."""

from __future__ import annotations

import json

from collector.vendor_match.gold import auto_sample, duplicate_artists, review_accepts


def _seed(pg) -> None:
    for sql in (
        "INSERT INTO clouder_albums (id, title, normalized_title, created_at, updated_at) "
        "VALUES ('al1', 'Album One', 'album one', now(), now())",
        "INSERT INTO clouder_tracks (id, title, normalized_title, length_ms, album_id, created_at, updated_at) "
        "VALUES ('t1', 'Night Drive', 'night drive', 300000, 'al1', now(), now()), "
        "('t2', 'Day Ride', 'day ride', NULL, NULL, now(), now())",
        "INSERT INTO clouder_artists (id, name, normalized_name, created_at, updated_at) "
        "VALUES ('ar1', 'Zeta', 'zeta', now(), now()), ('ar2', 'Alpha', 'alpha', now(), now()), "
        "('ar3', 'Alpha', 'alpha', now(), now())",
        "INSERT INTO clouder_track_artists (track_id, artist_id) "
        "VALUES ('t1', 'ar1'), ('t1', 'ar2'), ('t2', 'ar1')",
        "INSERT INTO identity_map (source, entity_type, external_id, clouder_entity_type, clouder_id, "
        "match_type, confidence, first_seen_at, last_seen_at) "
        "VALUES ('beatport', 'artist', '1', 'artist', 'ar1', 'auto_create', 0.6, now(), now()), "
        "('beatport', 'artist', '2', 'artist', 'ar2', 'auto_create', 0.6, now(), now())",
    ):
        pg.execute(sql)
    candidates = json.dumps([{"ref": {"videoId": "v1", "title": "Night"}, "score": 0.7},
                             {"ref": {"videoId": "v2", "title": "Night Drive"}, "score": 0.9}])
    for qid, resolved_at, cands in (("q-old", "2026-01-01", "[]"), ("q-new", "2026-02-01", candidates)):
        pg.execute(
            "INSERT INTO match_review_queue (id, clouder_track_id, vendor, candidates, status, created_at, resolved_at) "
            "VALUES (:id, 't1', 'ytmusic', CAST(:c AS jsonb), 'resolved', now(), CAST(:r AS timestamptz))",
            {"id": qid, "c": cands, "r": resolved_at},
        )
    pg.execute(
        "INSERT INTO match_review_queue (id, clouder_track_id, vendor, candidates, status, created_at) "
        "VALUES ('q-pending', 't2', 'ytmusic', '[]'::jsonb, 'pending', now())"
    )
    pg.execute(
        """
        INSERT INTO vendor_track_map (clouder_track_id, vendor, vendor_track_id, match_type, confidence, matched_at, payload)
        VALUES ('t1', 'ytmusic', 'v2', 'manual', 1.0, now(), '{"videoId": "v2"}'::jsonb),
               ('t2', 'ytmusic', 'y9', 'fuzzy', 0.973, now(), '{"videoId": "y9", "title": "Day Ride"}'::jsonb)
        """
    )


def test_review_accepts_keeps_latest_resolution_per_track(pg) -> None:
    _seed(pg)

    (record,) = review_accepts(pg)

    assert record["kind"] == "review_accept"
    assert record["track_id"] == "t1"
    assert record["chosen_id"] == "v2"
    assert [c["videoId"] for c in record["candidates"]] == ["v1", "v2"]
    assert (record["artist"], record["title"], record["duration_ms"], record["album"]) == (
        "Alpha, Zeta", "Night Drive", 300000, "Album One")


def test_auto_sample_returns_fuzzy_matches_with_query_fields(pg) -> None:
    _seed(pg)

    (record,) = auto_sample(pg, 10)

    assert record["kind"] == "auto_sample"
    assert (record["track_id"], record["candidate"]["videoId"], record["confidence"]) == ("t2", "y9", 0.973)
    assert (record["artist"], record["duration_ms"], record["album"]) == ("Zeta", None, None)


def test_duplicate_artists_counts_name_groups(pg) -> None:
    _seed(pg)

    summary = duplicate_artists(pg)

    assert summary == {"kind": "duplicate_artists", "name_groups": 1,
                       "artists_in_groups": 2, "groups_with_non_beatport_artist": 1}
```

- [ ] **Step 2: Run to verify RED**

Run: `TEST_DATABASE_URL=$TEST_DATABASE_URL PYTHONPATH=src $VENV/python -m pytest tests/db/test_vendor_match_gold_pg.py -q`
Expected: collection error `No module named 'collector.vendor_match.gold'`.

- [ ] **Step 3: Implement the extractor**

`src/collector/vendor_match/gold.py`:

```python
"""Read-only extraction of the YT Music matching gold set (offline evaluation).

The owner runs these queries against production through
scripts/export_match_gold.py; no Lambda calls this module. `artist` is built
exactly like the vendor-match input (STRING_AGG of distinct names, ordered), so
re-scoring reproduces what the worker saw.
"""

from __future__ import annotations

import json
from typing import Any, Mapping


def _json(value: Any) -> Any:
    return json.loads(value) if isinstance(value, str) else value


def _query_fields(row: Mapping[str, Any]) -> dict[str, Any]:
    length = row.get("length_ms")
    return {
        "artist": row.get("artist_names") or "",
        "title": row.get("title") or "",
        "duration_ms": int(length) if length is not None else None,
        "album": row.get("album_title"),
    }


def review_accepts(client: Any) -> list[dict[str, Any]]:
    """Resolved review items with their scored candidates and the human's choice."""
    rows = client.execute(
        """
        SELECT DISTINCT ON (q.clouder_track_id)
               q.clouder_track_id AS track_id,
               q.candidates,
               m.vendor_track_id AS chosen_id,
               t.title,
               t.length_ms,
               alb.title AS album_title,
               (SELECT COALESCE(STRING_AGG(DISTINCT a.name, ', ' ORDER BY a.name), '')
                  FROM clouder_track_artists cta
                  JOIN clouder_artists a ON a.id = cta.artist_id
                 WHERE cta.track_id = t.id) AS artist_names
        FROM match_review_queue q
        JOIN vendor_track_map m
          ON m.clouder_track_id = q.clouder_track_id
         AND m.vendor = q.vendor
         AND m.match_type = 'manual'
        JOIN clouder_tracks t ON t.id = q.clouder_track_id
        LEFT JOIN clouder_albums alb ON alb.id = t.album_id
        WHERE q.vendor = 'ytmusic' AND q.status = 'resolved'
        ORDER BY q.clouder_track_id, q.resolved_at DESC NULLS LAST
        """
    )
    return [
        {
            "kind": "review_accept",
            "track_id": row["track_id"],
            **_query_fields(row),
            "chosen_id": row["chosen_id"],
            "candidates": [c.get("ref") or {} for c in _json(row["candidates"]) or []],
        }
        for row in rows
    ]


def auto_sample(client: Any, n: int) -> list[dict[str, Any]]:
    """A deterministic sample (md5 order) of auto-accepted fuzzy matches to label by hand."""
    rows = client.execute(
        """
        SELECT m.clouder_track_id AS track_id,
               m.payload,
               m.confidence,
               t.title,
               t.length_ms,
               alb.title AS album_title,
               (SELECT COALESCE(STRING_AGG(DISTINCT a.name, ', ' ORDER BY a.name), '')
                  FROM clouder_track_artists cta
                  JOIN clouder_artists a ON a.id = cta.artist_id
                 WHERE cta.track_id = t.id) AS artist_names
        FROM vendor_track_map m
        JOIN clouder_tracks t ON t.id = m.clouder_track_id
        LEFT JOIN clouder_albums alb ON alb.id = t.album_id
        WHERE m.vendor = 'ytmusic' AND m.match_type = 'fuzzy'
        ORDER BY md5(m.clouder_track_id)
        LIMIT :n
        """,
        {"n": n},
    )
    return [
        {
            "kind": "auto_sample",
            "track_id": row["track_id"],
            **_query_fields(row),
            "confidence": float(row["confidence"]),
            "candidate": _json(row["payload"]) or {},
        }
        for row in rows
    ]


def duplicate_artists(client: Any) -> dict[str, Any]:
    """Artists sharing a normalized name — measured before any merge tooling exists."""
    (row,) = client.execute(
        """
        WITH groups AS (
            SELECT a.normalized_name,
                   count(*) AS n,
                   count(*) FILTER (WHERE im.clouder_id IS NULL) AS without_beatport_identity
            FROM clouder_artists a
            LEFT JOIN identity_map im
              ON im.clouder_id = a.id
             AND im.source = 'beatport'
             AND im.entity_type = 'artist'
            GROUP BY a.normalized_name
            HAVING count(*) > 1
        )
        SELECT count(*) AS name_groups,
               COALESCE(sum(n), 0) AS artists_in_groups,
               count(*) FILTER (WHERE without_beatport_identity > 0) AS groups_with_non_beatport_artist
        FROM groups
        """
    )
    return {
        "kind": "duplicate_artists",
        "name_groups": int(row["name_groups"]),
        "artists_in_groups": int(row["artists_in_groups"]),
        "groups_with_non_beatport_artist": int(row["groups_with_non_beatport_artist"]),
    }
```

- [ ] **Step 4: Run to verify GREEN, plus the SQL grammar check**

Run: `TEST_DATABASE_URL=$TEST_DATABASE_URL PYTHONPATH=src $VENV/python -m pytest tests/db/test_vendor_match_gold_pg.py tests/unit/test_raw_sql_parses.py -q`
Expected: all pass.

- [ ] **Step 5: Write the export script**

`scripts/export_match_gold.py`:

```python
#!/usr/bin/env python3
"""Export the YT Music matching gold set (read-only) for scripts/eval_vendor_match.py.

  PYTHONPATH=src .venv/bin/python scripts/export_match_gold.py                 # prod, RDS Data API
  PYTHONPATH=src .venv/bin/python scripts/export_match_gold.py --database-url postgresql://...

Writes match_gold_<ts>.jsonl (review-queue accepts, a sample of auto-accepted fuzzy
matches, a duplicate-artist summary) and match_gold_<ts>_labels.csv — fill its `label`
column with y/n to measure precision above the current threshold. Both files hold
catalog rows and are git-ignored.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]

from collector.vendor_match.gold import auto_sample, duplicate_artists, review_accepts  # noqa: E402


def _client(database_url: str | None) -> Any:
    if database_url:
        sys.path.insert(0, str(ROOT / "tests" / "db"))
        from pg_data_api import PgDataAPIClient

        return PgDataAPIClient(database_url)
    import boto3

    from collector.data_api import create_default_data_api_client

    cluster = boto3.client("rds").describe_db_clusters(
        DBClusterIdentifier=os.environ.get("CLUSTER", "clouder-prod-aurora")
    )["DBClusters"][0]
    return create_default_data_api_client(
        resource_arn=cluster["DBClusterArn"],
        secret_arn=cluster["MasterUserSecret"]["SecretArn"],
        database=cluster["DatabaseName"],
    )


def main(argv: list[str] | None = None) -> tuple[Path, Path]:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--database-url", help="any Postgres instead of production")
    parser.add_argument("--sample", type=int, default=100, help="auto-accepted matches to sample")
    parser.add_argument("--out-dir", type=Path, default=Path("."))
    args = parser.parse_args(argv)

    client = _client(args.database_url)
    reviews = review_accepts(client)
    sample = auto_sample(client, args.sample)
    duplicates = duplicate_artists(client)

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M")
    gold = args.out_dir / f"match_gold_{stamp}.jsonl"
    with gold.open("w", encoding="utf-8") as f:
        for record in [*reviews, *sample, duplicates]:
            f.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")

    labels = args.out_dir / f"match_gold_{stamp}_labels.csv"
    with labels.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["track_id", "query", "candidate", "url", "label"])
        for record in sample:
            cand = record["candidate"]
            names = ", ".join(
                a.get("name", "") for a in cand.get("artists") or [] if isinstance(a, dict)
            )
            writer.writerow([
                record["track_id"],
                f"{record['artist']} — {record['title']}",
                f"{names} — {cand.get('title', '')}",
                f"https://music.youtube.com/watch?v={cand.get('videoId', '')}",
                "",
            ])

    print(
        f"{len(reviews)} review accepts, {len(sample)} auto-accepted matches -> {gold}\n"
        f"Optional: label the sample (y/n) in {labels}, then run\n"
        f"  PYTHONPATH=src .venv/bin/python scripts/eval_vendor_match.py {gold} --labels {labels}"
    )
    return gold, labels


if __name__ == "__main__":
    main()
```

Append to `.gitignore`:

```
# Matching gold-set exports (scripts/export_match_gold.py): catalog rows, never committed
match_gold_*
```

- [ ] **Step 6: Smoke-run the export against the test database**

Run (after seeding through the PG test once, or on the empty DB):
`PYTHONPATH=src $VENV/python scripts/export_match_gold.py --database-url $TEST_DATABASE_URL --out-dir <scratchpad>`
Expected: prints the counts line and two paths; both files exist.

- [ ] **Step 7: Full suite, commit** — `feat(vendor-match): export matching gold set`

---

### Task 3: Evaluation CLI and entity-resolution doc

**Files:**
- Create: `scripts/eval_vendor_match.py`
- Create: `tests/unit/test_eval_vendor_match_cli.py`
- Create: `docs/data/entity-resolution.md`
- Modify: `docs/data/README.md` (link)

**Interfaces:**
- Consumes: Task 1 API; gold JSONL format from Task 2.
- Produces: `scripts/eval_vendor_match.py GOLD [--labels CSV] [--fp-cost F] [--review-cost R] [--out FILE]`; `main(argv) -> str` (the report).

- [ ] **Step 1: Failing CLI test**

`tests/unit/test_eval_vendor_match_cli.py`:

```python
"""scripts/eval_vendor_match.py end to end on a tiny gold file."""

from __future__ import annotations

import json
import runpy
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "eval_vendor_match.py"


def test_cli_prints_report_and_writes_it(tmp_path, monkeypatch, capsys) -> None:
    gold = tmp_path / "match_gold_test.jsonl"
    records = [
        {"kind": "review_accept", "track_id": "t1", "artist": "Artist A", "title": "Night Drive",
         "duration_ms": 300000, "album": None, "chosen_id": "v1",
         "candidates": [{"videoId": "v1", "title": "Night Drive", "artists": [{"name": "Artist A"}],
                         "duration_seconds": 300}]},
        {"kind": "duplicate_artists", "name_groups": 2, "artists_in_groups": 5,
         "groups_with_non_beatport_artist": 0},
    ]
    gold.write_text("\n".join(json.dumps(r) for r in records) + "\n")
    out = tmp_path / "report.md"
    monkeypatch.setattr(sys, "argv", ["eval_vendor_match.py", str(gold), "--out", str(out)])

    runpy.run_path(str(SCRIPT), run_name="__main__")

    printed = capsys.readouterr().out
    assert "Gold items: 1" in printed
    assert "2 name groups (5 artists)" in printed
    assert out.read_text() == printed
```

- [ ] **Step 2: Run to verify RED**

Run: `PYTHONPATH=src $VENV/python -m pytest tests/unit/test_eval_vendor_match_cli.py -q`
Expected: FAIL — `FileNotFoundError` / no such file `scripts/eval_vendor_match.py`.

- [ ] **Step 3: Implement the CLI**

`scripts/eval_vendor_match.py`:

```python
#!/usr/bin/env python3
"""Score the YT Music fuzzy matcher against a gold set from scripts/export_match_gold.py.

  PYTHONPATH=src .venv/bin/python scripts/eval_vendor_match.py match_gold_<ts>.jsonl \
      [--labels match_gold_<ts>_labels.csv] [--fp-cost 10] [--review-cost 1] [--out report.md]
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from collector.settings import get_vendor_match_settings
from collector.vendor_match.evaluate import load_gold, read_labels, render_report, sweep


def main(argv: list[str] | None = None) -> str:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("gold", type=Path)
    parser.add_argument("--labels", type=Path)
    parser.add_argument("--fp-cost", type=float, default=10.0, help="cost of one wrong auto-match")
    parser.add_argument("--review-cost", type=float, default=1.0, help="cost of one manual review")
    parser.add_argument("--out", type=Path)
    args = parser.parse_args(argv)

    records = [json.loads(line) for line in args.gold.read_text(encoding="utf-8").splitlines() if line.strip()]
    labels = read_labels(args.labels.read_text(encoding="utf-8").splitlines()) if args.labels else {}
    items = load_gold(records, labels)
    results = sweep(items, fp_cost=args.fp_cost, review_cost=args.review_cost)
    duplicates = next((r for r in records if r.get("kind") == "duplicate_artists"), None)
    report = render_report(
        items, results,
        current=get_vendor_match_settings().fuzzy_match_threshold,
        fp_cost=args.fp_cost, review_cost=args.review_cost, duplicates=duplicates,
    )
    if args.out:
        args.out.write_text(report, encoding="utf-8")
    print(report, end="")
    return report


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run to verify GREEN**

Run: `PYTHONPATH=src $VENV/python -m pytest tests/unit/test_eval_vendor_match_cli.py -q`
Expected: PASS.

- [ ] **Step 5: Write the doc**

`docs/data/entity-resolution.md` — sections, in this order:

1. **Why.** Coverage is not correctness; the 0.92 threshold was picked by hand; every item below it costs a person a review.
2. **How matching works.** Beatport → canonical via `identity_map` (ADR-0022); Spotify by ISRC with a strict/relaxed metadata fallback (ADR-0006), no human review; YouTube Music: ISRC lookup first, else search (top results), each candidate scored `0.5·title + 0.4·artist + 0.05·duration within 3 s + 0.05·same album` (`src/collector/vendor_match/scorer.py`), auto-accept at ≥ 0.92, otherwise the top 5 go to the review queue where a person accepts one, pastes a URL, or rejects.
3. **Before (2026-10-06).** Table: Spotify 96.9 % matched (91,785 of 94,736 tracks); YouTube Music 568 matches — 472 automatic fuzzy (average confidence 0.994) and 96 manual; review queue 99 items (93 resolved, 3 pending, 3 rejected) — about 1 in 6 YouTube Music matches needed a person; precision of automatic matches: not measured; threshold: chosen by hand.
4. **Method.** Gold set from resolved review items (chosen candidate = positive, others = negative; pasted URL = all negative); optional hand labels for a deterministic sample of automatic matches; re-scoring with the production scorer; per-threshold auto-accept, precision, review load; cost = wrong auto-match × 10 + review × 1; bias: review items all scored below 0.92, so raising the threshold can only be judged with the hand-labelled sample.
5. **After.** "Pending the owner's export (`scripts/export_match_gold.py`); filled from `scripts/eval_vendor_match.py`."
6. **Duplicates.** Name collisions are not necessarily duplicates (Beatport keeps distinct artists with equal names — `test_same_name_different_beatport_ids_create_separate_entities`); the export measures name groups and those involving an artist without a Beatport identity (e.g. created by a Spotify playlist import, ADR-0021) before any merge tooling is built.
7. **Scale note.** Candidates come from a vendor search capped per query, so fuzzy scoring is O(candidates per track), not O(catalog); `SequenceMatcher` is not a bottleneck.
8. **How to run.** The two commands from the scripts' docstrings.

Add to `docs/data/README.md` under the existing list: `- [Entity resolution](entity-resolution.md) — identity map, ISRC and fuzzy matching, review queue, measured matcher quality.`

Check: `grep -nE '\$[0-9]|USD|/month' docs/data/entity-resolution.md` prints nothing.

- [ ] **Step 6: Full suite, commit** — `docs(data): entity resolution and matcher evaluation`

---

### Task 4: Ship

- [ ] Final whole-branch review (fresh reviewer, most capable model), fix Critical/Important.
- [ ] PR (title/body via `caveman:caveman-commit`), checks green, merge, wait for Deploy, remove worktree, fast-forward `main`, delete branch.
- [ ] Audit §15.3 B status line (no money figures); loop tracker updated; owner checkpoint recorded.

### Task 5: Owner checkpoint (after the export)

- [ ] Owner: `PYTHONPATH=src .venv/bin/python scripts/export_match_gold.py` (optionally labels the CSV).
- [ ] Agent: `scripts/eval_vendor_match.py <file> [--labels …] --out <scratch>/report.md`; fill "After" and "What it buys" in `docs/data/entity-resolution.md`; if the lowest-cost threshold differs from 0.92 with precision ≥ 99 % on the gold set, change `fuzzy_match_threshold` in `infra/variables.tf` + `src/collector/settings.py` default, with ADR-0023 citing the report; ship as one PR.

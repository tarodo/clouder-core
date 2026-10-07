# Entity resolution and matcher quality

Status: method and tooling shipped; "After" is filled from the owner's first export.

## Why

CLOUDER links one Beatport track to its Spotify and YouTube Music versions. Coverage was
known, correctness was not: the YouTube Music matcher auto-accepts a candidate at a fuzzy
score of 0.92 — a threshold picked by hand — and sends everything below it to a person.
Too low a threshold publishes wrong videos into playlists; too high a threshold buries the
owner in reviews. This page measures where the matcher actually stands, using the decisions
people already made, so the threshold can be argued from data.

## How matching works

| Step | Source → target | How | Human in the loop |
|---|---|---|---|
| Canonicalization | Beatport → canonical catalog | `identity_map` (source, entity type, external id) → canonical id; set-based, race-safe claims (ADR-0022) | no |
| Spotify | canonical → Spotify | ISRC lookup, then a strict/relaxed metadata fallback (ADR-0006) | no |
| YouTube Music | canonical → YouTube Music | search by "artist title" (YouTube Music has no ISRC search), every result scored by `src/collector/vendor_match/scorer.py` | below the threshold |

YouTube Music score: `0.5 · title similarity + 0.4 · best artist similarity + 0.05 if the
duration is within 3 s + 0.05 if the album name matches` (similarities are
`difflib.SequenceMatcher` ratios on lower-cased, whitespace-normalized strings). The best
candidate is accepted automatically at ≥ 0.92; otherwise the top five are stored in
`match_review_queue` and a person accepts one of them, pastes a URL, or rejects the track.

## Before (2026-10-06)

| | |
|---|---|
| Spotify | 96.9 % of tracks matched (91,785 of 94,736); 85,030 linked by ISRC |
| YouTube Music | 568 matches: 472 automatic fuzzy (average confidence 0.994) and 96 manual |
| Review queue | 99 items: 93 resolved, 3 pending, 3 closed as no match (a person's reject and a search with no candidates both end there) — about one YouTube Music match in six needed a person |
| Precision of automatic matches | not measured |
| Threshold 0.92 | chosen by hand |

## Method

1. **Gold set from human decisions.** For every resolved review item the database keeps the
   scored candidates and the person's choice (`vendor_track_map.match_type = 'manual'`). The
   chosen candidate is a positive, the others are negatives; if the person pasted a URL
   outside the list, every candidate is a negative. Rejected items lose their candidates when
   rejected, so they are not used.
2. **Optional hand labels for automatic matches.** A deterministic sample (md5 order) of
   auto-accepted fuzzy matches is exported with an empty `label` column to mark y/n.
3. **Re-scoring.** Each gold item is scored again with the production scorer, so the same
   report answers "what if the threshold were different" (scorer changes can only be judged
   within the stored top five candidates). The export keeps the score production computed;
   items whose metadata changed since the match (a re-ingest that filled a duration, a new
   artist credit) re-score differently, are left out, and are counted in the report.
4. **Per threshold (0.70–1.00):** auto-accepted, correct, wrong, precision, sent to review,
   and cost = wrong auto-matches × 10 + reviews × 1 (a wrong video in a published playlist is
   treated as ten times worse than one manual check; both weights are CLI flags).
5. **Weights.** Review items are the whole population below 0.92; hand-labelled automatic
   matches are a sample, so each one is weighted by its share of all automatic matches.
6. **Bias.** Every review item scored below 0.92 when it was queued, so review items alone
   cannot show whether a threshold above 0.92 would help — without the labelled sample the
   report does not recommend one. Rejected items are not in the gold set (their candidates
   are deleted on reject), which makes precision below 0.92 look somewhat better than it is.

## After

Pending the owner's first export (`scripts/export_match_gold.py`); filled from
`scripts/eval_vendor_match.py`: measured precision at 0.92, the lowest-cost threshold, and
the review load each would produce.

## What it buys

Filled with "After": the precision of today's automatic matches, and how much review work a
data-backed threshold saves at that precision.

## Duplicate artists

Equal names are not necessarily duplicates: Beatport keeps distinct artists that share a name,
and so does the catalog (`test_same_name_different_beatport_ids_create_separate_entities`).
The export therefore measures before anything is merged: how many normalized names are
shared by several artists, and how many of those groups include an artist without a Beatport
identity (for example one created by a Spotify playlist import, ADR-0021) — the case most
likely to be a real duplicate. Merge tooling is decided from those numbers.

## Scale

Candidates come from a vendor search capped per query, so fuzzy scoring costs
O(candidates per track), not O(catalog). `SequenceMatcher` is not a bottleneck at any catalog
size; the per-track vendor search is.

## How to run

```bash
# 1. Export (read-only). Production through the RDS Data API, or any Postgres:
PYTHONPATH=src .venv/bin/python scripts/export_match_gold.py
PYTHONPATH=src .venv/bin/python scripts/export_match_gold.py --database-url postgresql://...

# 2. Optionally fill the `label` column (y/n) of match_gold_<ts>_labels.csv.

# 3. Report:
PYTHONPATH=src .venv/bin/python scripts/eval_vendor_match.py match_gold_<ts>.jsonl \
    --labels match_gold_<ts>_labels.csv --out report.md
```

The exports contain catalog rows and are git-ignored (`match_gold_*`).

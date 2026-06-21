# Video-aware matching for comment fallback — design

**Date:** 2026-06-21
**Status:** Approved (design phase)
**Builds on:** `2026-06-21-youtube-comment-video-fallback-design.md` (shipped)

## Problem

The fallback resolver (`YouTubeCommentProvider.resolve_alternate_videos`) reuses
the vendor-match fuzzy scorer (`vendor_match/scorer.py`) and its `0.92`
threshold. That scorer is wrong for YouTube `videos` results:

- The candidate "artist" is the **uploading channel/label** (e.g. `Fokuz
  Recordings`), not the track artist — so `artist_sim ≈ 0.09`, and it carries
  40% of the score.
- The candidate title embeds the artist (`Lychee - Back in Time`), so
  `title_sim` against the bare title is only `~0.73`.

Net: the *correct* video scores ~0.45 and can never clear 0.92. Measured live on
4 real tracks; every fallback ended `disabled` even when the right video existed.

## Empirical grounding (measured)

Token-set coverage (fraction of query words found in the candidate title, after
normalization + noise removal) separates correct from noise cleanly:

| Track | Best candidate | coverage | jaccard |
|---|---|---|---|
| Lychee — Back In Time | `Lychee - Back in Time` (correct) | 1.00 | 1.00 |
| Tremor — Disposition | `Tremor - Disposition` (correct, +2 copies) | 1.00 | 1.00 |
| Dysfunctional Family — Overwhelmingly Positive | `…Christmas` (wrong track) | 0.50 | 0.40 |
| TENEM — Sonar | mixes / unrelated pop | 0.00 | 0.00 |

Correct = 1.0; nearest noise = 0.5. A "all query words present" gate is precise.

## Decisions

| Topic | Decision |
|---|---|
| Search query | `"{Artists} - {Title}"` (dash form; improves ytmusicapi `videos` recall). |
| Gate | **coverage == 1.0** (every meaningful query token appears in the candidate title) **AND** version-markers match. |
| Artist field | Ignored — the track artist is matched via the candidate **title** words, not the (channel) artist field. |
| Duration guard | **Not added** (coverage already excludes mega-mixes/albums; revisit in prod if needed). |
| Threshold knob | None — the gate is all-or-nothing boolean; the resolver stops using `fuzzy_match_threshold`. |

## The matcher (pure, no network)

New module `src/collector/providers/youtube/video_match.py`:

```python
def video_matches(query_artist: str, query_title: str, candidate_title: str) -> bool:
    ...
```

Algorithm:

1. **Normalize + tokenize:** lowercase, replace non-alphanumeric with spaces,
   split on whitespace.
2. **Token classes:**
   - `STOPWORDS = {the, a, an, of, in, on, and, to, &}` — excluded from coverage.
   - `NOISE = {official, video, audio, lyric, lyrics, hd, hq, 4k, mv, visualizer,
     visualiser, premiere, ft, feat, featuring, music, clip, free, download, out,
     now, prod}` — dropped from BOTH sides (counted neither for coverage nor
     version).
   - `VERSION_MARKERS = {remix, edit, bootleg, mashup, rework, flip, vip,
     instrumental, acapella, acappella, live, cover, version, remaster,
     remastered, sped, slowed, karaoke, dub, extended, radio, mix}` — used only
     for the version check. `"original mix"`/`"original version"` normalizes to
     "no version" (the original).
3. `query_sig = tokens(artist + " " + title) − STOPWORDS − NOISE`
   `cand = tokens(candidate_title) − NOISE`
4. **Coverage:** `query_sig ⊆ cand` (every meaningful query token present).
5. **Version:** `(VERSION_MARKERS ∩ cand) == (VERSION_MARKERS ∩ query_tokens)`
   after the `original mix` normalization. (Version markers are disjoint from
   NOISE, so it does not matter whether the version sets are taken before or
   after noise-stripping; STOPWORDS are also disjoint from VERSION_MARKERS.)
6. Return `coverage AND version`.

Why version-match: coverage alone catches "remix track ↛ original video" (the
remixer name/`remix` words are in the query but missing from the original's
title → coverage < 1.0). The version check adds the reverse guard: "original
track ↛ remix video" (the remix title has all original words **plus** `remix` →
coverage 1.0, but `cand_versions={remix} != query_versions={}` → rejected). It
also separates `Extended Mix`/`Radio Edit` from the original.

## Resolver integration

`YouTubeCommentProvider.resolve_alternate_videos` changes to:

1. Build the search string `f"{artist} - {title}"`.
2. `ytmusic.search(query, filter="videos", limit=search_limit)` (unchanged client/lazy-factory).
3. For each result → `result_to_ref`; skip None and the `exclude_video_id`.
4. Keep candidates where `video_matches(artist, title, ref.title)` is True.
5. Return their `vendor_track_id`s **in ytmusicapi relevance order, capped at 3**
   (no numeric scoring/sort).

The worker (`comments_collect_handler._resolve_and_collect`) is unchanged — it
already tries the returned ids in order until one yields comments, so the 3
identical `Tremor - Disposition` copies are handled (try first; if no comments,
next).

The `threshold` constructor param and the `score_candidate` import are removed
from the provider. `vendor_match/scorer.py` and the vendor-match pipeline are
untouched.

## Testing

- **`video_match` unit tests** (pure, no network):
  - Real positives: `("Lychee","Back In Time","Lychee - Back in Time")` → True;
    `("Tremor","Disposition","Tremor - Disposition")` → True.
  - Real negatives: `("Dysfunctional Family","Overwhelmingly Positive",
    "Dysfunctional Family Christmas (Music Video)")` → False (missing
    "overwhelmingly","positive"); TENEM mix titles → False.
  - Noise tolerance: trailing `(Official Video) [Fokuz Recordings]` / `Lyrics`
    does not break a true match; stopword dropped in title (`Back Time` vs
    `Back In Time`) still matches.
  - Version guard: original track vs `… (Someone Remix)` → False;
    `Back in Time (Klute Remix)` track vs `… (Klute Remix)` video → True;
    original vs `… (Extended Mix)` → False; `(Original Mix)` candidate vs bare
    original → True.
- **Resolver tests** (fake ytmusic client): builds `"{artist} - {title}"`;
  returns only matching ids; excludes the art-track id; caps at 3; preserves
  search order; empty when nothing matches.

## Non-goals (YAGNI)

- No duration guard (deferred; coverage handles mixes).
- No tunable threshold / config knob for the matcher.
- No change to the vendor-match scorer or the playlist-publish path.
- No backfill of already-`disabled` collections (re-runs on a new match, or
  manual re-enqueue as done during the incident).

## Open items for the implementation plan

- Confirm the exact current `resolve_alternate_videos` signature/body to replace
  (it currently imports `score_candidate` + resolves a threshold).
- Decide module placement of the token-class constants (inside
  `video_match.py`).

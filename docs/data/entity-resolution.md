# Entity resolution and matcher quality

Status: measured on 2026-10-08 from the owner's first export and labelled sample.

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
| YouTube Music | canonical → YouTube Music | search by "artist title" (YouTube Music has no ISRC search), every result scored by `src/collector/vendor_match/scorer.py`; runs in `youtube-search-worker`, 250 tracks an hour, newest release first over the whole catalog (fresh ingests land on top by themselves); playlist add searches only what the sweep has not reached | below the threshold |

YouTube Music score: `0.5 · title similarity + 0.4 · best artist similarity + 0.05 if the
duration is within 3 s + 0.05 if the album name matches` (similarities are
`difflib.SequenceMatcher` ratios on folded strings, see below). An automatic match also needs
the same version on both sides (`same_version`): no remix, dub, VIP and the like on one side only,
and a remix of ours named after its remixer. This holds at the threshold too, since the original
scores high for a remix of the same title.

**Folding** (`vendor_match/textfold.py`). Names and titles are read as plain ASCII before they are compared. The tables come from the catalog's own artist names:
- letters NFKD leaves whole: Ø→o, Æ→ae, ı→i, Đ→d, Ł→l, Ɇ→e;
- Greek letters used as Latin lookalikes: Λ→a, Ξ→e, Δ→a, Θ→o (a Greek name is transliterated instead: "ΠΑΝΟΣ" is "panos");
- symbols standing for letters: €→e, ∆▲△→a, ¥→y, $→s;
- Cyrillic, transliterated: "ЛСП" is "lsp".

Decorations and zero-width marks are dropped. Scripts without a Latin reading stay as they are. "XØRØ" scored 0.25 against "Xoro" before folding. The best
candidate is accepted automatically at ≥ 0.92, or below it by the version rule (end of this
page, `match_type = 'fuzzy_version'`); otherwise the top five are stored in
`match_review_queue` and a person accepts one of them, pastes a URL, or rejects the track. That happens in a playlist (the track's YT Music popover) or week by week on Coverage. There, a cell's drawer counts the open reviews and links to `/admin/youtube-review`, which shows each track with its Spotify link and the candidates, each with a pick button and a YouTube link (`GET /admin/youtube/review`, `POST /admin/youtube/review/{track_id}`).

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

Export of 2026-10-07, labels of 2026-10-08: 193 gold items — 87 review accepts with the right
answer among the candidates, 6 accepted from a pasted URL, and 100 automatic matches labelled
by hand (all 100 correct).

| Threshold | Precision | Wrong auto-matches | Sent to review (of 565) |
|---|---|---|---|
| 0.90 | 94.7 % | 27 | 55 |
| 0.91 (lowest cost) | 100 % | 0 | 92 |
| **0.92 (current)** | **100 %** | **0** | **93** |
| 0.96 | 100 % | 0 | 126 |

- Precision at 0.92 is 100 % on the labelled sample; with no error in 100, the error rate is
  below about 3 % at 95 % confidence (rule of three).
- Below 0.91 the review queue catches real mistakes: at 0.90, 27 wrong videos would be
  published automatically.
- 0.91 would save one review out of 93 with no margin to spare, so the threshold **stays at
  0.92**.

## What it buys

The automatic matches are measured, not assumed: none wrong in the sample, and the threshold
is argued from data. Lowering it to 0.90 would save 38 reviews and publish 27 wrong videos;
raising it would add reviews without gaining precision. The same two commands re-measure after
any scorer change.

## Spotify matching quality

Coverage is measured nightly (`spotify_match_pct`, 96.85 %); correctness was not. The worker
links every track the same way (`identity_map.match_type = 'isrc_match'`), so the export
recovers how each link was made by comparing ISRCs:

| Tier | How the worker found it | How the export recognises it |
|---|---|---|
| `isrc` | exact ISRC search | the Spotify track's ISRC equals the catalog's |
| `isrc_neighbour` | sibling ISRC (last digit ± 1 or 2) with a title/artist check | ISRCs differ only in the last character |
| `metadata` | text search with strict or relaxed similarity and a duration check (ADR-0006) | ISRCs differ |
| `no_payload` | linked without a stored Spotify payload | no `source_entities` row for the Spotify id |

**Method.** `scripts/export_spotify_gold.py` (read-only) samples each tier and the
searched-but-not-found tracks deterministically (md5 order) and records each population.
Each match has a Spotify link, each miss a Spotify search link. The owner marks y/n: for a
match, y = the right recording; for a miss, y = really not on Spotify.
`scripts/eval_spotify_match.py` reports precision per tier and estimates recall as
correct matches ÷ (correct matches + estimated misses), where misses = the miss sample's
"it was on Spotify" share × all not-found tracks. Tiers without labels are left out, so the
estimate leans low until every tier is labelled.

**After:** pending the owner's labels.

```bash
PYTHONPATH=src .venv/bin/python scripts/export_spotify_gold.py --per-tier 50
PYTHONPATH=src .venv/bin/python scripts/eval_spotify_match.py spotify_gold_<ts>.jsonl \
    --labels spotify_gold_<ts>_labels.csv
```

## Duplicate artists

Equal names are not necessarily duplicates: Beatport keeps distinct artists that share a name,
and so does the catalog (`test_same_name_different_beatport_ids_create_separate_entities`).
The export therefore measures before anything is merged: how many normalized names are
shared by several artists, and how many of those groups include an artist without a Beatport
identity (for example one created by a Spotify playlist import, ADR-0021) — the case most
likely to be a real duplicate. Merge tooling is decided from those numbers.

Measured on 2026-10-07: 19 shared names (38 artists); 4 of the groups include an artist
without a Beatport identity. Four candidates do not justify merge tooling; they are reviewed by
hand.

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

**Before moving the threshold.** The export also samples the open review queue per band of the top candidate's score (`--band-sample`, 50 per band: 0.90–0.92, 0.85–0.90, 0.70–0.85). Each row shows our title with its mix name and length next to the candidate's. A row's `band` column is set, and `y` means auto-accepting that candidate would be right. Look at the lengths: a candidate that shares the title can be the radio edit of an extended mix, or the original instead of a remix. Since ingest-time search started, about 29 % of the review queue sits at exactly 0.900: title and artist identical, length off by more than 3 s.

**Version rule (2026-10-18).** The owner labelled 150 band rows with one rule: Original Mix, Extended Mix, Radio Mix/Edit are the same track; a remix, dub or VIP is a different one. Lowering the threshold to 0.85 would be right only 73 % of the time. Instead, below 0.92 the first candidate, best score first, is accepted (`version_rule_accepts` in `scorer.py`) when either:

- its title equals ours, the artist is identical, and our mix is generic (Original/Extended/Radio): a shorter edit of the same recording; or
- its length is within 3 s and its title is ≥ 0.95 similar.

Titles are compared with and without the mix name, after Unicode NFKC folding, dropping feat. credits and generic version brackets. The candidate is refused when:
- one side names a version the other lacks (remix, dub, VIP, rework, bootleg, instrumental, acapella, live, slowed, sped up): a dub is not the radio mix, and the radio mix is not a dub;
- ours is a remix whose remixer the candidate does not name;
- the match rests on length alone and the artist similarity is under 0.6. "After the Drop" 4:48 by DJ Rusty is not DjEdyB's; labelled same-recording matches go down to 0.62, through feat. lists and aliases.

The rule only applies from 0.70 up, the lowest labelled band. That floor reads the score with the version-aware title: a short title under a long mix name scores low on the plain title, though the match is exact ("Rush" vs "Rush (Dub Radio Mix)" is 0.33). On the labelled rows the rule is right 85 times in 85 (three rows first read as wrong were unlabelled, not rejected; the owner confirmed them; 95 % lower bound ≈ 96 %); the automatic share of searched tracks goes from about 80 % to about 87 %.

**Closing the old queue.** Reviews queued before the rule still hold candidates the search would now accept. `scripts/rescore_ytmusic_review.py` replays the rule on each open review's stored candidates, best first, with no YouTube request. The default dry run reads through the agent's read-only role and can write a CSV to look at. `--apply` connects as the master user and does what a manual accept does, in one transaction per page: it links the track as `fuzzy_version` and resolves the review. The dry run on 2026-10-22 accepted 2,795 of 10,461 open reviews. That first pass looked only at the top candidate, so the remix of an original that scores higher stayed open: "Don't Shut Up (ISHNLV Remix)" exactly matches the remix, the plain "Don't Shut Up" tops it at 0.90 and is rightly refused. Since 2026-10-22 both the search and the script try every candidate in order.

**Not on Spotify, not on YouTube.** A DJ hears tracks through Spotify, so a track Spotify could not find needs no YouTube review. Each hourly YouTube run starts by closing the open YT Music reviews of such tracks as not on YouTube (`close_youtube_reviews_without_spotify`); the candidates stay on the `no_match` row. If Spotify finds the track later (for example on an admin retry), the next run deletes that row and clears `youtube_searched_at`, so the track is searched on YouTube again (`reopen_youtube_for_spotify_found`). A `no_match` row with candidates is only ever written this way: a person's reject and an empty search leave none. Both steps touch the database only, so they run during a YouTube ban too.

**Second chance.** A track searched within 4 days of its release may not be on YouTube yet: distributors upload late, and search indexes later still. "Daylight (Extended Mix)" by AFTERGLW came out on Beatport on 2026-10-16 and was searched on 10-19; YouTube Music returned no AFTERGLW track then, and the same query found it on 10-23. Such a review is dropped and the track is searched again 4 days after the first search (`reopen_youtube_second_chance`, `SECOND_CHANCE_DAYS`; the owner's call, as later comes too late). The new search falls after that window, so a track gets one second chance. On a sample of 15 such reviews, a search 4 to 7 days later matched 6 automatically.

**Artist check.** When no candidate names any of our artists, in its title or credits, the track is taken as not on YouTube (`artist_named` in `scorer.py`): the search writes `no_match` with reason `artist_absent` instead of a review. Names are compared leniently, because a miss closes the track:
- diacritics and country tags are dropped: "Dabu" is "dabü", "DJ Icon (US)" is "DJ Icon";
- a distinctive word of the name is enough: "Dj SaeRo" is "Deejay SaeRo";
- an alias inside our credit counts: "ORVEXA" in "Artem ORVEXA".

A track whose names are all non-Latin, or whose candidates have no credits, is not judged. The artist alone is not enough either (`candidate_names_track`). The candidate's title must also be like ours: version-aware similarity ≥ 0.5, also against "Artist - Title" when the title names the artist, as video uploads do. Another song of the same artist on YouTube ("White Christmas" by Dax Hill for Khristian Dax's "This!") says nothing of this one. A single word of the name counts only in the credits: "punk" of "Punk Rock" in someone's title "Back To Punk" is not the artist. The owner accepted the cost: a 100-track sample of what this closes held 2 or 3 tracks an artist uploaded under another title (Cyrillic "СКУФ CLUB" for "Skuf", "Roar" for "Rugido"). As the owner put it, how an artist names an upload is their problem; the listeners come first. An early search (within the second-chance window) keeps its review for the second search. All 101 labelled same-recording matches pass the check. `scripts/rescore_ytmusic_review.py` closes existing reviews the same way: on 2026-10-23 the dry run closed 1,599 of 4,746. The stricter check closed 939 more the same day. The script scores stored candidates again with the current scorer, so a scorer change reaches the old queue. After folding, it accepted 20 more and closed 10.

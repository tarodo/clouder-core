# AI reputation of labels and artists

Date: 2026-10-29. Owner-approved in chat (brainstorm with mockups).

## Why

The AI detectors (`ai_lofcz`, `ai_deezer`) flag individual tracks; a flagged track already goes to DISCARD
(PR #369). The owner wants the flag to rub off on whoever releases it: a label or artist caught putting out
AI tracks gets an AI mark, visible next to its name everywhere, and a triage block can send all its tracks
to NOT — including tracks the detector has not checked yet. Streaming AI labels are the main target, but even
one caught track should show.

## Levels

Counted per label and per artist over the tracks in CLOUDER (shared canonical data, one value for all users):

- `total` — tracks in CLOUDER (label: via `clouder_albums.label_id`; artist: via `clouder_track_artists`,
  any role).
- `checked` — tracks with an `ok` row from `ai_lofcz` or `ai_deezer`.
- `ai` — tracks flagged by either (the existing `AI_FLAGGED_SQL`, the same rule as the track badge and
  DISCARD).

The share is `ai / checked` — **not** `ai / total`: only ~13% of tracks are checked (2026-10-29: 32 k of
242 k), so dividing by the total buries streaming AI labels (Abstrato Records: 80 of 87 checked are AI, 869
in CLOUDER → 9% by total).

| Level | Rule |
|---|---|
| none | `ai = 0` |
| 1 — "at least once" | `ai ≥ 1` and share < 25% |
| 2 — "some" | 25% ≤ share ≤ 50% |
| 3 — "almost all" | share > 50% |

Prod counts with these rules (2026-10-29): labels 146 / 108 / 438, artists 74 / 181 / 2 084.

Distributors (DistroKid, TuneCore, Symphonic Starter…) are ordinary labels — owner: "why release there if you
know their reputation". DistroKid is level 3 (3 703 of 5 491 checked).

## Freshness

Levels follow the detector: when `POST /v1/analysis/results` stores pair-analyzer results, the labels and
artists of those tracks are recounted. A one-time backfill counts everything at deploy. `total` only matters
for the tooltip; it may lag new ingest until the next recount of that label/artist (acceptable).
Builder's call: a recount always counts from the rows that exist, so an admin requeue (which deletes ok rows)
leaves a level stale only until those tracks' results come back. One results POST carries ≤ 100 items, so a
recount touches a small set of labels/artists.

## Where the mark shows

Next to every label and artist name in the SPA:

- track rows: triage bucket list, category tracks, playlist tracks;
- the bucket player card and the Curate card (incl. the label tile and artists panel under the player);
- Library: labels and artists lists, label and artist detail headers.

Look (owner-chosen, mockups 2026-10-29): a small "AI" badge, monochrome so it never reads as the track's own
coloured AI badge.

| Level | Fill | Text | Border |
|---|---|---|---|
| 1 | white | black | black |
| 2 | dark grey (~#6b6b6b) | white | none / same grey |
| 3 | black | white | black |

Tooltip on hover (tap on touch): `AI: {ai} of {checked} checked · {total} in CLOUDER`. No mark when there is
no level. UI copy is English like the rest of the SPA.

## Triage block creation

"Advanced options" of the create dialog gets two selects, placed after the "disliked … to NOT" switches:

- "Send AI-label tracks to NOT": Off / From level 1 / From level 2 / From level 3
- "Send AI-artist tracks to NOT": same options

Both default to **Off**. A track goes to NOT when its label's level ≥ the chosen label level, or any of its
artists' level ≥ the chosen artist level.

Branch order at creation (first match wins) keeps today's rules on top:

1. AI-flagged track → DISCARD (when `ai_to_discard`);
2. liked label/artist → FAV (when `include_favorites`) — likes beat this rule, as they beat dislikes;
3. disliked label/artist → NOT, **AI label/artist → NOT** (new, same tier);
4. date branches, compilations, NEW — unchanged.

The rule runs only at creation. A label that crosses the level later does not move tracks of existing blocks
(unlike AI → DISCARD, which also moves later).

The chosen levels are stored on the block and returned with it (like the other creation options).

## Non-goals

- No per-user thresholds or per-user levels; no settings page entry (the choice lives in the create dialog).
- No moving of tracks after creation; no change to the AI → DISCARD rule or the track badge.
- No mark in admin tables or exports.
- `clouder_label_info.ai_content` (LLM enrichment) stays as is and is not shown.

## Anti-goals

- A mark that reads like the track's red/orange/yellow AI badge.
- Making track lists noticeably slower: level data must come from stored values, not per-request counting.

## Left to the builder

Storage shape (columns vs table), how the recount is wired, API field names, component structure, tests.

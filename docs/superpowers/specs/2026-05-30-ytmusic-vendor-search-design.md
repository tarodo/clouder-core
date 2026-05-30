# YT Music Vendor Search — Design

**Date:** 2026-05-30
**Status:** Approved (design)
**Scope:** Implement real track search for YT Music and wire the extensible
per-vendor search mechanism end to end. Playlist creation on YT Music is **out
of scope** for this iteration.

---

## 1. Goal

Every track that lands in a user's playlist must be searched on YT Music and a
match stored, so the user can see the corresponding YT Music track. YT Music is
the first non-Spotify vendor; the mechanism must generalize to future platforms
without handler changes.

The extensibility framework already exists in the codebase. This iteration fills
the three missing links: the **YT Music search implementation**, the
**producer** that enqueues match jobs, and the **read surface** that exposes the
match status to the user.

---

## 2. What already exists (reused as-is)

- **`providers/base.py`** — `LookupProvider` / `ExportProvider` Protocols and the
  `VendorTrackRef` dataclass. The point of extension.
- **`providers/registry.py`** — lazy per-vendor builders behind the
  `VENDORS_ENABLED` gate. Adding a vendor is three steps, no handler edits.
- **`vendor_match_handler.py`** — SQS worker: ISRC fast-path → metadata fuzzy →
  `score_candidate` → confidence threshold → manual review queue. Results cached
  in `vendor_track_map`.
- **`vendor_match/scorer.py`** — fuzzy scorer (title 0.5 / artist 0.4 /
  duration 0.05 / album bonus 0.05). **Left unchanged.**
- **`vendor_track_map`** — keyed `(clouder_track_id, vendor)`, so a YT Music
  match is **shared across all users** (canonical-core model).
- **`match_review_queue`** — top-5 candidates for below-threshold matches.
- **Infra** — SQS `vendor-match` queue + DLQ + event source mapping.

`providers/ytmusic/{lookup,export}.py` currently exist only as stubs raising
`VendorDisabledError`.

### Key constraint: no ISRC on YT Music

Unlike Spotify, YT Music exposes no public ISRC search. The ISRC fast-path in the
worker will never fire for YT; matching relies entirely on metadata fuzzy search.
A meaningful share of matches will therefore be `fuzzy`, and some will fall below
threshold into the review queue.

---

## 3. Decisions

| Decision | Choice |
|---|---|
| Search backend | `ytmusicapi` (unauthenticated search; rich song metadata: artist, album, duration, videoId) |
| Trigger | Enqueue on playlist track-add **and** on Spotify import, **plus** a one-off backfill of tracks already in playlists |
| User-visible outcome | API exposes per-track YT Music status + badge/link in the playlist UI |
| Below-threshold handling | Store top-5 in `match_review_queue` (`needs_review`); review-resolution UI deferred |
| Search algorithm | Multi-pass + YT-specific normalization (shared scorer unchanged) |

---

## 4. Architecture

```
add tracks / Spotify import / backfill
        │  enqueue only if no vendor_track_map[ytmusic]
        ▼
   SQS vendor-match ──► vendor_match_handler ──► YTMusicLookup.lookup_by_metadata
                                │                        │ ytmusicapi (no auth)
                                ▼                        ▼
                          scorer (shared)           VendorTrackRef[]
                                │
              ┌─────────────────┼──────────────────────┐
         ≥ threshold        < threshold            0 candidates
              ▼                  ▼                       ▼
       vendor_track_map    match_review_queue      match_review_queue
        (matched)           (needs_review)          (status=no_match → not_found)
```

The match is canonical/shared: a repeat search of the same track for a different
user is a cache hit and is never re-run.

---

## 5. Components

### 5.1 `providers/ytmusic/lookup.py` — real `YTMusicLookup` (algorithm B)

- `lookup_by_isrc(isrc) -> None` — always `None`; YT has no ISRC search.
  Documented explicitly so the worker's ISRC fast-path is knowingly skipped.
- `lookup_by_metadata(artist, title, duration_ms, album) -> list[VendorTrackRef]`:
  1. Normalize the query (collapse duplicate `feat.`, normalize remix tags).
  2. Pass 1: `search(q, filter="songs")`, take top-N.
  3. Pass 2 (fallback, only if pass 1 is empty/weak): `search(q, filter="videos")`
     — some tracks exist on YT only as videos/uploads.
  4. Convert each result to `VendorTrackRef`: strip the ` - Topic` suffix from
     artist names, convert `duration_seconds → duration_ms`, collect the artist
     list, set `vendor_track_id = videoId`, keep the raw response in
     `raw_payload`.
  5. Return the candidates. Scoring is done by the worker via the shared
     `score_candidate` — the lookup does **not** score.
- `lookup_batch_by_isrc(...)` — raises `VendorDisabledError(reason="not_implemented")`;
  this method is consumed only by the Spotify worker.
- Thin wrapper over `ytmusicapi.YTMusic`, with the client injected through the
  constructor so tests can substitute a fake.

The shared `score_candidate` is reused unchanged. YT-specific cleanup happens in
the adapter before candidates reach the scorer, keeping the scorer generic and
Spotify matching unaffected.

### 5.2 Dependency

Add `ytmusicapi` to `src/collector/requirements.txt` and ensure it is packaged by
`scripts/package_lambda.sh`. Search works **without OAuth**; YT authentication is
needed only for playlist creation, which is out of scope.

### 5.3 Producer — `vendor_match/enqueue.py` (new helper)

- On `_handle_add_playlist_tracks` and the Spotify-import track path: for each
  newly added track with no `vendor_track_map[ytmusic]` row, fetch its metadata
  (artist / title / duration / album / isrc) and send a `VendorMatchMessage` to
  the vendor-match queue.
- New settings field `vendor_match_queue_url` for the API Lambda, plus an
  `sqs:SendMessage` IAM permission in `infra/`.
- Idempotent: never enqueue when a match already exists (saves YT quota).
- Enqueue failures must **not** fail the originating request — log and return
  success; the match arrives later.

### 5.4 Backfill — `scripts/backfill_vendor_match.py` (admin-only)

Run with `PYTHONPATH=src`. Finds every track currently in any playlist that lacks
a `vendor_track_map[ytmusic]` row and enqueues it through the same helper. No new
public route.

### 5.5 Read API — match status in playlist track output

Extend the `GET` playlist-tracks response: each track gains a `ytmusic` field:

```
ytmusic: { status, video_id?, url?, confidence? }
status ∈ { matched, pending, needs_review, not_found }
```

Status derivation:

| Condition | Status |
|---|---|
| Row in `vendor_track_map[ytmusic]` | `matched` (with `video_id`, `url`, `confidence`) |
| Open row in `match_review_queue` | `needs_review` |
| `match_review_queue` row with `status=no_match` | `not_found` |
| None of the above | `pending` |

To make `not_found` deterministic (distinct from `pending`), the worker's
zero-candidates branch writes a `match_review_queue` row with `status=no_match`
(a small change to `vendor_match_handler`). Update `scripts/generate_openapi.py`
and regenerate `frontend/src/api/schema.d.ts`.

### 5.6 Frontend

A YT Music badge/icon per track in the playlist view:

- `matched` → clickable link to `music.youtube.com/watch?v=<videoId>` (tooltip
  shows confidence).
- `pending` → spinner / clock.
- `needs_review` → "review" marker.
- `not_found` → muted marker.

Verify visuals with `cd frontend && pnpm test:browser`.

### 5.7 Config

Add `ytmusic` to `VENDORS_ENABLED` on the vendor-match worker Lambda.

---

## 6. Data flow

Track added → enqueue (if no match) → worker searches YT → result written to
`vendor_track_map` / `match_review_queue` → API derives status → frontend renders
the badge. Because the match is canonical, the same track for another user is a
cache hit and triggers no second search.

---

## 7. Error handling

- `VendorDisabledError` (ytmusic not enabled) → worker logs and skips (current
  behaviour).
- YT failure / throttle → existing `retry_vendor(max_retries=3)`; on exhaustion
  the message goes to the DLQ.
- ytmusicapi internal endpoint breaks → errors are contained in `YTMusicLookup`;
  Spotify matching is unaffected.
- Enqueue errors are logged and swallowed so they never fail the track-add
  request.

---

## 8. Testing

- **Unit:** query normalization and YT response parsing (fake `YTMusic`);
  ` - Topic` stripping; `duration_seconds → ms`; multi-artist handling;
  interaction with the scorer; enqueue idempotency (no duplicates when a match
  exists); the `no_match` branch; API response shape.
- **Integration:** `add tracks → enqueue` path; worker path through to
  `vendor_track_map` / review / `no_match`.
- **Browser:** badges for all four statuses.
- **Regression guard:** `lookup_by_isrc → None` for YT, pinning the "no ISRC"
  contract.

---

## 9. Out of scope (explicit)

- Creating / publishing playlists on YT Music.
- YT OAuth.
- Manual `needs_review` resolution UI (data accumulates in `match_review_queue`;
  the screen comes later).
- Per-vendor scorer weights (approach C — kept as future headroom if algorithm
  B's precision proves insufficient).

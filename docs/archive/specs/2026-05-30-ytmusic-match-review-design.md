# YT Music Match Review (user-facing) — Design

**Date:** 2026-05-30
**Status:** Approved (design)
**Scope:** Let a regular user resolve `needs_review` YT Music matches inline from the playlist view — pick one of the top-5 candidates, paste a YT Music link manually, or mark the track as not on YT. Resolution is canonical (shared across all users). Builds on the YT Music search feature (PR #157).

---

## 1. Goal

The YT Music backfill left a tail of tracks the fuzzy matcher could not auto-confirm (`needs_review`, 9 of 57 in the first run). Give the user a contextual way to resolve them where they already see the problem: the `needs_review` badge on a playlist track. No separate admin screen — the small DJ circle reviews their own playlists.

A resolution writes to the **canonical** `vendor_track_map` (shared by all users), consistent with the existing tenancy model where vendor matches are canonical, not per-user.

---

## 2. Decisions

| Decision | Choice |
|---|---|
| Audience | Regular user (curation Lambda, `user_id` from JWT) |
| Entry point | Inline in the playlist — click the `needs_review` badge |
| Resolution actions | Accept a top-5 candidate; paste a YT Music link; "not on YT" (reject) |
| List scope | Only `needs_review` rows (no `not_found` browsing this iteration) |
| Tenancy | Canonical write to `vendor_track_map` (shared) |
| Manual-link existence check | None — trust the user; format-validate the videoId only |

Out of scope: a dedicated cross-playlist review page, per-user overlay matches, re-running search from the UI, reviewing `not_found` rows.

---

## 3. Flow

```
[badge needs_review] --click--> Popover
        GET match-candidates (lazy, on open)
                │ top-5 from match_review_queue.candidates + the canonical track
                ▼
   Popover:
     ├─ 5 candidates  → "Accept #N"        (vendor_track_id from candidate)
     ├─ paste YT link → "Accept"           (videoId parsed from URL)
     └─ "Not on YT"   → reject
                │
   ┌────────────┴───────────────┐
 accept(vendor_track_id)      reject
   ▼                            ▼
 upsert vendor_track_map       review row → status='no_match'
 (match_type='manual',         (resolved_at set)
  confidence=1.000)            track → not_found
 review row → status='resolved'
   ▼                            ▼
 badge → matched (link)        badge → not_found (muted)
```

Statuses interplay with the existing `fetch_ytmusic_status` read (matched > needs_review > not_found > pending):
- `accept` writes `vendor_track_map` → `matched` wins regardless of the review row; the row is set to `'resolved'` (excluded from the pending/no_match read) for hygiene.
- `reject` sets the row to `'no_match'` → read returns `not_found`. No fallback to `pending`.

---

## 4. Backend (curation Lambda, per-user)

Two routes, scoped under the playlist so the playlist path is the authorization boundary — the user may only resolve tracks within a playlist they own (`validate_tracks_in_scope`), even though the write is canonical.

### `GET /playlists/{id}/tracks/{track_id}/match-candidates?vendor=ytmusic`

- Scope-check the track is in the user's playlist `{id}`.
- Return the open `match_review_queue` row's `candidates` (top-5) plus the canonical track fields for side-by-side comparison:
  ```
  {
    "vendor": "ytmusic",
    "track": { "track_id", "title", "artists", "isrc", "duration_ms", "album" },
    "candidates": [
      { "vendor_track_id", "title", "artists", "album", "duration_ms",
        "url", "score" }, ...
    ]
  }
  ```
  `url` = `https://music.youtube.com/watch?v=<vendor_track_id>`. Candidate fields are projected from the stored `candidates[i].ref` (YT raw payload) + `candidates[i].score`.
- `404` if no open (`status='pending'`) review row for `(track_id, vendor)`.

### `POST /playlists/{id}/tracks/{track_id}/match-resolve`

Body: `{ "vendor": "ytmusic", "action": "accept" | "reject", "vendor_track_id"?: string }`

- Scope-check as above.
- `accept`: `vendor_track_id` required. **Backend format-validates** it (`^[A-Za-z0-9_-]{11}$`) — never trusts the client. The source (candidate vs pasted link) is irrelevant to the backend; one code path. Then:
  - `upsert_vendor_match(clouder_track_id, vendor, vendor_track_id, match_type='manual', confidence=1.000, matched_at=now, payload=<chosen candidate dict, or {videoId, url, source:'manual_url'} when not from the top-5>)`.
  - Mark the review row `status='resolved'`, `resolved_at=now`.
- `reject`: mark the review row `status='no_match'`, `resolved_at=now`.
- Idempotent: `accept` upsert overwrites; `reject` update is a no-op if already resolved. Always returns the resulting `ytmusic` status object for the track so the client can reconcile.

### Repository methods

In `PlaylistsRepository` (reads/writes within the curation Lambda's repo) — or delegating to `ClouderRepository.upsert_vendor_match` for the canonical write:
- `get_open_review(track_id, vendor) -> ReviewRow | None` — the `status='pending'` row with parsed candidates.
- `resolve_review_accept(track_id, vendor, vendor_track_id, payload, now)` — canonical upsert + set row `'resolved'`.
- `resolve_review_reject(track_id, vendor, now)` — set row `'no_match'`.

`'resolved'` is a new `status` value; `match_review_queue.status` has no CHECK constraint, so no migration is required. `'resolved'` and `'no_match'` are both excluded from the `pending` read; the partial unique indexes (`uq_review_pending`, `uq_review_no_match`) are unaffected by adding a `'resolved'` value.

---

## 5. Frontend

- **Clickable badge.** Today `needs_review` renders a non-interactive icon in `YtMusicBadge`. Wrap it in a Mantine `Popover` whose target is an `ActionIcon`. `matched` / `pending` / `not_found` are unchanged.
- **`YtMusicReviewPopover`** (new): header with the canonical track (title / artists / duration / isrc for comparison); top-5 candidate rows (title / artists / album / duration / score / ▶ YT link / "Accept"); a "paste YT link" `TextInput` + "Accept"; a footer "Not on YT" (reject).
- **Hooks** (react-query, matching existing patterns): `useMatchCandidates(playlistId, trackId)` — lazy `GET`, `enabled` when the popover opens; `useResolveMatch(playlistId, trackId)` — `POST` mutation that, on success, optimistically updates `track.ytmusic` in the playlist-tracks cache (accept → `matched` with `url`; reject → `not_found`) and invalidates the tracks query.
- **Util** `parseYtVideoId(input) -> string | null` (jsdom-tested): extracts the 11-char videoId from `music.youtube.com/watch?v=`, `youtube.com/watch?v=`, `youtu.be/`, or a bare id; otherwise `null` → inline field error, no request.

---

## 6. Error handling

- Invalid pasted link → inline field error; no request issued.
- `match-candidates` `404` (row already resolved by another user) → close the popover, refetch the track row.
- Resolve race (another user resolved first): `accept` upsert overwrites; `reject` update no-ops. Backend returns the current `ytmusic` status; the client reconciles from it / refetches.
- Track not in the user's scope → `403`.
- Backend `videoId` format rejection → `400` with a field error surfaced inline.

---

## 7. Testing

- **Backend unit:** `videoId` format validation (valid / wrong length / bad chars); `accept` writes `vendor_track_map` (`match_type='manual'`, `confidence=1.000`) and sets the row `'resolved'`; `reject` sets the row `'no_match'`; candidates projection from stored `ref`; scope-check rejects out-of-scope tracks (`403`); idempotent re-resolve.
- **Frontend:** jsdom — `parseYtVideoId` across URL forms + the resolve hook's optimistic cache update; browser (`*.browser.test.tsx`) — click the `needs_review` badge → candidates render → Accept → badge becomes a matched link.
- **OpenAPI:** add both routes to `scripts/generate_openapi.py`, regenerate `docs/api/openapi.yaml`, and regenerate `frontend/src/api/schema.d.ts` (`pnpm api:types`).

---

## 8. Files (anticipated)

**Backend**
- `src/collector/curation_handler.py` — two route handlers + `_ROUTE_TABLE` entries.
- `src/collector/curation/playlists_repository.py` — `get_open_review`, `resolve_review_accept`, `resolve_review_reject`; reuse `ClouderRepository.upsert_vendor_match` for the canonical write.
- `src/collector/curation/schemas.py` (or the curation schema module) — resolve request model + `videoId` validator.
- `scripts/generate_openapi.py` — the two routes + response schemas.

**Frontend**
- `src/features/playlists/components/YtMusicBadge.tsx` — make `needs_review` open the popover.
- `src/features/playlists/components/YtMusicReviewPopover.tsx` — new.
- `src/features/playlists/hooks/useMatchCandidates.ts`, `useResolveMatch.ts` — new.
- `src/features/playlists/lib/parseYtVideoId.ts` — new (+ test).
- `src/features/playlists/lib/playlistTypes.ts` — candidate/response types.
- `src/api/schema.d.ts` — regenerated.

# ADR-0019: YouTube Music as a second vendor (match + publish), mirrored not shared
Status: Accepted
Date: 2026-06-04

## Context

YouTube Music is the first non-Spotify vendor. Two surfaces were needed: track
**matching** (so a user sees the corresponding YT Music track) and playlist
**publish** (parity with the existing Spotify publish). The provider abstraction —
`LookupProvider` / `ExportProvider` Protocols, `VendorTrackRef`, a registry behind the
`VENDORS_ENABLED` gate (ADR-0004) — and the `vendor_match` worker (ISRC fast-path →
metadata fuzzy → scorer → confidence threshold → review queue), `vendor_track_map`,
and `match_review_queue` already existed.

Key constraint: YouTube Music exposes no public ISRC search, so the ISRC fast-path
never fires for YT. Matching is metadata-fuzzy only, and a meaningful share of tracks
fall below threshold into the review queue.

## Decision

- **Matching.** Implement `providers/ytmusic/{lookup,export}` using `ytmusicapi`
  (unauthenticated search). Enqueue match jobs on playlist track-add, on Spotify
  import, and via a one-off backfill of existing playlist tracks. Below-threshold
  results store the top-5 candidates in `match_review_queue`. `vendor_track_map` is
  keyed `(clouder_track_id, vendor)`, so a YT Music match is shared across all users
  (canonical-core model). The fuzzy scorer is left unchanged.
- **Match review (user-facing).** A regular user resolves `needs_review` matches
  inline from the playlist (click the badge): accept one of the top-5 candidates,
  paste a YT Music link (videoId is format-validated only — no existence check), or
  mark "not on YT". Resolution writes the canonical `vendor_track_map`
  (`match_type='manual'`, confidence 1.0). No admin screen — the small DJ circle
  reviews its own playlists.
- **Publish.** Mirror the Spotify publish path one-to-one with **separate** YouTube
  Music classes; do **not** refactor the working Spotify path into a shared base
  (lower risk; extract later if a third vendor appears). Uses `ytmusicapi`
  authenticated + Google **device-flow** OAuth ("TVs and Limited Input devices"). The
  app-level `client_id`/`client_secret` live in Secrets Manager / SSM; per user we
  persist only the encrypted refresh token. The OAuth app stays in Google "testing"
  mode (≤100 users). Republish is edit-in-place (stable playlist URL). Publish runs
  synchronously in the curation Lambda (mirrors Spotify). Publish state is stored as
  mirrored `ytmusic_*` columns on `playlists` (not a normalized table). The
  `device_code` is client-held between request and poll (backend stateless), like the
  Spotify PKCE verifier. No custom cover (YT Music has no cover API).

## Consequences

- No ISRC → a lower auto-match rate than Spotify; the review queue is a permanent,
  expected surface, not an edge case.
- `ytmusicapi` is an unofficial internal API (ToS grey area) — accepted for the small
  audience.
- "Testing"-mode OAuth means a ~7-day refresh-token expiry, so users re-connect
  roughly weekly, and each must be added as a Google test user.
- Two parallel publish paths (Spotify + YT Music) with no shared base — intentional; a
  shared base is the documented future option.
- Relates to ADR-0004 (provider abstraction), ADR-0006 (Spotify metadata fallback),
  ADR-0011 (Spotify token bundling).

**Cross-references:** `../backend/providers.md`, `../data/data-model.md`. Source specs
(now archived):
`../archive/specs/2026-05-30-ytmusic-vendor-search-design.md`,
`../archive/specs/2026-05-30-ytmusic-match-review-design.md`,
`../archive/specs/2026-05-31-youtube-music-publish-design.md`.

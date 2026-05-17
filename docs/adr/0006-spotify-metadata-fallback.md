# ADR-0006: Spotify metadata fallback with strict / relaxed tiers
Status: Accepted
Date: 2026-05-17

## Context

The primary Spotify enrichment path looks up a track by ISRC (`GET /v1/search?q=isrc:{ISRC}&type=track`). ISRC is an exact identifier and the lookup is deterministic. However, Beatport data quality produces a meaningful rate of ISRC mismatches: the ISRC in the Beatport payload is sometimes off by one digit from the ISRC Spotify has indexed, or the track was registered under a different ISRC altogether.

When the primary ISRC lookup returns zero results, the track is marked as "searched but not found" (`spotify_searched_at` set, `spotify_id` null). Without enrichment, these tracks have no `release_type`, no `spotify_release_date`, and no vendor match — downstream triage classification degrades.

Two fallback stages were designed. Stage 1 exploits the common off-by-one pattern: ISRC neighbours (last digit ±1, ±2) are tried in closest-first order. Stage 1 candidates are accepted only when they pass a title + artist similarity gate; duration is not checked because radio edits and extended versions of the same recording can differ substantially.

Stage 2 uses Spotify's text search (`q=track:{title} artist:{first_artist}`). Text search is noisier: the Beatport artist string is multi-artist and includes country suffixes (`(UK)`, `(US)`) that Spotify's `artist:` operator does not handle gracefully. The query is therefore narrowed to the first artist only, with country suffixes stripped. Candidate results are scored by title and artist similarity after normalising both sides (stripping feat., remix parentheticals, etc.).

A single text-similarity threshold would either over-accept (causing incorrect matches) or over-reject (missing legitimate matches where the track exists under a slightly different master). The decision was to add a **relaxed tier** for near-perfect text matches that differ only in duration — same recording, different master or radio edit — while keeping the **strict tier** for the common case where duration is available.

The fallback is disabled by default (`SPOTIFY_METADATA_FALLBACK_ENABLED=false`) to preserve the deterministic baseline and allow operators to enable it only when confident in the thresholds.

## Decision

When an ISRC lookup returns zero items and `SPOTIFY_METADATA_FALLBACK_ENABLED=true`, the Spotify worker tries (1) sibling ISRC neighbours with a title+artist gate, then (2) a metadata search with two acceptance tiers: **strict** (`title_sim ≥ 0.90`, `artist_sim ≥ 0.85`, `|dur_diff| ≤ 3000 ms`) and **relaxed** (`title_sim ≥ 0.95`, `artist_sim ≥ 0.95`, no duration check). Strict matches win when both tiers have hits.

## Consequences

- The fallback adds latency to tracks that miss the ISRC lookup: up to 3 additional Spotify API calls (4 neighbour ISRCs checked in stage 1, 1 text search in stage 2). Spotify rate limits apply; `SPOTIFY_METADATA_FALLBACK_ENABLED` should not be enabled on high-volume batches without monitoring DLQ depth.
- On stage 2 reject, `spotify_metadata_fallback_scores` is logged with `best_title_sim` and `best_artist_sim`. Use this to tune thresholds without re-running the batch.
- Thresholds are configurable via env vars on `beatport-prod-spotify-search-worker`: `SPOTIFY_FUZZY_TITLE_MIN` (default `0.90`), `SPOTIFY_FUZZY_ARTIST_MIN` (default `0.85`), `SPOTIFY_FUZZY_DURATION_TOLERANCE_MS` (default `3000`).
- The fallback does NOT apply when the track has no ISRC at all (not a miss, simply absent from Beatport data). Only tracks where a primary ISRC lookup returned 0 items enter the fallback.
- Title and artist normalisation (`_normalize_title_for_match`) strips feat. clauses and mix-type parentheticals. Changing this function affects both stage 1 and stage 2 matching.

**Cross-references:** `../data/search-and-enrichment.md`.

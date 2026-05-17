# ADR-0007: `release_type` derived from Spotify
Status: Accepted
Date: 2026-05-17

## Context

Triage classification distinguishes between albums, singles, and compilations — a DJ cares whether a track comes from a label compilation (`NOT` bucket candidate) versus a dedicated single. `release_type` encodes this.

Beatport's track API payload does not expose a release-type field. The Beatport release object contains `release.{id, name, label, slug}` but no `album_type` equivalent. This information simply is not available in the raw ingest data.

Spotify's track object includes `album.album_type` with values `album`, `single`, and `compilation`. This is exactly the field needed, and it is already fetched during ISRC enrichment. The Spotify ISRC lookup returns the full track object, so no additional API call is required to obtain `release_type`.

The propagation path has two hops. First, `release_type` is written onto `clouder_tracks` when the ISRC lookup succeeds (`UpdateSpotifyResultCmd`). Second, a separate pass (`propagate_release_type_to_albums`) copies the value from the track to its parent `clouder_albums` row. The album-level propagation is deferred to a second pass because multiple tracks in the same album may be enriched at different times; the album row should reflect a consistent value from any successfully-enriched track in the set.

Tracks that have been searched but not found on Spotify keep `release_type = NULL` indefinitely unless the fallback succeeds. `NULL` is a valid query-time state meaning "not yet determined".

## Decision

`release_type` is sourced from Spotify (`album.album_type`) during ISRC enrichment. The Beatport payload does not expose a release-type field. The value is written onto `clouder_tracks` and propagated to the parent `clouder_albums` via `propagate_release_type_to_albums`. Tracks without a successful ISRC lookup keep `release_type = NULL`.

## Consequences

- `clouder_tracks.release_type` and `clouder_albums.release_type` are both nullable. Downstream queries that classify tracks by release type must handle `NULL` (typically treated as "unclassified" in triage).
- The propagation from track to album is eventually consistent: the album row is updated only after at least one track in the album has a successful Spotify lookup. Early triage of an album before any of its tracks are enriched will see `release_type = NULL`.
- If Spotify's `album_type` is wrong or stale, it propagates to the CLOUDER canonical layer. There is no override mechanism in the current schema.
- Changing `release_type` retrospectively (e.g. after a metadata correction on Spotify) requires re-running the Spotify enrichment for the affected track, which sets a new `spotify_searched_at` timestamp and overwrites the prior value.
- `clouder_tracks.spotify_release_date` follows the same derived-from-Spotify pattern and has the same NULL-until-enriched semantics.

**Cross-references:** `../data/canonicalization.md`.

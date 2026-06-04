# Copy Playlist as JSON — Design

**Date:** 2026-06-02
**Status:** Approved (design), pending implementation plan
**Branch:** `add_copy_tracklist`

## Goal

Add a "Copy playlist" button on the playlist detail page. Clicking it copies the
playlist to the clipboard as formatted JSON: a wrapper object with the playlist
name, track count, and a list of tracks. Each track carries the fields needed to
seed an existing web-search prompt that finds full track info online.

As part of the same work, expose the Beatport track id on the playlist tracks API
and add a per-track Beatport link icon in the track row, next to the existing
Spotify and YouTube Music links.

## Scope

In scope:
- Backend: expose `beatport_track_id` + `beatport_slug` on the playlist tracks response.
- Frontend: copy-to-clipboard button producing the JSON below.
- Frontend: Beatport link icon in each playlist track row.

Out of scope:
- A dedicated server-side export endpoint (rejected — see Approaches).
- Storing beatport id/slug as first-class columns on `clouder_tracks` (we resolve
  via the existing `identity_map` / `source_entities` join instead).

## Approaches considered

- **A — client-side JSON build + minimal backend (CHOSEN).** Build the JSON on the
  frontend from the already-loaded playlist tracks. Touch the backend only to add
  `beatport_track_id` (+ `beatport_slug`) to the existing
  `GET /playlists/{id}/tracks` response. The same Beatport URL helper feeds both the
  JSON and the new row icon. Minimal code; the export format can change without a deploy.
- **B — dedicated `/playlists/{id}/export` endpoint** returning ready-made JSON.
  Rejected: a new route means three registration sites (route table + `generate_openapi`
  + `infra/curation_routes_*.tf`) plus a handler and tests, for a format only the button
  needs today.
- **C — pure frontend, no backend.** Rejected: the Beatport id is not present on the
  track object, so the Beatport link cannot be constructed without backend work.

## Clipboard JSON format

```json
{
  "playlist": "<playlist name>",
  "track_count": 42,
  "tracks": [
    {
      "title": "Strobe",
      "mix_name": "Extended Mix",
      "artists": ["deadmau5"],
      "label": "mau5trap",
      "isrc": "USUS11200402",
      "beatport_url": "https://www.beatport.com/track/strobe/123456",
      "spotify_url": "https://open.spotify.com/track/<id>",
      "youtube_music_url": "https://music.youtube.com/watch?v=<id>"
    }
  ]
}
```

Rules:
- Wrapper object: `playlist` (name), `track_count`, `tracks` (array).
- `artists` is an array of artist names (preserve the order from the API response).
- `mix_name`, `isrc`, `label`, and any of the three URLs are `null` when the underlying
  data is missing.
- `beatport_url`: `https://www.beatport.com/track/{slug}/{id}`. `slug` comes from
  `source_entities.payload->>'slug'` when present; if the slug is empty, use the
  placeholder `_` (`https://www.beatport.com/track/_/{id}`) — Beatport redirects to the
  canonical URL by id. The redirect/placeholder behavior is verified against a real row
  during implementation; if the placeholder does not redirect reliably, fall back to
  emitting `beatport_url: null` when no slug is available.
- `spotify_url`: `https://open.spotify.com/track/{spotify_id}` when `spotify_id` is set.
- `youtube_music_url`: the matched YT Music URL from `track.ytmusic` when status is
  `matched` and a url exists.
- JSON is pretty-printed with 2-space indentation (`JSON.stringify(obj, null, 2)`).

## Backend changes

File: `src/collector/curation/playlists_repository.py` — the playlist tracks query.

- Add joins to resolve the canonical track to its Beatport identity:
  ```sql
  LEFT JOIN identity_map im
    ON im.clouder_id = t.id
   AND im.clouder_entity_type = 'track'
   AND im.source = 'beatport'
  LEFT JOIN source_entities se
    ON se.source = 'beatport'
   AND se.entity_type = 'track'
   AND se.external_id = im.external_id
  ```
- Select `im.external_id AS beatport_track_id` and `se.payload->>'slug' AS beatport_slug`.
- Add `beatport_track_id` and `beatport_slug` to the `GROUP BY` (or aggregate
  appropriately) so the existing per-track grouping still holds. The `identity_map` PK is
  `(source, entity_type, external_id)`, and the join is by `clouder_id`, so at most one
  Beatport row matches per track.

File: `PlaylistTrackResponse` (pydantic model serving the tracks list).

- Add `beatport_track_id: str | None = None` and `beatport_slug: str | None = None`.

OpenAPI / schema:
- Regenerate `docs/api/openapi.yaml`:
  `PYTHONPATH=src .venv/bin/python scripts/generate_openapi.py`.
- Regenerate `frontend/src/api/schema.d.ts` so the frontend CI diff-gate passes.

## Frontend changes

Types — `frontend/src/features/playlists/lib/playlistTypes.ts`:
- `PlaylistTrack` gains `beatport_track_id: string | null` and `beatport_slug: string | null`.

New pure module — `frontend/src/features/playlists/lib/playlistExport.ts`:
- `beatportTrackUrl(id: string | null, slug: string | null): string | null` — shared by
  the row icon and the export builder.
- `buildPlaylistExport(playlistName: string, tracks: PlaylistTrack[]): PlaylistExport` —
  maps tracks to the JSON shape above. Pure function (no DOM, no clipboard) for easy
  testing and reuse.

Copy button — `frontend/src/features/playlists/components/CopyPlaylistButton.tsx`:
- A Mantine `<Button variant="outline" leftSection={<IconCopy />}>`, placed in the same
  `publishSlot` `<Group>` as the existing Publish-to-Spotify / Publish-to-YT-Music buttons
  (rendered through `PlaylistMetaPanel`).
- On click: `JSON.stringify(buildPlaylistExport(name, tracks), null, 2)` →
  `navigator.clipboard.writeText(...)` → success notification ("Скопировано N треков").
- Disabled when the playlist has 0 tracks.
- Clipboard failure → error notification; never throws to the UI.

Row link — `frontend/src/features/playlists/components/PlaylistTrackRow.tsx`:
- Next to the existing Spotify `ActionIcon`, add a Beatport link `ActionIcon component="a"`
  using `IconLink` (the icon already used for Beatport in
  `frontend/src/features/library/lib/channelMeta.ts`; tabler has no Beatport brand icon).
- Render only when `track.beatport_track_id` is set; `href` from `beatportTrackUrl(...)`.

i18n:
- Add strings for the copy button label, the copied/failed notifications, and the
  "open in Beatport" aria-label.

## Data loading

The JSON is built from the playlist tracks already loaded on the detail page — no new
fetch is required for the copy action. Implementation verifies the full track list is in
memory (the list query has no LIMIT; rendering may be virtualized but the data is complete).

## Error handling

- `navigator.clipboard` requires a secure context — production is served over HTTPS, so
  this holds. On failure, show an error notification; do not crash.
- Tracks not originating from Beatport resolve to `beatport_url: null` and hide the row
  icon.
- Empty playlist → copy button disabled.

## Testing

Backend:
- Query test: a track with a Beatport `identity_map` row returns `beatport_track_id` and
  `beatport_slug`; a track without one returns `null` for both.

Frontend:
- Unit tests for `buildPlaylistExport` and `beatportTrackUrl`: null fields, `mix_name`,
  multiple artists, URL construction with and without slug, and missing Beatport id.
- Component test for the copy button: clicking calls `navigator.clipboard.writeText`
  (mocked) with the expected JSON string; disabled state on an empty playlist.

CI gates:
- `docs/api/openapi.yaml` and `frontend/src/api/schema.d.ts` regenerated and diff-clean.
- Frontend typecheck + lint + test pass locally before merge.

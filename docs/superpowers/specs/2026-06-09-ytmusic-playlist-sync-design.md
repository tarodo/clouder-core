# YouTube Music playlist sync — correct republish

**Date:** 2026-06-09
**Status:** Approved (design), pending implementation plan

## Problem

Publishing a playlist to YouTube Music works the first time. After the user
reorders tracks in CLOUDER and republishes:

1. The UI shows *"YouTube rejected the cover image (needs a square JPEG/PNG
   under 2 MB)"* — read by the user as «неверный формат обложки».
2. The track order on YouTube does **not** change.

Both are confirmed in code, not transient API issues.

## Root causes

### Cause 1 — cover upload always uses `insert`
`YoutubeDataApiClient.set_cover` (`src/collector/curation/youtube_data_api_client.py:104`)
always sends `playlistImages.insert` (POST `/upload/youtube/v3/playlistImages`).

- First publish: playlist has no image → `insert` succeeds.
- Republish: playlist already has an image → YouTube rejects the second
  `insert` → `YtmusicApiError`.

`YtmusicPublishService.publish` (`src/collector/curation/ytmusic_publish_service.py:138-149`)
catches any cover exception and sets `cover_failed=true`. The frontend renders
the i18n key `playlists.publish.ytmusic_cover_failed`
(`frontend/src/i18n/en.json:287`), whose text mentions format/size — so the
message is **misleading**: the real cause is `insert`-over-existing, not the
image format. The YouTube Data API exposes a separate `playlistImages.update`
(PUT) for replacing an existing image, which is never called.

### Cause 2 — reorder is never reflected on YouTube
`YtmusicPublishService.publish` (`src/collector/curation/ytmusic_publish_service.py:128-134`)
diffs YouTube vs desired tracks as **sets**, not ordered lists:

```python
existing_vids = [it["videoId"] for it in existing_items]
if existing_vids != video_ids:
    desired = set(video_ids)
    present = set(existing_vids)
    to_remove = [it["itemId"] for it in existing_items if it["videoId"] not in desired]
    to_add = [v for v in video_ids if v not in present]
    self._yt.remove_items(target_id, to_remove)
    self._yt.add_items(target_id, to_add)
```

A pure reorder leaves the membership set unchanged → `to_remove == []`,
`to_add == []` → zero API calls → order on YouTube is untouched. The code
comment at lines 124-125 acknowledges this was intentional (quota saving).

### Cause 3 (contributing) — reorder does not flag ytmusic republish
`PlaylistsRepository._mark_dirty_if_published`
(`src/collector/curation/playlists_repository.py:1090`) only marks Spotify
playlists dirty:

```sql
UPDATE playlists SET needs_republish = TRUE, updated_at = :now
WHERE id = :id AND spotify_playlist_id IS NOT NULL
```

`ytmusic_needs_republish` is never set on reorder, so the UI never signals that
a YouTube republish is needed.

## Chosen approach

Confirmed with the user:

- **Reorder strategy:** minimal moves via `playlistItems.update` with
  `snippet.position` (touch only tracks that are out of place). Quota-friendly.
- **Cover strategy:** try `insert`; on conflict fall back to `update`.

## Design

### Fix 1 — cover: insert → update fallback
File: `src/collector/curation/youtube_data_api_client.py`

- Keep `set_cover` doing POST `playlistImages.insert` as the primary call.
- If `insert` fails with a non-auth, non-quota error (i.e. anything other than
  401 / quota-exceeded), retry via PUT `playlistImages.update` on
  `/upload/youtube/v3/playlistImages` with the **same** multipart/related body
  (snippet `{playlistId, type}` + image bytes).
- Raise `YtmusicApiError` only if **both** insert and update fail — so the
  service's `cover_failed=true` (and the user-facing format/size message) now
  fires only on a genuine format/size problem.
- The YouTube error message is already logged (`error_message` in
  `ytmusic_publish_partial_fail`); the exact "image already exists" reason is
  undocumented, so the trigger is "insert failed" and can be tightened later
  from prod evidence.
- **Optional quota optimization (not in MVP unless requested):** when
  `ytmusic_playlist_id` already existed before this publish, call `update`
  first and fall back to `insert`, avoiding a guaranteed-failing `insert`.
  Default: insert-first, as chosen.

### Fix 2 — reorder: minimal-move position sync
Files: `src/collector/curation/youtube_data_api_client.py`,
`src/collector/curation/ytmusic_publish_service.py`

New client method:

```python
def move_item(self, playlist_id: str, item_id: str, video_id: str, position: int) -> None:
    # PUT /youtube/v3/playlistItems?part=snippet  (50 quota units)
    body = {
        "id": item_id,
        "snippet": {
            "playlistId": playlist_id,
            "resourceId": {"kind": "youtube#video", "videoId": video_id},
            "position": position,
        },
    }
```

Required fields confirmed against the API docs: `id`, `snippet.playlistId`,
`snippet.resourceId`; `snippet.position` is the settable reorder field.

Service flow in `publish`, after the existing membership diff
(remove/add):

1. If `add_items` ran, **re-fetch** items via `get_existing_items` (list = 1
   quota unit) to learn new playlistItem ids and the current order. If nothing
   was added or removed, reuse the `existing_items` already fetched.
2. Build `video_id → item_id` from the fetched items.
3. **Selection-style reorder.** Maintain a working model of the current order.
   For `i` in `0 .. len(desired)-1`:
   - if `current[i] == desired[i]`: skip (no API call).
   - else: find the item whose videoId is `desired[i]` at some position `j > i`,
     call `move_item(..., position=i)`, and update the working model (remove
     from `j`, insert at `i`, shifting `i..j-1` right by one).
   The prefix `[0..i]` is fixed once placed. API calls = number of tracks not
   already in place (drag one track ≈ 1 call; full reversal ≈ N).
4. Duplicate videoIds within a playlist are not expected (matched set is unique
   per track); if encountered, match by first unused item id.

### Fix 3 — flag ytmusic dirty on reorder
File: `src/collector/curation/playlists_repository.py`

Extend `_mark_dirty_if_published` to also set the ytmusic flag:

```sql
UPDATE playlists SET ytmusic_needs_republish = TRUE, updated_at = :now
WHERE id = :id AND ytmusic_playlist_id IS NOT NULL
```

(Either a second statement or a combined update covering both publish targets.)
This lights the "needs republish" badge after a reorder.

## Testing (TDD)

Unit tests, fake clients (no network), following existing patterns in
`tests/unit/test_youtube_data_api_client.py` and
`tests/unit/test_ytmusic_publish_service.py`.

**`set_cover`:**
- insert succeeds → no update call, no error.
- insert fails (non-auth) → `update` is called → success, no raise.
- both insert and update fail → raises `YtmusicApiError`.
- 401 on insert → still surfaces as auth error (not silently swallowed into a
  cover retry loop).

**`publish` reorder:**
- reorder-then-republish with unchanged membership → emits `move_item` calls
  that realize the desired order (assert recorded itemId + position sequence).
- already-correct order → zero `move_item` calls.
- membership change + reorder → re-fetch happens, new items end up at correct
  positions.
- skipped/no-match tracks still excluded from the order.

**Repository:**
- reorder of a ytmusic-published playlist sets `ytmusic_needs_republish=TRUE`.
- reorder of a spotify-only playlist still sets `needs_republish` (no
  regression).

## Out of scope

- Changing the i18n cover-failure text (after the fix it only fires on genuine
  format/size errors, so it becomes accurate).
- Quota backoff / retry handling and bulk endpoints (Data API v3 has no bulk
  playlistItems write).

## Quota note

Drag one track in a 30-track playlist ≈ 1 `move_item` (50) + 1 `list` (1) +
1 cover `update` (~50) ≈ ~100 units. Default Data API daily quota is 10,000
units. Full reversal of N tracks ≈ N × 50 units (worst case).

## Key references

- `playlistItems.update`: PUT `https://www.googleapis.com/youtube/v3/playlistItems`,
  50 units. https://developers.google.com/youtube/v3/docs/playlistItems/update
- `playlistImages.insert` / `update`:
  https://developers.google.com/youtube/v3/docs/playlistImages

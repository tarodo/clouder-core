# YouTube Music playlist sync — correct republish — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make republishing a YouTube Music playlist update both the cover (no false "invalid format" error) and the track order, and flag a YouTube republish as needed after a reorder.

**Architecture:** Three independent fixes. (1) `YoutubeDataApiClient.set_cover` tries `playlistImages.insert`; on a non-auth failure it falls back to `playlistImages.update`. (2) A new `move_item` client method (PUT `playlistItems` + `snippet.position`) plus a selection-style reorder pass in `YtmusicPublishService.publish` that touches only out-of-place tracks. (3) `PlaylistsRepository._mark_dirty_if_published` also sets `ytmusic_needs_republish` for ytmusic-published playlists.

**Tech Stack:** Python 3, YouTube Data API v3 (REST over a `requests` session), pytest with hand-rolled fakes (no network), Aurora via RDS Data API (faked with `MagicMock` in unit tests).

**Spec:** `docs/superpowers/specs/2026-06-09-ytmusic-playlist-sync-design.md`

---

## Conventions for every task

- **Run from the worktree root:** `/Users/roman/Projects/clouder-projects/clouder-core/.claude/worktrees/fix_ytmusic`
- **pytest binary** lives at the MAIN repo `.venv` (worktrees share it):
  `/Users/roman/Projects/clouder-projects/clouder-core/.venv/bin/pytest`
  `pytest.ini` already sets `pythonpath = src`, so no `PYTHONPATH` export is needed for the runner.
- **Commits:** Conventional Commits, single-line `-m` subject, NO `Co-Authored-By` trailer (a hook strips/blocks it). Generate the subject with the `caveman:caveman-commit` skill, then `git commit -m "<subject>"`. Already on feature branch `worktree-fix_ytmusic` — commit there.
- No new API routes are added, so **no** OpenAPI regeneration or `infra/*.tf` changes are required.

## File structure

| File | Responsibility | Change |
|---|---|---|
| `src/collector/curation/youtube_data_api_client.py` | YouTube Data API v3 HTTP client | Modify `set_cover`; add `_upload_cover` helper + `move_item` |
| `src/collector/curation/ytmusic_publish_service.py` | Publish orchestration | Add reorder pass + `_reorder_items` helper |
| `src/collector/curation/playlists_repository.py` | DB access (Data API) | Extend `_mark_dirty_if_published` |
| `tests/unit/test_youtube_data_api_client.py` | Client unit tests | Add cover-fallback + `move_item` tests; fix one existing test |
| `tests/unit/test_ytmusic_publish_service.py` | Service unit tests | Extend `FakeClient`; add reorder tests |
| `tests/unit/test_playlists_repository.py` | Repo unit tests | Add ytmusic dirty-flag test |

---

## Task 1: Cover — insert with update fallback

**Files:**
- Modify: `src/collector/curation/youtube_data_api_client.py` (`set_cover`, currently lines 104-132)
- Test: `tests/unit/test_youtube_data_api_client.py`

- [ ] **Step 1: Fix the existing error test, then add the new failing tests**

The current `test_set_cover_error_raises` (lines 149-152) queues a single `400`. After this change a single `400` triggers the update fallback (which the default `FakeSession` answers `200`), so the call would no longer raise. Update it to queue **two** failures, and add the fallback tests.

Replace `test_set_cover_error_raises` and add the new tests:

```python
def test_set_cover_insert_succeeds_no_update():
    s = FakeSession([FakeResp(200, {"id": "img1"})])
    _client(s).set_cover("PL", b"\xff\xd8\xffJPEG")
    assert [c["method"] for c in s.calls] == ["POST"]


def test_set_cover_insert_conflict_falls_back_to_update():
    s = FakeSession([
        FakeResp(400, {"error": {"message": "image already exists"}}),
        FakeResp(200, {"id": "img1"}),
    ])
    _client(s).set_cover("PL", b"\xff\xd8\xffJPEG")
    assert [c["method"] for c in s.calls] == ["POST", "PUT"]
    # Both hit the same media-upload endpoint with the same multipart body.
    assert s.calls[1]["url"] == "https://www.googleapis.com/upload/youtube/v3/playlistImages"
    assert b'"playlistId": "PL"' in s.calls[1]["data"]


def test_set_cover_both_fail_raises():
    s = FakeSession([
        FakeResp(400, {"error": {"message": "bad type"}}),
        FakeResp(400, {"error": {"message": "still bad"}}),
    ])
    with pytest.raises(YtmusicApiError):
        _client(s).set_cover("PL", b"\xff\xd8\xffX")
    assert [c["method"] for c in s.calls] == ["POST", "PUT"]


def test_set_cover_401_does_not_retry():
    s = FakeSession([FakeResp(401, {})])
    with pytest.raises(YtmusicNotAuthorizedError):
        _client(s).set_cover("PL", b"\xff\xd8\xffX")
    assert [c["method"] for c in s.calls] == ["POST"]
```

- [ ] **Step 2: Run the new tests to verify they fail**

Run: `/Users/roman/Projects/clouder-projects/clouder-core/.venv/bin/pytest tests/unit/test_youtube_data_api_client.py -q`
Expected: the 4 new tests FAIL (`set_cover` makes no PUT call / does not raise `YtmusicNotAuthorizedError`).

- [ ] **Step 3: Implement insert→update fallback**

In `src/collector/curation/youtube_data_api_client.py`, replace the whole `set_cover` method (lines 104-132) with a body-builder helper plus the fallback logic. Note `YtmusicNotAuthorizedError` is already imported (line 16).

```python
    def set_cover(self, playlist_id: str, image_bytes: bytes) -> None:
        """Set/replace a custom playlist cover. Tries playlistImages.insert
        (POST); if that fails for a reason other than auth (most commonly the
        playlist already has an image), retries playlistImages.update (PUT) on
        the same media-upload endpoint. Raises only if both fail."""
        resp = self._upload_cover("POST", playlist_id, image_bytes)
        status = getattr(resp, "status_code", 0)
        if 200 <= status < 300:
            return
        if status == 401:
            raise YtmusicNotAuthorizedError("YouTube returned 401 (token rejected)")
        resp2 = self._upload_cover("PUT", playlist_id, image_bytes)
        status2 = getattr(resp2, "status_code", 0)
        if 200 <= status2 < 300:
            return
        raise YtmusicApiError(
            f"YouTube cover insert {status} / update {status2}: "
            f"{self._error_message(resp2)}"
        )

    def _upload_cover(self, method: str, playlist_id: str, image_bytes: bytes) -> Any:
        """Build the multipart/related body and send it with the given HTTP
        method (POST = insert, PUT = update). YouTube requires a square (1:1)
        JPEG/PNG <= 2 MB."""
        content_type = "image/png" if image_bytes[:8].startswith(_PNG_MAGIC) else "image/jpeg"
        metadata = json.dumps(
            {"snippet": {"playlistId": playlist_id, "type": _COVER_TYPE}}
        )
        body = (
            f"--{_COVER_BOUNDARY}\r\n"
            "Content-Type: application/json; charset=UTF-8\r\n\r\n"
            f"{metadata}\r\n"
            f"--{_COVER_BOUNDARY}\r\n"
            f"Content-Type: {content_type}\r\n\r\n"
        ).encode("utf-8") + image_bytes + f"\r\n--{_COVER_BOUNDARY}--\r\n".encode("utf-8")
        headers = {
            "Authorization": f"Bearer {self._token}",
            "Content-Type": f"multipart/related; boundary={_COVER_BOUNDARY}",
            "Accept": "application/json",
        }
        return self._session.request(
            method=method,
            url=f"{_UPLOAD_BASE}/playlistImages",
            params={"part": "snippet", "uploadType": "multipart"},
            data=body,
            headers=headers,
        )
```

- [ ] **Step 4: Run the full client test file to verify pass + no regression**

Run: `/Users/roman/Projects/clouder-projects/clouder-core/.venv/bin/pytest tests/unit/test_youtube_data_api_client.py -q`
Expected: PASS, including the updated `test_set_cover_multipart_upload` / `test_set_cover_detects_png` (single-POST happy path unchanged).

- [ ] **Step 5: Commit**

```bash
git add src/collector/curation/youtube_data_api_client.py tests/unit/test_youtube_data_api_client.py
git commit -m "fix(ytmusic): replace cover via update when insert conflicts"
```

---

## Task 2: Client `move_item` method

**Files:**
- Modify: `src/collector/curation/youtube_data_api_client.py` (add method near `add_items`, around line 102)
- Test: `tests/unit/test_youtube_data_api_client.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/unit/test_youtube_data_api_client.py`:

```python
def test_move_item_puts_with_position():
    s = FakeSession([FakeResp(200, {"id": "i1"})])
    _client(s).move_item("PL", "i1", "v1", 2)
    call = s.calls[0]
    assert call["method"] == "PUT"
    assert call["url"].endswith("/youtube/v3/playlistItems")
    assert call["params"] == {"part": "snippet"}
    assert call["json"]["id"] == "i1"
    assert call["json"]["snippet"]["playlistId"] == "PL"
    assert call["json"]["snippet"]["resourceId"] == {"kind": "youtube#video", "videoId": "v1"}
    assert call["json"]["snippet"]["position"] == 2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `/Users/roman/Projects/clouder-projects/clouder-core/.venv/bin/pytest tests/unit/test_youtube_data_api_client.py::test_move_item_puts_with_position -v`
Expected: FAIL with `AttributeError: 'YoutubeDataApiClient' object has no attribute 'move_item'`.

- [ ] **Step 3: Implement `move_item`**

Add directly after `add_items` (after line 102) in `src/collector/curation/youtube_data_api_client.py`:

```python
    def move_item(self, playlist_id: str, item_id: str, video_id: str, position: int) -> None:
        # Reorder one playlistItem to an absolute index (50 quota units).
        # YouTube shifts the other items to accommodate the new position.
        body = {
            "id": item_id,
            "snippet": {
                "playlistId": playlist_id,
                "resourceId": {"kind": "youtube#video", "videoId": video_id},
                "position": position,
            },
        }
        self._request(
            "PUT", f"{_BASE}/playlistItems",
            params={"part": "snippet"}, json_body=body,
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `/Users/roman/Projects/clouder-projects/clouder-core/.venv/bin/pytest tests/unit/test_youtube_data_api_client.py::test_move_item_puts_with_position -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/collector/curation/youtube_data_api_client.py tests/unit/test_youtube_data_api_client.py
git commit -m "feat(ytmusic): add move_item to reorder playlist items"
```

---

## Task 3: Reorder sync in publish service

**Files:**
- Modify: `src/collector/curation/ytmusic_publish_service.py` (the `else` branch, lines 120-134, + new helper)
- Test: `tests/unit/test_ytmusic_publish_service.py` (extend `FakeClient`, add tests)

- [ ] **Step 1: Extend `FakeClient` in the test file**

In `tests/unit/test_ytmusic_publish_service.py`, update `FakeClient` (lines 54-87) to record moves and to support a sequence of `get_existing_items` results (so a post-add re-fetch can differ from the first read). Replace the `__init__`, `get_existing_items`, and add `move_item`:

```python
class FakeClient:
    def __init__(self, *, create_ret="PLnew", edit_raises=None, cover_raises=None,
                 existing=None, existing_seq=None):
        self.create_ret = create_ret
        self.edit_raises = edit_raises
        self.cover_raises = cover_raises
        self._existing = existing if existing is not None else [{"videoId": "old", "itemId": "i_old"}]
        self._existing_seq = list(existing_seq) if existing_seq is not None else None
        self.created = None
        self.edited = None
        self.added = []
        self.removed = []
        self.moves = []
        self.cover = None

    def create_playlist(self, *, name, description, privacy):
        self.created = (name, description, privacy)
        return self.create_ret

    def set_cover(self, playlist_id, image_bytes):
        if self.cover_raises:
            raise self.cover_raises
        self.cover = (playlist_id, image_bytes)

    def edit_meta(self, *, playlist_id, name, description, privacy):
        if self.edit_raises:
            raise self.edit_raises
        self.edited = (playlist_id, name, description, privacy)

    def get_existing_items(self, playlist_id):
        if self._existing_seq:
            return list(self._existing_seq.pop(0))
        return list(self._existing)

    def add_items(self, playlist_id, video_ids):
        self.added.append((playlist_id, list(video_ids)))

    def remove_items(self, playlist_id, items):
        self.removed.append((playlist_id, items))

    def move_item(self, playlist_id, item_id, video_id, position):
        self.moves.append((playlist_id, item_id, video_id, position))
```

- [ ] **Step 2: Write the failing reorder tests**

Add to `tests/unit/test_ytmusic_publish_service.py`:

```python
def test_pure_reorder_emits_moves():
    pl = FakePlaylist(id="p", name="N", description=None, is_public=True, ytmusic_playlist_id="PLold")
    rows = [FakeTrackRow("t1", "T1"), FakeTrackRow("t2", "T2")]
    statuses = {"t1": _matched("v1"), "t2": _matched("v2")}
    # YouTube currently has v2 then v1; desired is v1 then v2.
    client = FakeClient(existing=[{"videoId": "v2", "itemId": "i2"}, {"videoId": "v1", "itemId": "i1"}])
    svc = YtmusicPublishService(repo=FakeRepo(pl, rows, statuses), ytmusic_client=client, now=_now)
    svc.publish(user_id="u", playlist_id="p", confirm_overwrite=True)
    # Same membership -> no add/remove; one move puts v1 at index 0.
    assert client.removed == []
    assert client.added == []
    assert client.moves == [("PLold", "i1", "v1", 0)]


def test_correct_order_emits_no_moves():
    pl = FakePlaylist(id="p", name="N", description=None, is_public=True, ytmusic_playlist_id="PLold")
    rows = [FakeTrackRow("t1", "T1"), FakeTrackRow("t2", "T2")]
    statuses = {"t1": _matched("v1"), "t2": _matched("v2")}
    client = FakeClient(existing=[{"videoId": "v1", "itemId": "i1"}, {"videoId": "v2", "itemId": "i2"}])
    svc = YtmusicPublishService(repo=FakeRepo(pl, rows, statuses), ytmusic_client=client, now=_now)
    svc.publish(user_id="u", playlist_id="p", confirm_overwrite=True)
    assert client.moves == []


def test_membership_change_then_reorder_refetches_and_moves():
    pl = FakePlaylist(id="p", name="N", description=None, is_public=True, ytmusic_playlist_id="PLold")
    rows = [FakeTrackRow("t3", "T3"), FakeTrackRow("t1", "T1")]
    statuses = {"t3": _matched("v3"), "t1": _matched("v1")}
    # First read: v1 + v2. Desired: v3 then v1 -> remove v2, add v3.
    # Re-fetch after add: YouTube appended v3 at the end (new itemId i3).
    pre = [{"videoId": "v1", "itemId": "i1"}, {"videoId": "v2", "itemId": "i2"}]
    post = [{"videoId": "v1", "itemId": "i1"}, {"videoId": "v3", "itemId": "i3"}]
    client = FakeClient(existing_seq=[pre, post])
    svc = YtmusicPublishService(repo=FakeRepo(pl, rows, statuses), ytmusic_client=client, now=_now)
    svc.publish(user_id="u", playlist_id="p", confirm_overwrite=True)
    assert client.removed == [("PLold", ["i2"])]
    assert client.added == [("PLold", ["v3"])]
    # v3 must move to index 0; v1 then falls into place at index 1.
    assert client.moves == [("PLold", "i3", "v3", 0)]
```

- [ ] **Step 3: Run the reorder tests to verify they fail**

Run: `/Users/roman/Projects/clouder-projects/clouder-core/.venv/bin/pytest tests/unit/test_ytmusic_publish_service.py -q -k "reorder or correct_order"`
Expected: FAIL (`client.moves` is empty — no reorder logic yet).

- [ ] **Step 4: Implement the reorder pass + helper**

In `src/collector/curation/ytmusic_publish_service.py`, replace the `else` branch (lines 120-134) with membership-by-set diff followed by a reorder pass:

```python
        else:
            # Incremental sync — touch only the delta. Each playlistItems
            # insert/delete/update costs 50 YouTube quota units.
            existing_items = existing or []
            existing_vids = [it["videoId"] for it in existing_items]
            to_remove: list[str] = []
            to_add: list[str] = []
            if set(existing_vids) != set(video_ids):
                desired = set(video_ids)
                present = set(existing_vids)
                to_remove = [it["itemId"] for it in existing_items if it["videoId"] not in desired]
                to_add = [v for v in video_ids if v not in present]
                self._yt.remove_items(target_id, to_remove)
                self._yt.add_items(target_id, to_add)
            # Reorder pass. New items get YouTube-assigned itemIds, so re-fetch
            # once when membership changed; otherwise reuse what we already have.
            items_for_order = (
                self._yt.get_existing_items(target_id)
                if (to_add or to_remove)
                else existing_items
            )
            self._reorder_items(target_id, video_ids, items_for_order)
```

Then add the helper method to the `YtmusicPublishService` class (e.g. directly after `publish`):

```python
    def _reorder_items(self, target_id: str, desired_vids: list[str], items: list[dict]) -> None:
        """Move only out-of-place items so YouTube order matches desired_vids.
        Selection-style: walk desired left-to-right; if the slot already holds
        the right video, skip; otherwise move the matching item to that index.
        ``work`` mirrors YouTube's post-move order so positions stay correct."""
        work = [(it["videoId"], it["itemId"]) for it in items]
        for i, vid in enumerate(desired_vids):
            if i < len(work) and work[i][0] == vid:
                continue
            j = next((k for k in range(i, len(work)) if work[k][0] == vid), None)
            if j is None:
                continue  # not present (e.g. stale read) — nothing to move
            moved = work.pop(j)
            work.insert(i, moved)
            self._yt.move_item(target_id, moved[1], moved[0], i)
```

- [ ] **Step 5: Run the service tests to verify pass + no regression**

Run: `/Users/roman/Projects/clouder-projects/clouder-core/.venv/bin/pytest tests/unit/test_ytmusic_publish_service.py -q`
Expected: PASS — new reorder tests green AND the existing `test_republish_*`, `test_cover_*`, orphan/error tests still green (they don't assert `moves` and their membership diffs are unchanged).

- [ ] **Step 6: Commit**

```bash
git add src/collector/curation/ytmusic_publish_service.py tests/unit/test_ytmusic_publish_service.py
git commit -m "fix(ytmusic): sync track order on republish via minimal moves"
```

---

## Task 4: Flag ytmusic republish on reorder

**Files:**
- Modify: `src/collector/curation/playlists_repository.py` (`_mark_dirty_if_published`, lines 1090-1098)
- Test: `tests/unit/test_playlists_repository.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/unit/test_playlists_repository.py` (mirrors the capture style of `test_reorder_accepts_permutation_and_emits_updates` at line 327). It asserts the dirty-mark step emits a ytmusic-gated UPDATE.

```python
def test_reorder_marks_ytmusic_needs_republish() -> None:
    api = MagicMock()
    api.transaction.return_value.__enter__.return_value = "tx"
    api.transaction.return_value.__exit__.return_value = False
    sqls: list[str] = []

    def _execute(sql, params=None, transaction_id=None):
        sqls.append(sql)
        if "SELECT 1 AS ok FROM playlists" in sql:
            return [{"ok": 1}]
        if "SELECT track_id FROM playlist_tracks" in sql:
            return [{"track_id": "t-1"}, {"track_id": "t-2"}]
        return []

    api.execute.side_effect = _execute
    api.batch_execute.side_effect = lambda *a, **k: None
    repo = PlaylistsRepository(api)
    repo.reorder_tracks(
        user_id="u-1", playlist_id="p-1",
        ordered_track_ids=["t-2", "t-1"], now=_utc(),
    )
    joined = " | ".join(sqls)
    # Spotify dirty-mark preserved...
    assert "needs_republish = TRUE" in joined
    assert "spotify_playlist_id IS NOT NULL" in joined
    # ...and ytmusic dirty-mark added.
    assert "ytmusic_needs_republish = TRUE" in joined
    assert "ytmusic_playlist_id IS NOT NULL" in joined
```

- [ ] **Step 2: Run test to verify it fails**

Run: `/Users/roman/Projects/clouder-projects/clouder-core/.venv/bin/pytest tests/unit/test_playlists_repository.py::test_reorder_marks_ytmusic_needs_republish -v`
Expected: FAIL — `ytmusic_needs_republish` UPDATE is not emitted.

- [ ] **Step 3: Implement the ytmusic dirty-mark**

In `src/collector/curation/playlists_repository.py`, extend `_mark_dirty_if_published` (lines 1090-1098) with a second UPDATE. Keep them separate because the two targets use different flag columns and gates:

```python
    def _mark_dirty_if_published(
        self, playlist_id: str, now: datetime, tx_id: str
    ) -> None:
        self._data_api.execute(
            "UPDATE playlists SET needs_republish = TRUE, updated_at = :now "
            "WHERE id = :id AND spotify_playlist_id IS NOT NULL",
            {"id": playlist_id, "now": now},
            transaction_id=tx_id,
        )
        self._data_api.execute(
            "UPDATE playlists SET ytmusic_needs_republish = TRUE, updated_at = :now "
            "WHERE id = :id AND ytmusic_playlist_id IS NOT NULL",
            {"id": playlist_id, "now": now},
            transaction_id=tx_id,
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `/Users/roman/Projects/clouder-projects/clouder-core/.venv/bin/pytest tests/unit/test_playlists_repository.py -q`
Expected: PASS — new test green and existing reorder/dirty tests (`test_reorder_accepts_permutation_and_emits_updates`, `test_set_cover_updates_row_and_marks_dirty`) still green.

- [ ] **Step 5: Commit**

```bash
git add src/collector/curation/playlists_repository.py tests/unit/test_playlists_repository.py
git commit -m "fix(ytmusic): flag ytmusic republish after track reorder"
```

---

## Task 5: Full regression run

**Files:** none (verification only)

- [ ] **Step 1: Run the full unit suite**

Run: `/Users/roman/Projects/clouder-projects/clouder-core/.venv/bin/pytest tests/unit -q`
Expected: PASS, no regressions.

- [ ] **Step 2: Run the curation/ytmusic-touching tests explicitly as a focused check**

Run: `/Users/roman/Projects/clouder-projects/clouder-core/.venv/bin/pytest tests/unit/test_youtube_data_api_client.py tests/unit/test_ytmusic_publish_service.py tests/unit/test_playlists_repository.py -q`
Expected: PASS.

- [ ] **Step 3: No commit** (verification task — nothing changed). If the suite revealed a regression, fix it in the owning task and re-run.

---

## Self-review notes (already reconciled)

- **Spec coverage:** Fix 1 (cover) → Task 1. Fix 2 (reorder) → Tasks 2-3. Fix 3 (dirty flag) → Task 4. Quota/test sections → covered by the per-task tests and Task 5.
- **Behavioral change to watch:** the membership gate in `publish` changes from list-compare (`existing_vids != video_ids`) to set-compare (`set(...) != set(...)`). This is intentional — a pure reorder must NOT enter the add/remove branch; it is handled by the reorder pass instead. Existing service tests don't cover a same-set/different-order case, so none regress.
- **Type consistency:** `move_item(playlist_id, item_id, video_id, position)` signature is identical in the client, the `FakeClient`, and the `_reorder_items` caller. `_reorder_items` consumes `[{"videoId","itemId"}]` dicts — the exact shape `get_existing_items` returns.
- **Out of scope (per spec):** i18n cover-failure text, quota backoff/retry, bulk endpoints. No frontend or infra changes.

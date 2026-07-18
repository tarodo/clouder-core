# Spotify Import: Artist Fix + Playlist Mirror — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Spotify-imported tracks reliably get a YouTube link (by persisting their artists), and add a "import a whole Spotify playlist as a new mirror playlist" feature.

**Architecture:** The YouTube (YT Music) search is the existing `vendor_match` SQS pipeline; it silently drops imported tracks because they have no artist (import never wrote artists → `fetch_unmatched_match_inputs` returns empty artist → `VendorMatchMessage` validation rejects it). Fix: persist artists on import via a new batched write path `import_tracks_batch`, used by both single-track import and a new whole-playlist import handler. The playlist handler reads a Spotify playlist (paginated) and creates a new clouder playlist mirroring its name. Everything runs synchronously in the curation Lambda with a 200-track cap; a one-off script backfills already-broken imports.

**Tech Stack:** Python 3 (serverless Lambda, Aurora **Data API only** — no psycopg), pydantic v2, pytest (unit = MagicMock Data API fake; integration = `lambda_handler` + fakes). Frontend: Vite + React 19 + Mantine 9 + TanStack Query + TypeScript, tests via vitest + MSW. Terraform for API Gateway routes.

## Global Constraints

- **Runtime DB is the Aurora Data API, never psycopg.** All repo SQL goes through `self._data_api.execute(...)` / `.batch_execute(...)` / `.transaction()`. Never `import psycopg` in any `src/collector/` path.
- **Data API forbids array bind params.** Build `IN (...)` lists parametrically (`:t0, :t1, …`); use `batch_execute(sql, parameter_sets, transaction_id=...)` for multi-row inserts. `datetime`/`date` params get their typeHint automatically — pass them directly.
- **A new API route lives in THREE places** or it 404s: `_ROUTE_TABLE` in `src/collector/curation_handler.py`, the `ROUTES` list in `scripts/generate_openapi.py`, and `local.curation_playlist_routes` in `infra/curation_routes_playlists.tf`.
- **`docs/api/openapi.yaml` is generated.** Regenerate with `PYTHONPATH=src .venv/bin/python scripts/generate_openapi.py`; the frontend CI diff-checks `frontend/src/api/schema.d.ts` against it.
- **`PYTHONPATH=src` for anything outside pytest** (`pytest.ini` sets `pythonpath = src` for the runner only). macOS `python` is unavailable — use `.venv/bin/python` for project scripts, `python3` for stdlib-only.
- **No pytest markers, no shared `conftest.py`.** Unit vs integration is by directory (`tests/unit/` vs `tests/integration/`). Copy the local `_event`/fixture helpers into new test files.
- **Commits:** Conventional Commits (`^(feat|fix|chore|docs|refactor|test|perf|build|ci|style|revert)(\(.+\))?!?: `), imperative subject ≤72 chars, no `Co-Authored-By`/AI-attribution trailer. Single-line `-m` is fine for these self-explanatory subjects. Never hand-wave — subjects below are ready to use.
- **`clouder_artists` has NO `spotify_id` column** — dedup artists by `normalized_name`. **`clouder_tracks` has no `label_id`** — label is out of scope (deferred).

---

## Phase 1 — Backend: persist artists on import (the fix)

### Task 1: `import_tracks_batch` repository method (batched import + artist persistence)

**Files:**
- Modify: `src/collector/curation/playlists_repository.py` (add `ImportTrackInput` dataclass near `MatchInput` ~line 179; add `import_tracks_batch` method near `upsert_imported_track` ~line 846)
- Test: `tests/unit/test_playlists_repository.py`

**Interfaces:**
- Produces: `ImportTrackInput(spotify_id: str, title: str, isrc: str | None, length_ms: int | None, artists: list[str])` (frozen dataclass) and `PlaylistsRepository.import_tracks_batch(*, user_id: str, tracks: list[ImportTrackInput], now: datetime) -> list[str]` returning one `clouder_tracks.id` per input, in input order.
- Consumes: `self._data_api` (`execute`, `batch_execute`, `transaction`); `normalize_text` (already imported at `playlists_repository.py:17`); `uuid` (already imported at line 10).

- [ ] **Step 1: Write the failing tests**

Add to `tests/unit/test_playlists_repository.py`:

```python
from collector.curation.playlists_repository import ImportTrackInput


def _batch_data_api() -> MagicMock:
    """Data API fake that records execute/batch_execute calls."""
    api = MagicMock()
    api.transaction.return_value.__enter__.return_value = "tx"
    api.transaction.return_value.__exit__.return_value = False
    api.executed: list[tuple[str, dict]] = []
    api.batched: list[tuple[str, list[dict]]] = []

    def _execute(sql, params=None, transaction_id=None):
        api.executed.append((sql, params or {}))
        # No existing tracks / artists by default.
        return []

    def _batch(sql, parameter_sets, transaction_id=None):
        api.batched.append((sql, list(parameter_sets)))

    api.execute.side_effect = _execute
    api.batch_execute.side_effect = _batch
    return api


def test_import_tracks_batch_inserts_new_track_and_artists() -> None:
    api = _batch_data_api()
    repo = PlaylistsRepository(api)
    ids = repo.import_tracks_batch(
        user_id="u-1",
        tracks=[
            ImportTrackInput(
                spotify_id="spt-a", title="Track A", isrc="ISRC1",
                length_ms=200_000, artists=["Guri", "Nu Zau"],
            )
        ],
        now=_utc(),
    )
    assert len(ids) == 1
    # New track inserted.
    track_ins = [b for b in api.batched if "INSERT INTO clouder_tracks" in b[0]]
    assert track_ins and track_ins[0][1][0]["spotify_id"] == "spt-a"
    assert track_ins[0][1][0]["origin"] == "spotify_user_import"
    # Both artists inserted (deduped by normalized_name).
    artist_ins = [b for b in api.batched if "INSERT INTO clouder_artists" in b[0]]
    assert artist_ins and len(artist_ins[0][1]) == 2
    names = {r["normalized_name"] for r in artist_ins[0][1]}
    assert names == {"guri", "nu zau"}
    # Links created with role 'main'.
    link_ins = [b for b in api.batched if "INSERT INTO clouder_track_artists" in b[0]]
    assert link_ins and all(r["role"] == "main" for r in link_ins[0][1])
    # Import marker written.
    imp_ins = [b for b in api.batched if "INSERT INTO user_imported_tracks" in b[0]]
    assert imp_ins and imp_ins[0][1][0] == {
        "user_id": "u-1", "track_id": ids[0], "now": _utc(),
    }


def test_import_tracks_batch_reuses_existing_and_skips_artist_write() -> None:
    api = MagicMock()
    api.transaction.return_value.__enter__.return_value = "tx"
    api.transaction.return_value.__exit__.return_value = False
    batched: list[str] = []

    def _execute(sql, params=None, transaction_id=None):
        if "SELECT spotify_id, id FROM clouder_tracks" in sql:
            return [{"spotify_id": "spt-a", "id": "existing-1"}]
        return []

    def _batch(sql, parameter_sets, transaction_id=None):
        batched.append(sql)

    api.execute.side_effect = _execute
    api.batch_execute.side_effect = _batch
    repo = PlaylistsRepository(api)
    ids = repo.import_tracks_batch(
        user_id="u-1",
        tracks=[ImportTrackInput(
            spotify_id="spt-a", title="Track A", isrc=None,
            length_ms=None, artists=["Guri"],
        )],
        now=_utc(),
    )
    assert ids == ["existing-1"]
    # Existing track → no new clouder_tracks / clouder_artists / links.
    assert not any("INSERT INTO clouder_tracks" in s for s in batched)
    assert not any("INSERT INTO clouder_artists" in s for s in batched)
    assert not any("INSERT INTO clouder_track_artists" in s for s in batched)
    # But the import marker is still written.
    assert any("INSERT INTO user_imported_tracks" in s for s in batched)


def test_import_tracks_batch_empty_returns_empty() -> None:
    api = MagicMock()
    repo = PlaylistsRepository(api)
    assert repo.import_tracks_batch(user_id="u-1", tracks=[], now=_utc()) == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_playlists_repository.py -k import_tracks_batch -v`
Expected: FAIL — `ImportError: cannot import name 'ImportTrackInput'`.

- [ ] **Step 3: Add the dataclass and method**

In `src/collector/curation/playlists_repository.py`, after the `MatchInput` dataclass (~line 185) add:

```python
@dataclass(frozen=True)
class ImportTrackInput:
    spotify_id: str
    title: str
    isrc: str | None
    length_ms: int | None
    artists: list[str]  # ordered display names; may be empty
```

Add this method to `PlaylistsRepository` (place it next to `upsert_imported_track`):

```python
    def import_tracks_batch(
        self,
        *,
        user_id: str,
        tracks: list[ImportTrackInput],
        now: datetime,
    ) -> list[str]:
        """Batch-import Spotify tracks; return one clouder_tracks.id per input.

        One transaction, batched writes:
          - dedup existing rows by spotify_id (reuse id),
          - insert new clouder_tracks,
          - persist artists for NEW tracks only (dedup clouder_artists by
            normalized_name) and link clouder_track_artists (role='main'),
          - mark user_imported_tracks for every (user_id, track_id).

        Artists are written only for freshly-inserted tracks; a spotify_id
        dedup hit reuses the existing row untouched.
        """
        if not tracks:
            return []
        with self._data_api.transaction() as tx_id:
            # 1. Dedup existing tracks by spotify_id.
            unique_sids = list({t.spotify_id for t in tracks})
            sid_ph = ", ".join(f":s{i}" for i in range(len(unique_sids)))
            sid_params = {f"s{i}": sid for i, sid in enumerate(unique_sids)}
            existing_rows = self._data_api.execute(
                f"SELECT spotify_id, id FROM clouder_tracks "
                f"WHERE spotify_id IN ({sid_ph})",
                sid_params,
                transaction_id=tx_id,
            )
            id_by_sid: dict[str, str] = {}
            for r in existing_rows:
                id_by_sid.setdefault(r["spotify_id"], r["id"])

            # 2. Insert new clouder_tracks (one row per new spotify_id).
            new_track_rows: list[dict] = []
            for t in tracks:
                if t.spotify_id in id_by_sid:
                    continue
                new_id = str(uuid.uuid4())
                id_by_sid[t.spotify_id] = new_id
                new_track_rows.append({
                    "id": new_id,
                    "title": t.title,
                    "normalized_title": normalize_text(t.title),
                    "isrc": t.isrc,
                    "length_ms": t.length_ms,
                    "spotify_id": t.spotify_id,
                    "origin": "spotify_user_import",
                    "now": now,
                })
            new_sids = {row["spotify_id"] for row in new_track_rows}
            if new_track_rows:
                self._data_api.batch_execute(
                    """
                    INSERT INTO clouder_tracks (
                        id, title, normalized_title, isrc, length_ms,
                        spotify_id, origin, created_at, updated_at
                    ) VALUES (
                        :id, :title, :normalized_title, :isrc, :length_ms,
                        :spotify_id, :origin, :now, :now
                    )
                    """,
                    new_track_rows,
                    transaction_id=tx_id,
                )

            # 3. Persist artists for NEW tracks only.
            name_by_norm: dict[str, str] = {}
            for t in tracks:
                if t.spotify_id not in new_sids:
                    continue
                for name in t.artists:
                    norm = normalize_text(name)
                    if norm:
                        name_by_norm.setdefault(norm, name.strip())
            if name_by_norm:
                norms = list(name_by_norm.keys())
                n_ph = ", ".join(f":n{i}" for i in range(len(norms)))
                n_params = {f"n{i}": nm for i, nm in enumerate(norms)}
                found = self._data_api.execute(
                    f"SELECT id, normalized_name FROM clouder_artists "
                    f"WHERE normalized_name IN ({n_ph})",
                    n_params,
                    transaction_id=tx_id,
                )
                artist_id_by_norm: dict[str, str] = {
                    r["normalized_name"]: r["id"] for r in found
                }
                new_artist_rows: list[dict] = []
                for norm, display in name_by_norm.items():
                    if norm in artist_id_by_norm:
                        continue
                    aid = str(uuid.uuid4())
                    artist_id_by_norm[norm] = aid
                    new_artist_rows.append({
                        "id": aid, "name": display,
                        "normalized_name": norm, "now": now,
                    })
                if new_artist_rows:
                    self._data_api.batch_execute(
                        """
                        INSERT INTO clouder_artists (
                            id, name, normalized_name, created_at, updated_at
                        ) VALUES (:id, :name, :normalized_name, :now, :now)
                        """,
                        new_artist_rows,
                        transaction_id=tx_id,
                    )
                link_rows: list[dict] = []
                for t in tracks:
                    if t.spotify_id not in new_sids:
                        continue
                    tid = id_by_sid[t.spotify_id]
                    seen: set[str] = set()
                    for name in t.artists:
                        norm = normalize_text(name)
                        if not norm:
                            continue
                        aid = artist_id_by_norm[norm]
                        if aid in seen:
                            continue
                        seen.add(aid)
                        link_rows.append({
                            "track_id": tid, "artist_id": aid, "role": "main",
                        })
                if link_rows:
                    self._data_api.batch_execute(
                        """
                        INSERT INTO clouder_track_artists (track_id, artist_id, role)
                        VALUES (:track_id, :artist_id, :role)
                        ON CONFLICT DO NOTHING
                        """,
                        link_rows,
                        transaction_id=tx_id,
                    )

            # 4. Mark user_imported_tracks for every resolved track.
            import_rows: list[dict] = []
            seen_tids: set[str] = set()
            for t in tracks:
                tid = id_by_sid[t.spotify_id]
                if tid in seen_tids:
                    continue
                seen_tids.add(tid)
                import_rows.append({"user_id": user_id, "track_id": tid, "now": now})
            self._data_api.batch_execute(
                """
                INSERT INTO user_imported_tracks (user_id, track_id, imported_at)
                VALUES (:user_id, :track_id, :now)
                ON CONFLICT DO NOTHING
                """,
                import_rows,
                transaction_id=tx_id,
            )

            # 5. Return ids in input order.
            return [id_by_sid[t.spotify_id] for t in tracks]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/test_playlists_repository.py -k import_tracks_batch -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add src/collector/curation/playlists_repository.py tests/unit/test_playlists_repository.py
git commit -m "feat(curation): batched import_tracks_batch persists artists"
```

---

### Task 2: Route single-track import through `import_tracks_batch` (delivers the fix)

**Files:**
- Modify: `src/collector/curation_handler.py` (`_handle_import_spotify` ~line 1085; add import of `ImportTrackInput` and `parse_spotify_playlist_ref` will come later — here just `ImportTrackInput`)
- Modify: `src/collector/curation/playlists_repository.py` (delete now-unused `upsert_imported_track`, ~lines 846-910)
- Modify: `tests/unit/test_playlists_repository.py` (delete the two `test_upsert_imported_track_*` tests)
- Modify: `tests/integration/test_playlists_flow.py` (add `import_tracks_batch` to `FakePlaylistsRepo`; delete its now-unused `upsert_imported_track`)

**Interfaces:**
- Consumes: `ImportTrackInput`, `import_tracks_batch` from Task 1; `SpotifyTrackPayload.artists` (tuple of `SpotifyArtistRef` with `.name`).
- Produces: unchanged `_handle_import_spotify` response shape (`{added: [{track_id, spotify_id, title}], skipped, position_after, correlation_id}`).

- [ ] **Step 1: Add `import_tracks_batch` to the integration fake, write the failing artist assertion**

In `tests/integration/test_playlists_flow.py`, add this method to `FakePlaylistsRepo` (near `upsert_imported_track`, ~line 286) and record artist writes:

```python
    def import_tracks_batch(self, *, user_id, tracks, now) -> list[str]:
        ids: list[str] = []
        for t in tracks:
            existing = next(
                (tid for tid, meta in self.canonical_tracks.items()
                 if meta.get("spotify_id") == t.spotify_id),
                None,
            )
            if existing is not None:
                tid = existing
            else:
                tid = f"t-{len(self.canonical_tracks) + 1}"
                self.canonical_tracks[tid] = {
                    "spotify_id": t.spotify_id, "title": t.title,
                    "artists": list(t.artists),
                }
            self.imports.add((user_id, tid))
            ids.append(tid)
        return ids
```

Extend the existing `test_import_spotify_then_publish` (or add a focused test) to assert artists are threaded — update the `fake_spotify_client.get_track.side_effect` to return an artist and assert it lands:

```python
def test_import_spotify_persists_artists(fake_repo, fake_s3, fake_spotify_client):
    fake_spotify_client.get_track.side_effect = lambda spotify_id: SimpleNamespace(
        id=spotify_id, name=f"Imported {spotify_id}", duration_ms=200_000,
        isrc=None, artists=(SimpleNamespace(name="Guri"),),
    )
    resp = lambda_handler(
        _event(method="POST", route="/playlists", body={"name": "Set"}), None,
    )
    pid = json.loads(resp["body"])["id"]
    resp = lambda_handler(
        _event(
            method="POST", route="/playlists/{id}/tracks/import-spotify",
            body={"spotify_refs": ["spotify:track:5xkAVrKKnHeBHb1Mqt6wEt"]},
            path_params={"id": pid},
        ),
        None,
    )
    assert resp["statusCode"] == 201
    tid = json.loads(resp["body"])["added"][0]["track_id"]
    assert fake_repo.canonical_tracks[tid]["artists"] == ["Guri"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/integration/test_playlists_flow.py -k persists_artists -v`
Expected: FAIL — handler still calls `upsert_imported_track` (no artists threaded), `canonical_tracks[tid]["artists"]` missing/`KeyError`.

- [ ] **Step 3: Rewrite the handler's import loop**

In `src/collector/curation_handler.py`, ensure `ImportTrackInput` is imported from `collector.curation.playlists_repository` (add it to whichever import line already pulls from that module — `PlaylistsRepository` is imported from it near line 55 — or add a dedicated `from collector.curation.playlists_repository import ImportTrackInput`). Then replace the per-track `upsert_imported_track` loop inside `_handle_import_spotify` (the `for sid in spotify_ids:` block through the `added_details.append(...)`) with:

```python
    sp_client = _build_spotify_user_client(user_id, correlation_id)

    payloads = []
    for sid in spotify_ids:
        try:
            payloads.append(sp_client.get_track(sid))
        except SpotifyNotFoundError as exc:
            skipped.append({"ref": sid, "reason": "not_found"})
            log_event(
                "WARNING", "playlist_spotify_import_failed",
                correlation_id=correlation_id, user_id=user_id,
                spotify_id=sid, reason=str(exc),
            )

    inputs = [
        ImportTrackInput(
            spotify_id=p.id, title=p.name, isrc=p.isrc,
            length_ms=p.duration_ms,
            artists=[a.name for a in p.artists if a.name],
        )
        for p in payloads
    ]
    track_ids = repo.import_tracks_batch(
        user_id=user_id, tracks=inputs, now=utc_now(),
    )
    added_details = [
        {"track_id": tid, "spotify_id": p.id, "title": p.name}
        for tid, p in zip(track_ids, payloads)
    ]
```

- [ ] **Step 4: Delete the now-unused `upsert_imported_track`**

Remove `upsert_imported_track` from `src/collector/curation/playlists_repository.py` (~846-910), delete `test_upsert_imported_track_uses_existing_*` and `test_upsert_imported_track_inserts_new_*` from `tests/unit/test_playlists_repository.py`, and delete `upsert_imported_track` from `FakePlaylistsRepo` in `tests/integration/test_playlists_flow.py`.

- [ ] **Step 5: Run the affected suites**

Run: `pytest tests/integration/test_playlists_flow.py tests/unit/test_playlists_repository.py -q`
Expected: PASS (import flow works, artists persisted, no reference to `upsert_imported_track`).

- [ ] **Step 6: Commit**

```bash
git add src/collector/curation_handler.py src/collector/curation/playlists_repository.py tests/unit/test_playlists_repository.py tests/integration/test_playlists_flow.py
git commit -m "fix(curation): thread Spotify artists through import so ytmusic runs"
```

---

## Phase 2 — Backend: read a Spotify playlist

### Task 3: `get_playlist_name` + `get_playlist_tracks` on `SpotifyUserClient`

**Files:**
- Modify: `src/collector/curation/spotify_user_client.py`
- Test: `tests/unit/test_spotify_user_client.py`

**Interfaces:**
- Produces: `SpotifyUserClient.get_playlist_name(spotify_playlist_id: str) -> str`; `SpotifyUserClient.get_playlist_tracks(spotify_playlist_id: str, *, limit: int) -> list[SpotifyTrackPayload]` (skips null/local/episode/id-less items, paginates 100/page, stops at `limit` or when `next` is null); module helper `_track_payload(body: dict) -> SpotifyTrackPayload`.
- Consumes: `self._request`, `_BASE`, `SpotifyTrackPayload`, `SpotifyArtistRef`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/unit/test_spotify_user_client.py`:

```python
def test_get_playlist_name() -> None:
    session = MagicMock()
    session.request.return_value = _Resp(200, {"name": "My Set"})
    client = _client(session)
    assert client.get_playlist_name("pl-1") == "My Set"
    _, kwargs = session.request.call_args
    assert "playlists/pl-1" in kwargs.get("url")


def test_get_playlist_tracks_paginates_and_filters() -> None:
    page1 = _Resp(200, {
        "items": [
            {"track": {"id": "a", "name": "A", "duration_ms": 1000,
                       "external_ids": {"isrc": "I1"},
                       "artists": [{"id": "x", "name": "Art"}]}},
            {"track": None},                              # removed → skip
            {"track": {"id": None, "is_local": True, "name": "Local"}},  # skip
            {"track": {"id": "e", "type": "episode", "name": "Ep"}},     # skip
        ],
        "next": "http://next",
    })
    page2 = _Resp(200, {
        "items": [
            {"track": {"id": "b", "name": "B", "duration_ms": 2000,
                       "external_ids": {}, "artists": []}},
        ],
        "next": None,
    })
    session = MagicMock()
    session.request.side_effect = [page1, page2]
    client = _client(session)
    tracks = client.get_playlist_tracks("pl-1", limit=500)
    assert [t.id for t in tracks] == ["a", "b"]
    assert tracks[0].isrc == "I1"
    assert tracks[0].artists[0].name == "Art"


def test_get_playlist_tracks_respects_limit() -> None:
    page = _Resp(200, {
        "items": [
            {"track": {"id": "a", "name": "A", "duration_ms": 1, "external_ids": {}, "artists": []}},
            {"track": {"id": "b", "name": "B", "duration_ms": 1, "external_ids": {}, "artists": []}},
            {"track": {"id": "c", "name": "C", "duration_ms": 1, "external_ids": {}, "artists": []}},
        ],
        "next": "http://next",
    })
    session = MagicMock()
    session.request.return_value = page
    client = _client(session)
    tracks = client.get_playlist_tracks("pl-1", limit=2)
    assert [t.id for t in tracks] == ["a", "b"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_spotify_user_client.py -k playlist -v`
Expected: FAIL — `AttributeError: 'SpotifyUserClient' object has no attribute 'get_playlist_name'`.

- [ ] **Step 3: Implement the methods + shared extractor**

In `src/collector/curation/spotify_user_client.py`, add a module-level helper after the dataclasses (~line 49):

```python
def _track_payload(body: dict) -> SpotifyTrackPayload:
    return SpotifyTrackPayload(
        id=body["id"],
        name=body.get("name") or "",
        duration_ms=body.get("duration_ms"),
        isrc=(body.get("external_ids") or {}).get("isrc"),
        artists=tuple(
            SpotifyArtistRef(
                id=a.get("id") or "", name=a.get("name") or "",
                spotify_id=a.get("id"),
            )
            for a in (body.get("artists") or [])
        ),
    )
```

Refactor `get_track` to reuse it:

```python
    def get_track(self, spotify_id: str) -> SpotifyTrackPayload:
        return _track_payload(self._request("GET", f"{_BASE}/tracks/{spotify_id}"))
```

Add the two new methods:

```python
    def get_playlist_name(self, spotify_playlist_id: str) -> str:
        body = self._request(
            "GET", f"{_BASE}/playlists/{spotify_playlist_id}?fields=name",
        )
        return body.get("name") or ""

    def get_playlist_tracks(
        self, spotify_playlist_id: str, *, limit: int,
    ) -> list[SpotifyTrackPayload]:
        out: list[SpotifyTrackPayload] = []
        offset = 0
        page_size = 100
        while len(out) < limit:
            body = self._request(
                "GET",
                f"{_BASE}/playlists/{spotify_playlist_id}/tracks"
                f"?limit={page_size}&offset={offset}",
            )
            items = body.get("items") or []
            for item in items:
                track = item.get("track")
                if not track:
                    continue
                if track.get("is_local"):
                    continue
                if track.get("type") == "episode":
                    continue
                if not track.get("id"):
                    continue
                out.append(_track_payload(track))
                if len(out) >= limit:
                    break
            if body.get("next") is None:
                break
            offset += page_size
        return out
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/test_spotify_user_client.py -k "playlist or get_track" -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/collector/curation/spotify_user_client.py tests/unit/test_spotify_user_client.py
git commit -m "feat(curation): read Spotify playlist name and tracks (paginated)"
```

---

### Task 4: `parse_spotify_playlist_ref` + `MAX_IMPORT_PLAYLIST_TRACKS`

**Files:**
- Modify: `src/collector/curation/playlists_service.py`
- Test: `tests/unit/test_playlists_service.py`

**Interfaces:**
- Produces: `parse_spotify_playlist_ref(ref: str) -> str` (raises `InvalidSpotifyRefError`); constant `MAX_IMPORT_PLAYLIST_TRACKS = 200`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/unit/test_playlists_service.py` (extend the import from `playlists_service` to include `parse_spotify_playlist_ref`, `MAX_IMPORT_PLAYLIST_TRACKS`):

```python
def test_parse_playlist_uri_form() -> None:
    assert parse_spotify_playlist_ref(
        "spotify:playlist:37i9dQZF1DXcBWIGoYBM5M"
    ) == "37i9dQZF1DXcBWIGoYBM5M"


def test_parse_playlist_url_form() -> None:
    assert parse_spotify_playlist_ref(
        "https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M?si=x"
    ) == "37i9dQZF1DXcBWIGoYBM5M"


def test_parse_playlist_bare_id() -> None:
    assert parse_spotify_playlist_ref("37i9dQZF1DXcBWIGoYBM5M") == "37i9dQZF1DXcBWIGoYBM5M"


def test_parse_playlist_rejects_track_uri() -> None:
    with pytest.raises(InvalidSpotifyRefError):
        parse_spotify_playlist_ref("spotify:track:5xkAVrKKnHeBHb1Mqt6wEt")


def test_max_import_playlist_tracks_is_200() -> None:
    assert MAX_IMPORT_PLAYLIST_TRACKS == 200
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_playlists_service.py -k "playlist_ref or import_playlist" -v`
Expected: FAIL — `ImportError`.

- [ ] **Step 3: Implement**

In `src/collector/curation/playlists_service.py`, add the constant near `MAX_IMPORT_REFS_PER_REQUEST` (~line 20):

```python
MAX_IMPORT_PLAYLIST_TRACKS = 200
```

Add the regexes near the track ones (~line 30):

```python
_PLAYLIST_URI_RE = re.compile(r"^spotify:playlist:([0-9A-Za-z]{22})$")
_PLAYLIST_URL_RE = re.compile(
    r"^https?://open\.spotify\.com/playlist/([0-9A-Za-z]{22})(?:\?.*)?$"
)
```

Add the function after `parse_spotify_ref`:

```python
def parse_spotify_playlist_ref(ref: str) -> str:
    """Return the 22-char Spotify playlist ID or raise InvalidSpotifyRefError.

    Accepts: spotify:playlist:<id> | https://open.spotify.com/playlist/<id>[?q] | <id>
    """
    if not isinstance(ref, str):
        raise InvalidSpotifyRefError("Spotify ref must be a string")
    cleaned = ref.strip()
    if not cleaned:
        raise InvalidSpotifyRefError("Spotify ref must be non-empty")
    m = _PLAYLIST_URI_RE.match(cleaned)
    if m:
        return m.group(1)
    m = _PLAYLIST_URL_RE.match(cleaned)
    if m:
        return m.group(1)
    if _BASE62_RE.match(cleaned):
        return cleaned
    raise InvalidSpotifyRefError(f"Unrecognized Spotify playlist ref: {cleaned!r}")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/test_playlists_service.py -k "playlist_ref or import_playlist" -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/collector/curation/playlists_service.py tests/unit/test_playlists_service.py
git commit -m "feat(curation): parse Spotify playlist refs, cap 200 tracks"
```

---

## Phase 3 — Backend: the new import-playlist route

### Task 5: `_handle_import_spotify_playlist` handler + route table entry

**Files:**
- Modify: `src/collector/curation/schemas.py` (add `ImportSpotifyPlaylistIn` after `ImportSpotifyTracksIn` ~line 135)
- Modify: `src/collector/curation_handler.py` (add handler; register in `_ROUTE_TABLE`; extend imports)
- Test: `tests/integration/test_playlists_flow.py`

**Interfaces:**
- Consumes: `parse_spotify_playlist_ref`, `MAX_IMPORT_PLAYLIST_TRACKS`, `MAX_NAME_LENGTH` (from `playlists_service`); `validate_playlist_name`, `normalize_playlist_name` (already imported); `repo.create`, `repo.import_tracks_batch`, `repo.append_tracks`; `sp_client.get_playlist_name`, `sp_client.get_playlist_tracks`; `_enqueue_ytmusic`.
- Produces: route `POST /playlists/import-spotify-playlist`; response `{playlist_id, name, imported, skipped, truncated, total, correlation_id}` with status 201.

- [ ] **Step 1: Write the failing integration test**

Add to `tests/integration/test_playlists_flow.py` (extend `fake_spotify_client` fixture to provide playlist methods, then a test). Add these defaults to the `fake_spotify_client` fixture body:

```python
    client.get_playlist_name.return_value = "Spotify Mix"
    client.get_playlist_tracks.return_value = [
        SimpleNamespace(id="spt-1", name="One", duration_ms=100, isrc=None,
                        artists=(SimpleNamespace(name="Guri"),)),
        SimpleNamespace(id="spt-2", name="Two", duration_ms=200, isrc=None,
                        artists=(SimpleNamespace(name="Nu Zau"),)),
    ]
```

New test:

```python
def test_import_spotify_playlist_creates_mirror(fake_repo, fake_s3, fake_spotify_client):
    resp = lambda_handler(
        _event(
            method="POST", route="/playlists/import-spotify-playlist",
            body={"spotify_ref": "https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M"},
        ),
        None,
    )
    assert resp["statusCode"] == 201
    body = json.loads(resp["body"])
    assert body["name"] == "Spotify Mix"
    assert body["imported"] == 2
    assert body["truncated"] is False
    assert body["total"] == 2
    # A new clouder playlist was created and both tracks appended.
    pid = body["playlist_id"]
    assert fake_repo.get(user_id="u1", playlist_id=pid) is not None
    assert sum(1 for (p, _t) in fake_repo.tracks if p == pid) == 2
    # Artists were persisted through the batch importer.
    assert any(m.get("artists") == ["Guri"] for m in fake_repo.canonical_tracks.values())


def test_import_spotify_playlist_name_override(fake_repo, fake_s3, fake_spotify_client):
    resp = lambda_handler(
        _event(
            method="POST", route="/playlists/import-spotify-playlist",
            body={"spotify_ref": "37i9dQZF1DXcBWIGoYBM5M", "name": "My Name"},
        ),
        None,
    )
    assert json.loads(resp["body"])["name"] == "My Name"


def test_import_spotify_playlist_rejects_bad_ref(fake_repo, fake_s3, fake_spotify_client):
    resp = lambda_handler(
        _event(
            method="POST", route="/playlists/import-spotify-playlist",
            body={"spotify_ref": "not-a-playlist"},
        ),
        None,
    )
    assert resp["statusCode"] == 400
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/integration/test_playlists_flow.py -k import_spotify_playlist -v`
Expected: FAIL — route unknown → 404 (handler + route entry not added yet).

- [ ] **Step 3: Add the request schema**

In `src/collector/curation/schemas.py`, after `ImportSpotifyTracksIn`:

```python
class ImportSpotifyPlaylistIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    spotify_ref: str = Field(..., min_length=1)
    name: str | None = Field(default=None, max_length=100)
```

- [ ] **Step 4: Add the handler and register the route**

In `src/collector/curation_handler.py`:
1. Add `ImportSpotifyPlaylistIn` to the `from .curation.schemas import (...)` block.
2. Add `parse_spotify_playlist_ref`, `MAX_IMPORT_PLAYLIST_TRACKS`, `MAX_NAME_LENGTH` to the existing `from .curation.playlists_service import (...)` block.
3. Add the handler (place it right after `_handle_import_spotify`):

```python
def _handle_import_spotify_playlist(event, repo, user_id, correlation_id):
    body = ImportSpotifyPlaylistIn.model_validate(_parse_body(event))
    try:
        playlist_sid = parse_spotify_playlist_ref(body.spotify_ref)
    except InvalidSpotifyRefError as exc:
        raise ValidationError(str(exc))

    sp_client = _build_spotify_user_client(user_id, correlation_id)
    sp_name = sp_client.get_playlist_name(playlist_sid)
    payloads = sp_client.get_playlist_tracks(
        playlist_sid, limit=MAX_IMPORT_PLAYLIST_TRACKS + 1,
    )
    truncated = len(payloads) > MAX_IMPORT_PLAYLIST_TRACKS
    if truncated:
        payloads = payloads[:MAX_IMPORT_PLAYLIST_TRACKS]

    name = (body.name or sp_name or "Imported playlist").strip()[:MAX_NAME_LENGTH]
    validate_playlist_name(name)
    normalized = normalize_playlist_name(name)
    if not normalized:
        raise ValidationError("Name must be non-empty")
    playlist_id = str(uuid.uuid4())
    repo.create(
        user_id=user_id, playlist_id=playlist_id, name=name,
        normalized_name=normalized, description=None, is_public=True,
        now=utc_now(),
    )

    inputs = [
        ImportTrackInput(
            spotify_id=p.id, title=p.name, isrc=p.isrc,
            length_ms=p.duration_ms,
            artists=[a.name for a in p.artists if a.name],
        )
        for p in payloads
    ]
    track_ids = repo.import_tracks_batch(
        user_id=user_id, tracks=inputs, now=utc_now(),
    )
    result = repo.append_tracks(
        user_id=user_id, playlist_id=playlist_id,
        track_ids=track_ids, now=utc_now(),
    )
    _enqueue_ytmusic(repo, result.added_track_ids, correlation_id)

    log_event(
        "INFO", "playlist_spotify_playlist_imported",
        correlation_id=correlation_id, user_id=user_id, playlist_id=playlist_id,
        imported=len(result.added_track_ids), truncated=truncated,
    )
    return _json_response(
        201,
        {
            "playlist_id": playlist_id,
            "name": name,
            "imported": len(result.added_track_ids),
            "skipped": len(result.skipped_duplicates),
            "truncated": truncated,
            "total": len(track_ids),
            "correlation_id": correlation_id,
        },
        correlation_id,
    )
```

4. Register in `_ROUTE_TABLE` (add alongside the other playlist routes, before `POST /playlists/{id}/tracks/import-spotify`):

```python
    "POST /playlists/import-spotify-playlist": (
        _handle_import_spotify_playlist, _playlists_factory,
    ),
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/integration/test_playlists_flow.py -k import_spotify_playlist -v`
Expected: PASS (3 tests).

- [ ] **Step 6: Commit**

```bash
git add src/collector/curation/schemas.py src/collector/curation_handler.py tests/integration/test_playlists_flow.py
git commit -m "feat(curation): import whole Spotify playlist as mirror playlist"
```

---

### Task 6: Register the route in infra + OpenAPI, regenerate schema

**Files:**
- Modify: `infra/curation_routes_playlists.tf` (append to `local.curation_playlist_routes`)
- Modify: `scripts/generate_openapi.py` (add a `ROUTES` entry)
- Regenerate: `docs/api/openapi.yaml`, `frontend/src/api/schema.d.ts`

**Interfaces:** none (config). This makes the route reachable in prod and typed on the frontend.

- [ ] **Step 1: Add the Terraform route string**

In `infra/curation_routes_playlists.tf`, add to the `local.curation_playlist_routes` list:

```hcl
    "POST /playlists/import-spotify-playlist",
```

- [ ] **Step 2: Add the OpenAPI ROUTES entry**

In `scripts/generate_openapi.py`, add to the `ROUTES` list (near the existing import-spotify entry ~line 3133):

```python
    {
        "method": "post",
        "path": "/playlists/import-spotify-playlist",
        "auth": AUTH,
        "summary": "Import a whole Spotify playlist as a new mirror playlist.",
        "description": (
            "Reads the Spotify playlist via the user's stored OAuth token "
            "(requires playlist-read-private/collaborative for private playlists), "
            "creates a new clouder playlist mirroring its name, imports up to 200 "
            "tracks (persisting artists), and enqueues YT Music matching."
        ),
        "requestBody": {
            "required": True,
            "content": {"application/json": {"schema": {
                "type": "object",
                "required": ["spotify_ref"],
                "properties": {
                    "spotify_ref": {
                        "type": "string",
                        "description": "Spotify playlist URL, URI, or bare id.",
                    },
                    "name": {
                        "type": "string",
                        "description": "Optional name override (defaults to the Spotify playlist name).",
                    },
                },
                "additionalProperties": False,
            }}},
        },
        "request_example": {"spotify_ref": "https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M"},
        "responses": {
            "201": _make_response(201, "Mirror playlist created; returns counts.", {"type": "object"}),
            "400": _error(400, "invalid_spotify_ref."),
            "404": _error(404, "playlist_not_found."),
            "409": _error(409, "playlist name already exists."),
            "412": _error(412, "spotify_not_authorized / spotify_scope_insufficient."),
            "502": _error(502, "spotify_upstream_error."),
            **COMMON_AUTH_ERRORS,
        },
    },
```

- [ ] **Step 3: Regenerate the OpenAPI doc and the frontend schema**

Run:
```bash
PYTHONPATH=src .venv/bin/python scripts/generate_openapi.py
cd frontend && pnpm run gen:api   # regenerates src/api/schema.d.ts from docs/api/openapi.yaml
```
(If the frontend script name differs, find it: `grep -n "schema.d.ts\|openapi" frontend/package.json`. The CI job that diff-checks the schema names the exact command.)
Expected: `docs/api/openapi.yaml` and `frontend/src/api/schema.d.ts` now contain `/playlists/import-spotify-playlist`.

- [ ] **Step 4: Verify the generator runs clean**

Run: `PYTHONPATH=src .venv/bin/python scripts/generate_openapi.py && echo OK`
Expected: `OK`, no diff on re-run.

- [ ] **Step 5: Commit**

```bash
git add infra/curation_routes_playlists.tf scripts/generate_openapi.py docs/api/openapi.yaml frontend/src/api/schema.d.ts
git commit -m "feat(api): register POST /playlists/import-spotify-playlist"
```

---

## Phase 4 — OAuth scopes

### Task 7: Add playlist-read scopes (enables private/collaborative playlists)

**Files:**
- Modify: `src/collector/auth_handler.py` (`SPOTIFY_SCOPES` ~line 59)
- Test: `tests/unit/` (add a small assertion; find the existing auth_handler test file with `grep -rl SPOTIFY_SCOPES tests/` or create `tests/unit/test_auth_scopes.py`)

**Interfaces:** none (constant change). Note: existing users must reconnect Spotify once (scope change requires re-consent). A token lacking the scope already surfaces as `SpotifyScopeInsufficientError` → 412 (handled by the generic `CurationError` catch).

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_auth_scopes.py`:

```python
from collector.auth_handler import SPOTIFY_SCOPES


def test_scopes_include_playlist_read() -> None:
    assert "playlist-read-private" in SPOTIFY_SCOPES
    assert "playlist-read-collaborative" in SPOTIFY_SCOPES
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_auth_scopes.py -v`
Expected: FAIL — scopes not present.

- [ ] **Step 3: Add the scopes**

In `src/collector/auth_handler.py`, update `SPOTIFY_SCOPES`:

```python
SPOTIFY_SCOPES = (
    "user-read-email user-read-private "
    "playlist-modify-public playlist-modify-private ugc-image-upload "
    "playlist-read-private playlist-read-collaborative "
    "streaming user-read-playback-state user-modify-playback-state"
)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_auth_scopes.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/collector/auth_handler.py tests/unit/test_auth_scopes.py
git commit -m "feat(auth): request Spotify playlist-read scopes for imports"
```

---

## Phase 5 — Frontend: import-playlist modal

### Task 8: `parseSpotifyPlaylistRef` helper + test

**Files:**
- Create: `frontend/src/features/playlists/lib/spotifyPlaylistRefParse.ts`
- Test: `frontend/src/features/playlists/lib/__tests__/spotifyPlaylistRefParse.test.ts`

**Interfaces:**
- Produces: `parseSpotifyPlaylistRef(input: string): string` (throws `InvalidSpotifyRefError` from the existing `../spotifyRefParse` module — reuse it).

- [ ] **Step 1: Write the failing test**

Create `frontend/src/features/playlists/lib/__tests__/spotifyPlaylistRefParse.test.ts`:

```ts
import { describe, it, expect } from 'vitest';
import { parseSpotifyPlaylistRef } from '../spotifyPlaylistRefParse';
import { InvalidSpotifyRefError } from '../spotifyRefParse';

describe('parseSpotifyPlaylistRef', () => {
  it('parses uri form', () => {
    expect(parseSpotifyPlaylistRef('spotify:playlist:37i9dQZF1DXcBWIGoYBM5M')).toBe(
      '37i9dQZF1DXcBWIGoYBM5M',
    );
  });
  it('parses url form with query', () => {
    expect(
      parseSpotifyPlaylistRef('https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M?si=x'),
    ).toBe('37i9dQZF1DXcBWIGoYBM5M');
  });
  it('parses bare id', () => {
    expect(parseSpotifyPlaylistRef('37i9dQZF1DXcBWIGoYBM5M')).toBe('37i9dQZF1DXcBWIGoYBM5M');
  });
  it('rejects a track ref', () => {
    expect(() => parseSpotifyPlaylistRef('spotify:track:5xkAVrKKnHeBHb1Mqt6wEt')).toThrow(
      InvalidSpotifyRefError,
    );
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && pnpm test spotifyPlaylistRefParse`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement**

Create `frontend/src/features/playlists/lib/spotifyPlaylistRefParse.ts`:

```ts
import { InvalidSpotifyRefError } from './spotifyRefParse';

const BASE62 = /^[0-9A-Za-z]{22}$/;
const URI_RE = /^spotify:playlist:([0-9A-Za-z]{22})$/;
const URL_RE = /^https?:\/\/open\.spotify\.com\/playlist\/([0-9A-Za-z]{22})(?:\?.*)?$/;

export function parseSpotifyPlaylistRef(input: string): string {
  const ref = (input ?? '').trim();
  if (!ref) throw new InvalidSpotifyRefError();

  const uriMatch = URI_RE.exec(ref);
  if (uriMatch && uriMatch[1]) return uriMatch[1];

  const urlMatch = URL_RE.exec(ref);
  if (urlMatch && urlMatch[1]) return urlMatch[1];

  if (BASE62.test(ref)) return ref;

  throw new InvalidSpotifyRefError();
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && pnpm test spotifyPlaylistRefParse`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/features/playlists/lib/spotifyPlaylistRefParse.ts frontend/src/features/playlists/lib/__tests__/spotifyPlaylistRefParse.test.ts
git commit -m "feat(playlists): client-side Spotify playlist ref parser"
```

---

### Task 9: `useImportSpotifyPlaylist` mutation hook + test

**Files:**
- Create: `frontend/src/features/playlists/hooks/useImportSpotifyPlaylist.ts`
- Modify: `frontend/src/features/playlists/lib/playlistTypes.ts` (add result type)
- Test: `frontend/src/features/playlists/hooks/__tests__/useImportSpotifyPlaylist.test.tsx`

**Interfaces:**
- Produces: `ImportSpotifyPlaylistResult` type; `useImportSpotifyPlaylist()` → mutation over `{ spotifyRef: string; name?: string }` returning `ImportSpotifyPlaylistResult`; invalidates `['playlists', 'list']` on success.

- [ ] **Step 1: Add the result type**

In `frontend/src/features/playlists/lib/playlistTypes.ts`:

```ts
export interface ImportSpotifyPlaylistResult {
  playlist_id: string;
  name: string;
  imported: number;
  skipped: number;
  truncated: boolean;
  total: number;
  correlation_id?: string;
}
```

- [ ] **Step 2: Write the failing test**

Create `frontend/src/features/playlists/hooks/__tests__/useImportSpotifyPlaylist.test.tsx`:

```tsx
import React from 'react';
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { renderHook, act } from '@testing-library/react';
import { http, HttpResponse } from 'msw';
import { server } from '../../../../test/setup';
import { useImportSpotifyPlaylist } from '../useImportSpotifyPlaylist';

function makeWrapper(qc: QueryClient) {
  return function Wrapper({ children }: { children: React.ReactNode }) {
    return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
  };
}

describe('useImportSpotifyPlaylist', () => {
  beforeEach(() => {
    server.use(
      http.post('http://localhost/playlists/import-spotify-playlist', () =>
        HttpResponse.json({
          playlist_id: 'pl-new', name: 'Spotify Mix', imported: 2,
          skipped: 0, truncated: false, total: 2,
        }),
      ),
    );
  });

  it('posts the ref and invalidates the playlists list', async () => {
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const spy = vi.spyOn(qc, 'invalidateQueries');
    const { result } = renderHook(() => useImportSpotifyPlaylist(), {
      wrapper: makeWrapper(qc),
    });
    let res!: { playlist_id: string };
    await act(async () => {
      res = await result.current.mutateAsync({ spotifyRef: 'spotify:playlist:37i9dQZF1DXcBWIGoYBM5M' });
    });
    expect(res.playlist_id).toBe('pl-new');
    expect(spy).toHaveBeenCalledWith({ queryKey: ['playlists', 'list'] });
  });
});
```

- [ ] **Step 3: Run test to verify it fails**

Run: `cd frontend && pnpm test useImportSpotifyPlaylist`
Expected: FAIL — module not found.

- [ ] **Step 4: Implement the hook**

Create `frontend/src/features/playlists/hooks/useImportSpotifyPlaylist.ts`:

```ts
import { useMutation, useQueryClient, type UseMutationResult } from '@tanstack/react-query';
import { api } from '../../../api/client';
import type { ImportSpotifyPlaylistResult } from '../lib/playlistTypes';

export interface ImportSpotifyPlaylistInput {
  spotifyRef: string;
  name?: string;
}

export function useImportSpotifyPlaylist(): UseMutationResult<
  ImportSpotifyPlaylistResult,
  Error,
  ImportSpotifyPlaylistInput
> {
  const qc = useQueryClient();
  return useMutation<ImportSpotifyPlaylistResult, Error, ImportSpotifyPlaylistInput>({
    mutationFn: ({ spotifyRef, name }) =>
      api<ImportSpotifyPlaylistResult>('/playlists/import-spotify-playlist', {
        method: 'POST',
        body: JSON.stringify({ spotify_ref: spotifyRef, ...(name ? { name } : {}) }),
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['playlists', 'list'] });
    },
  });
}
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd frontend && pnpm test useImportSpotifyPlaylist`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/features/playlists/hooks/useImportSpotifyPlaylist.ts frontend/src/features/playlists/hooks/__tests__/useImportSpotifyPlaylist.test.tsx frontend/src/features/playlists/lib/playlistTypes.ts
git commit -m "feat(playlists): useImportSpotifyPlaylist mutation hook"
```

---

### Task 10: `ImportSpotifyPlaylistModal` + toolbar entry point + i18n

**Files:**
- Create: `frontend/src/features/playlists/components/ImportSpotifyPlaylistModal.tsx`
- Modify: `frontend/src/features/playlists/routes/PlaylistsListPage.tsx` (add toolbar button + mount modal)
- Modify: locale files (add `playlists.importPlaylist.*` keys — find them: `grep -rl "playlists.import.title" frontend/src`)
- Test: manual/browser (jsdom covers the hook; the modal is simple; no browser test required)

**Interfaces:**
- Consumes: `useImportSpotifyPlaylist`, `parseSpotifyPlaylistRef`, `InvalidSpotifyRefError`, `ApiError`, `useNavigate`, `notifications`.

- [ ] **Step 1: Add i18n keys**

Find the locale JSON (`grep -rl "playlists.import.title" frontend/src` — typically `frontend/src/locales/en/*.json` and a `ru` sibling). Add, under the existing `playlists` object, mirroring the values' language:

English:
```json
"importPlaylist": {
  "cta": "Import Spotify playlist",
  "title": "Import a Spotify playlist",
  "url_label": "Spotify playlist link",
  "url_placeholder": "https://open.spotify.com/playlist/…",
  "name_label": "Playlist name (optional)",
  "invalid_url": "Enter a valid Spotify playlist link",
  "submit": "Import",
  "success": "Imported {{count}} tracks into \"{{name}}\"",
  "success_truncated": "Imported {{count}} tracks (capped at 200) into \"{{name}}\"",
  "name_conflict": "A playlist with this name already exists — pick a name"
}
```
Russian (in the `ru` locale):
```json
"importPlaylist": {
  "cta": "Импорт плейлиста Spotify",
  "title": "Импорт плейлиста из Spotify",
  "url_label": "Ссылка на плейлист Spotify",
  "url_placeholder": "https://open.spotify.com/playlist/…",
  "name_label": "Название плейлиста (необязательно)",
  "invalid_url": "Введите корректную ссылку на плейлист Spotify",
  "submit": "Импортировать",
  "success": "Импортировано {{count}} треков в «{{name}}»",
  "success_truncated": "Импортировано {{count}} треков (лимит 200) в «{{name}}»",
  "name_conflict": "Плейлист с таким именем уже есть — выберите другое имя"
}
```

- [ ] **Step 2: Create the modal**

Create `frontend/src/features/playlists/components/ImportSpotifyPlaylistModal.tsx`:

```tsx
import { useMemo, useState } from 'react';
import { Alert, Button, Group, Modal, Stack, TextInput } from '@mantine/core';
import { IconAlertTriangle } from '@tabler/icons-react';
import { notifications } from '@mantine/notifications';
import { useTranslation } from 'react-i18next';
import { useNavigate } from 'react-router';
import { parseSpotifyPlaylistRef } from '../lib/spotifyPlaylistRefParse';
import { InvalidSpotifyRefError } from '../lib/spotifyRefParse';
import { useImportSpotifyPlaylist } from '../hooks/useImportSpotifyPlaylist';
import { ApiError } from '../../../api/error';

export interface ImportSpotifyPlaylistModalProps {
  opened: boolean;
  onClose: () => void;
}

export function ImportSpotifyPlaylistModal({ opened, onClose }: ImportSpotifyPlaylistModalProps) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const importMut = useImportSpotifyPlaylist();
  const [url, setUrl] = useState('');
  const [name, setName] = useState('');
  const [serverError, setServerError] = useState<string | null>(null);

  const urlValid = useMemo(() => {
    try {
      parseSpotifyPlaylistRef(url);
      return true;
    } catch (e) {
      if (e instanceof InvalidSpotifyRefError) return false;
      return false;
    }
  }, [url]);

  function handleClose() {
    setUrl('');
    setName('');
    setServerError(null);
    onClose();
  }

  async function handleSubmit() {
    setServerError(null);
    try {
      const r = await importMut.mutateAsync({
        spotifyRef: url.trim(),
        name: name.trim() || undefined,
      });
      notifications.show({
        color: 'green',
        message: t(r.truncated ? 'playlists.importPlaylist.success_truncated' : 'playlists.importPlaylist.success', {
          count: r.imported,
          name: r.name,
        }),
      });
      handleClose();
      navigate(`/playlists/${r.playlist_id}`);
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) {
        setServerError(t('playlists.importPlaylist.name_conflict'));
      } else if (err instanceof ApiError && err.status === 412) {
        setServerError(t('playlists.errors.spotify_not_authorized'));
      } else if (err instanceof ApiError && err.status === 502) {
        setServerError(t('playlists.errors.spotify_upstream_error'));
      } else {
        setServerError(t('playlists.toast.generic_error'));
      }
    }
  }

  return (
    <Modal
      opened={opened}
      onClose={handleClose}
      size="lg"
      title={t('playlists.importPlaylist.title')}
      transitionProps={{ duration: 0 }}
    >
      <Stack gap="md">
        {serverError ? (
          <Alert color="red" icon={<IconAlertTriangle size={16} />}>
            {serverError}
          </Alert>
        ) : null}
        <TextInput
          label={t('playlists.importPlaylist.url_label')}
          placeholder={t('playlists.importPlaylist.url_placeholder')}
          value={url}
          onChange={(e) => setUrl(e.currentTarget.value)}
          error={url.length > 0 && !urlValid ? t('playlists.importPlaylist.invalid_url') : undefined}
        />
        <TextInput
          label={t('playlists.importPlaylist.name_label')}
          value={name}
          maxLength={100}
          onChange={(e) => setName(e.currentTarget.value)}
        />
        <Group justify="flex-end">
          <Button
            onClick={() => void handleSubmit()}
            loading={importMut.isPending}
            disabled={!urlValid}
          >
            {t('playlists.importPlaylist.submit')}
          </Button>
        </Group>
      </Stack>
    </Modal>
  );
}
```

- [ ] **Step 3: Wire the button + modal into the list page**

In `frontend/src/features/playlists/routes/PlaylistsListPage.tsx`:
1. Add imports:
```tsx
import { IconBrandSpotify } from '@tabler/icons-react';
import { ImportSpotifyPlaylistModal } from '../components/ImportSpotifyPlaylistModal';
```
2. Add state near the other `useState` booleans:
```tsx
const [importOpen, setImportOpen] = useState(false);
```
3. In the toolbar `<Group gap="sm">` (next to the Create button), add:
```tsx
          <Button
            variant="default"
            leftSection={<IconBrandSpotify size={16} />}
            onClick={() => setImportOpen(true)}
          >
            {t('playlists.importPlaylist.cta')}
          </Button>
```
4. Mount the modal near the other modals at the bottom of the returned `<Stack>`:
```tsx
      <ImportSpotifyPlaylistModal opened={importOpen} onClose={() => setImportOpen(false)} />
```

- [ ] **Step 4: Verify frontend gates**

Run: `cd frontend && pnpm typecheck && pnpm lint && pnpm test`
Expected: all pass (typecheck, eslint, vitest). (Per project gotcha #11, run `pnpm test:browser` only if you touched layout — this modal follows an existing pattern, so jsdom + typecheck suffice.)

- [ ] **Step 5: Commit**

```bash
git add frontend/src/features/playlists/components/ImportSpotifyPlaylistModal.tsx frontend/src/features/playlists/routes/PlaylistsListPage.tsx frontend/src/locales
git commit -m "feat(playlists): import Spotify playlist modal on list page"
```

---

## Phase 6 — Backfill existing broken imports

### Task 11: `SpotifyClient.get_tracks` batch method (for the backfill)

**Files:**
- Modify: `src/collector/spotify_client.py` (add `get_tracks`)
- Test: `tests/unit/test_spotify_client.py` (find/create — `grep -rl "class SpotifyClient" tests/`)

**Interfaces:**
- Produces: `SpotifyClient.get_tracks(spotify_ids: list[str], correlation_id: str) -> dict[str, list[str]]` — maps each spotify track id to its ordered artist display names (batched `GET /v1/tracks?ids=`, ≤50 ids/call, client-credentials).

- [ ] **Step 1: Write the failing test**

Add (or create `tests/unit/test_spotify_client.py`) a test that stubs `_request`:

```python
from unittest.mock import MagicMock
from collector.spotify_client import SpotifyClient


def test_get_tracks_maps_ids_to_artists() -> None:
    client = SpotifyClient(client_id="c", client_secret="s")
    client._ensure_token = MagicMock()  # skip auth
    client._request = MagicMock(return_value={
        "tracks": [
            {"id": "a", "artists": [{"name": "Guri"}, {"name": "Nu Zau"}]},
            {"id": "b", "artists": [{"name": "Solee"}]},
            None,  # unavailable track id
        ]
    })
    out = client.get_tracks(["a", "b", "c"], correlation_id="cid")
    assert out == {"a": ["Guri", "Nu Zau"], "b": ["Solee"]}
    # Batched into one call for ≤50 ids.
    assert client._request.call_count == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_spotify_client.py -k get_tracks -v`
Expected: FAIL — no `get_tracks`.

- [ ] **Step 3: Implement**

In `src/collector/spotify_client.py`, add:

```python
    def get_tracks(
        self, spotify_ids: list[str], correlation_id: str,
    ) -> dict[str, list[str]]:
        """Map each Spotify track id to its ordered artist names (batched)."""
        self._ensure_token(correlation_id)
        out: dict[str, list[str]] = {}
        for i in range(0, len(spotify_ids), 50):
            chunk = spotify_ids[i:i + 50]
            url = f"{API_BASE_URL}/tracks?ids={','.join(chunk)}"
            payload = self._request(url=url, correlation_id=correlation_id)
            for track in payload.get("tracks") or []:
                if not track:
                    continue
                tid = track.get("id")
                if not tid:
                    continue
                out[tid] = [
                    a.get("name") for a in (track.get("artists") or [])
                    if a.get("name")
                ]
        return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_spotify_client.py -k get_tracks -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/collector/spotify_client.py tests/unit/test_spotify_client.py
git commit -m "feat(spotify): batch get_tracks for artist backfill"
```

---

### Task 12: One-off backfill script

**Files:**
- Create: `scripts/backfill_spotify_import_artists.py`

**Interfaces:** standalone script (not imported). Run with `PYTHONPATH=src`. `--dry-run` by default; `--apply` to write.

**Note on scope:** this heals tracks imported before Task 2 (origin `spotify_user_import` with no `clouder_track_artists`). It fetches artists via client-credentials `SpotifyClient.get_tracks`, writes them through the same normalized-name upsert, then re-enqueues YT Music. There is no automated test for the script itself (it's a one-shot wired to live AWS); the logic it depends on (`get_tracks`, artist upsert, `enqueue_vendor_matches`) is unit-tested in earlier tasks. Validate manually with `--dry-run` first.

- [ ] **Step 1: Write the script**

Create `scripts/backfill_spotify_import_artists.py`:

```python
"""One-off: backfill artists for Spotify-imported tracks missing them, then
re-enqueue YT Music matching.

Tracks imported before the artist-persistence fix have no clouder_track_artists
rows, so the ytmusic vendor-match dropped them (empty artist). This finds those
tracks, fetches artists from Spotify (client-credentials catalog read), writes
them, and re-enqueues the match.

Usage:
    PYTHONPATH=src .venv/bin/python scripts/backfill_spotify_import_artists.py --dry-run
    PYTHONPATH=src .venv/bin/python scripts/backfill_spotify_import_artists.py --apply
"""
from __future__ import annotations

import argparse
import uuid
from datetime import datetime, timezone

import boto3

from collector.data_api import create_default_data_api_client
from collector.models import normalize_text
from collector.settings import (
    get_data_api_settings,
    get_api_settings,
    get_spotify_worker_settings,
)
from collector.spotify_client import SpotifyClient
from collector.vendor_match.enqueue import YTMUSIC_VENDOR, enqueue_vendor_matches
from collector.curation.playlists_repository import MatchInput


def _find_artistless(data_api) -> list[dict]:
    return data_api.execute(
        """
        SELECT t.id, t.spotify_id, t.title, t.isrc, t.length_ms
        FROM clouder_tracks t
        LEFT JOIN clouder_track_artists cta ON cta.track_id = t.id
        WHERE t.origin = 'spotify_user_import'
          AND t.spotify_id IS NOT NULL
          AND cta.track_id IS NULL
        """,
        {},
    )


def _upsert_artist(data_api, name: str, now: datetime, tx_id: str) -> str:
    norm = normalize_text(name)
    found = data_api.execute(
        "SELECT id FROM clouder_artists WHERE normalized_name = :n LIMIT 1",
        {"n": norm}, transaction_id=tx_id,
    )
    if found:
        return found[0]["id"]
    aid = str(uuid.uuid4())
    data_api.execute(
        """
        INSERT INTO clouder_artists (id, name, normalized_name, created_at, updated_at)
        VALUES (:id, :name, :n, :now, :now)
        """,
        {"id": aid, "name": name.strip(), "n": norm, "now": now},
        transaction_id=tx_id,
    )
    return aid


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="write changes (default: dry-run)")
    args = parser.parse_args()
    now = datetime.now(timezone.utc)

    db = get_data_api_settings()
    data_api = create_default_data_api_client(
        resource_arn=str(db.aurora_cluster_arn),
        secret_arn=str(db.aurora_secret_arn),
        database=db.aurora_database,
    )
    rows = _find_artistless(data_api)
    print(f"found {len(rows)} artist-less imported tracks")
    if not rows:
        return

    sp = get_spotify_worker_settings()
    client = SpotifyClient(client_id=sp.spotify_client_id, client_secret=sp.spotify_client_secret)
    sids = [r["spotify_id"] for r in rows]
    artists_by_sid = client.get_tracks(sids, correlation_id="backfill")

    healed: list[str] = []
    for r in rows:
        names = artists_by_sid.get(r["spotify_id"], [])
        if not names:
            print(f"  skip {r['id']} ({r['spotify_id']}): no artists from Spotify")
            continue
        print(f"  {r['id']} <- {names}" + ("" if args.apply else " (dry-run)"))
        if not args.apply:
            continue
        with data_api.transaction() as tx_id:
            for name in names:
                aid = _upsert_artist(data_api, name, now, tx_id)
                data_api.execute(
                    """
                    INSERT INTO clouder_track_artists (track_id, artist_id, role)
                    VALUES (:tid, :aid, 'main')
                    ON CONFLICT DO NOTHING
                    """,
                    {"tid": r["id"], "aid": aid}, transaction_id=tx_id,
                )
        healed.append(r["id"])

    if args.apply and healed:
        queue_url = get_api_settings().vendor_match_queue_url
        if queue_url:
            inputs = [
                MatchInput(
                    track_id=r["id"],
                    artist=", ".join(artists_by_sid.get(r["spotify_id"], [])),
                    title=r["title"], isrc=r.get("isrc"),
                    duration_ms=r.get("length_ms"), album=None,
                )
                for r in rows if r["id"] in healed
            ]
            n = enqueue_vendor_matches(
                track_inputs=inputs, vendor=YTMUSIC_VENDOR,
                queue_url=queue_url, sqs=boto3.client("sqs"),
                correlation_id="backfill",
            )
            print(f"re-enqueued {n} ytmusic matches")
        else:
            print("VENDOR_MATCH_QUEUE_URL not set — skipped re-enqueue")

    print(f"done. healed={len(healed)}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Sanity-check the script imports (no live AWS)**

Run: `PYTHONPATH=src .venv/bin/python -c "import ast; ast.parse(open('scripts/backfill_spotify_import_artists.py').read()); print('parse OK')"`
Expected: `parse OK`. (Full run requires live AWS creds; do `--dry-run` against the environment when deploying.)

- [ ] **Step 3: Commit**

```bash
git add scripts/backfill_spotify_import_artists.py
git commit -m "chore(scripts): backfill artists for old Spotify imports"
```

---

## Final verification

- [ ] **Backend full suite:** `pytest -q` → all pass.
- [ ] **Frontend gates:** `cd frontend && pnpm typecheck && pnpm lint && pnpm test` → all pass (per project gotcha #6: the deploy's vite build runs `tsc`, so typecheck must be clean).
- [ ] **OpenAPI clean:** `PYTHONPATH=src .venv/bin/python scripts/generate_openapi.py` produces no diff on re-run; `frontend/src/api/schema.d.ts` matches.
- [ ] **Manual smoke (post-deploy):** import a single Spotify track → confirm it gets a YT Music link (or a review candidate) within a minute; import a small public Spotify playlist → confirm a new mirror playlist appears with the tracks and links.
- [ ] **Backfill (post-deploy):** run `scripts/backfill_spotify_import_artists.py --dry-run`, review, then `--apply`.

## Notes / known follow-ups (out of scope)

- **Label from Spotify** is deferred (label is not in the track payload; needs `GET /albums` + album-row writes). Tracked in the design spec's non-goals.
- **Pre-existing OpenAPI mismatch:** the existing `/playlists/{id}/tracks/import-spotify` entry in `scripts/generate_openapi.py` documents a single `spotify_ref` while the handler takes `spotify_refs: string[]`. Not touched here to keep scope focused; worth a separate fix so `schema.d.ts` reflects reality.
- **Name conflict on re-import:** importing a playlist whose mirror name already exists returns 409; the modal surfaces it and the user picks a name. No auto-suffixing (YAGNI).

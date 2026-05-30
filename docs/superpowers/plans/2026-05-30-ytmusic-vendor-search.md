# YT Music Vendor Search Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Search every track that lands in a user's playlist on YT Music and expose the match status per track, using the existing extensible per-vendor mechanism.

**Architecture:** Fill three missing links in the existing pipeline — a real `YTMusicLookup` (multi-pass `ytmusicapi` search + YT normalization), a producer that enqueues `VendorMatchMessage` for `ytmusic` when tracks are added to playlists (plus a backfill), and a read surface that derives per-track match status (`matched` / `pending` / `needs_review` / `not_found`) for the playlist tracks API and a UI badge. The shared fuzzy scorer and the `vendor_match` worker are reused unchanged except for one small `no_match` recording branch.

**Tech Stack:** Python 3.12, `ytmusicapi`, AWS Lambda + SQS + RDS Data API, Alembic, pytest; React 19 + Mantine 9 + Vitest (jsdom + Playwright browser tests).

**Spec:** `docs/superpowers/specs/2026-05-30-ytmusic-vendor-search-design.md`

**Conventions (from CLAUDE.md):**
- Run all commands from the worktree root. `.venv` lives at the MAIN repo root, so call pytest by absolute path or via `PYTHONPATH=src pytest` from the worktree. Tests below use `PYTHONPATH=src python -m pytest`.
- Commits go through the `caveman:caveman-commit` skill, then `git commit`. Multi-line bodies use the heredoc form. Conventional Commits required. No AI-attribution trailer.
- `docs/api/openapi.yaml` is generated; regenerate with `PYTHONPATH=src .venv/bin/python scripts/generate_openapi.py`.

---

## File Structure

**Backend — created:**
- `src/collector/providers/ytmusic/normalize.py` — pure helpers: query building + YT result → `VendorTrackRef`.
- `src/collector/vendor_match/enqueue.py` — producer helper: build + send `VendorMatchMessage` to the queue.
- `scripts/backfill_vendor_match.py` — admin backfill for tracks already in playlists.
- `alembic/versions/20260530_01_review_no_match_index.py` — partial unique index for `no_match` rows.

**Backend — modified:**
- `src/collector/providers/ytmusic/lookup.py` — replace the stub with the real `YTMusicLookup`.
- `src/collector/providers/registry.py` — `_build_ytmusic` already wires `YTMusicLookup`; no change unless noted.
- `src/collector/requirements.txt` — add `ytmusicapi`.
- `src/collector/repositories.py` — `mark_no_match` on `ClouderRepository`.
- `src/collector/vendor_match_handler.py` — record `no_match` on zero candidates.
- `src/collector/curation/playlists_repository.py` — `MatchInput` dataclass, `fetch_unmatched_match_inputs`, `YtmusicStatus`, `fetch_ytmusic_status`, `PlaylistTrackRow.ytmusic`, enrich in `list_tracks`.
- `src/collector/curation_handler.py` — `_enqueue_ytmusic`, call it from add-tracks + import; include `ytmusic` in `_playlist_track_response`.
- `src/collector/settings.py` — `vendor_match_queue_url` on `ApiSettings`.
- `scripts/generate_openapi.py` — add the `ytmusic` object to the playlist-track response schema.
- `infra/curation.tf` — `VENDOR_MATCH_QUEUE_URL` env on the curation Lambda.
- `infra/variables.tf` — default `vendor_match_vendors_enabled` includes `ytmusic`.
- `docs/backend/providers.md` — move YT Music from "Stubbed" to "Wrapped".

**Frontend — created:**
- `frontend/src/features/playlists/components/YtMusicBadge.tsx`
- `frontend/src/features/playlists/components/__tests__/YtMusicBadge.browser.test.tsx`

**Frontend — modified:**
- `frontend/src/features/playlists/lib/playlistTypes.ts` — `ytmusic` field on `PlaylistTrack`.
- `frontend/src/features/playlists/components/PlaylistTrackRow.tsx` — render the badge.
- `frontend/src/api/schema.d.ts` — regenerated via `pnpm api:types`.

**Tests — created:**
- `tests/unit/test_providers_ytmusic_normalize.py`
- `tests/unit/test_providers_ytmusic_lookup.py`
- `tests/unit/test_vendor_match_enqueue.py`
- `tests/unit/test_repositories_review_no_match.py`
- `tests/unit/test_playlists_repository_ytmusic_status.py`

**Tests — modified:**
- `tests/unit/test_vendor_match_handler.py` — assert `no_match` recorded on zero candidates.
- `tests/unit/test_providers_registry.py` — `get_lookup("ytmusic")` returns the real impl.

---

## Task 1: YT Music normalization helpers (pure functions)

**Files:**
- Create: `src/collector/providers/ytmusic/normalize.py`
- Test: `tests/unit/test_providers_ytmusic_normalize.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/test_providers_ytmusic_normalize.py
from collector.providers.ytmusic.normalize import build_query, result_to_ref


def test_build_query_joins_and_collapses_whitespace():
    assert build_query("Guri  & Eider", " Lost  Track ") == "Guri & Eider Lost Track"


def test_result_to_ref_maps_song_fields_and_strips_topic():
    raw = {
        "videoId": "abc123",
        "title": "Lost Track",
        "artists": [{"name": "Guri - Topic", "id": "A1"}, {"name": "Eider", "id": "A2"}],
        "album": {"name": "Lost EP", "id": "AL1"},
        "duration_seconds": 225,
    }
    ref = result_to_ref(raw)
    assert ref is not None
    assert ref.vendor == "ytmusic"
    assert ref.vendor_track_id == "abc123"
    assert ref.isrc is None
    assert ref.artist_names == ("Guri", "Eider")
    assert ref.title == "Lost Track"
    assert ref.duration_ms == 225_000
    assert ref.album_name == "Lost EP"
    assert ref.raw_payload is raw


def test_result_to_ref_handles_missing_album_and_duration():
    raw = {"videoId": "v9", "title": "Edit", "artists": [{"name": "X"}]}
    ref = result_to_ref(raw)
    assert ref is not None
    assert ref.album_name is None
    assert ref.duration_ms is None


def test_result_to_ref_returns_none_without_video_id():
    assert result_to_ref({"title": "No id", "artists": []}) is None
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `PYTHONPATH=src python -m pytest tests/unit/test_providers_ytmusic_normalize.py -v`
Expected: FAIL with `ModuleNotFoundError: collector.providers.ytmusic.normalize`.

- [ ] **Step 3: Write the implementation**

```python
# src/collector/providers/ytmusic/normalize.py
"""Pure helpers: build a YT Music search query and convert a raw search
result (song or video) into a VendorTrackRef. No network, no scoring."""

from __future__ import annotations

from typing import Any

from ..base import VendorTrackRef

_TOPIC_SUFFIX = " - Topic"


def build_query(artist: str, title: str) -> str:
    """Whitespace-normalized "artist title" query."""
    return " ".join(f"{artist} {title}".split())


def _strip_topic(name: str) -> str:
    if name.endswith(_TOPIC_SUFFIX):
        return name[: -len(_TOPIC_SUFFIX)].strip()
    return name.strip()


def _artist_names(raw: dict[str, Any]) -> tuple[str, ...]:
    artists = raw.get("artists")
    if not isinstance(artists, list):
        return ()
    names = []
    for a in artists:
        if isinstance(a, dict) and a.get("name"):
            cleaned = _strip_topic(str(a["name"]))
            if cleaned:
                names.append(cleaned)
    return tuple(names)


def result_to_ref(raw: dict[str, Any]) -> VendorTrackRef | None:
    """Convert one YT Music search result to a VendorTrackRef.

    Returns None when the result carries no videoId (not playable).
    Works for both `songs` and `videos` result shapes; `videos` simply
    lack an `album` key, which maps to album_name=None.
    """
    video_id = raw.get("videoId")
    if not isinstance(video_id, str) or not video_id:
        return None

    album = raw.get("album")
    album_name = album.get("name") if isinstance(album, dict) else None

    seconds = raw.get("duration_seconds")
    duration_ms = int(seconds) * 1000 if isinstance(seconds, (int, float)) else None

    return VendorTrackRef(
        vendor="ytmusic",
        vendor_track_id=video_id,
        isrc=None,
        artist_names=_artist_names(raw),
        title=str(raw.get("title") or ""),
        duration_ms=duration_ms,
        album_name=str(album_name) if album_name else None,
        raw_payload=raw,
    )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `PYTHONPATH=src python -m pytest tests/unit/test_providers_ytmusic_normalize.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add src/collector/providers/ytmusic/normalize.py tests/unit/test_providers_ytmusic_normalize.py
git commit -m "feat(ytmusic): add search-result normalization helpers"
```

---

## Task 2: Real `YTMusicLookup` (multi-pass search)

**Files:**
- Modify: `src/collector/providers/ytmusic/lookup.py`
- Test: `tests/unit/test_providers_ytmusic_lookup.py`

The lookup owns the YT search strategy (algorithm B): pass 1 `songs`, fallback to `videos` only when pass 1 yields no playable candidate. Scoring stays in the worker. The `ytmusicapi` client is created lazily via an injectable factory so tests need no network and the module imports without the package installed.

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/test_providers_ytmusic_lookup.py
from collector.providers.ytmusic.lookup import YTMusicLookup


class FakeYT:
    def __init__(self, by_filter):
        self.by_filter = by_filter
        self.calls = []

    def search(self, query, filter, limit):  # noqa: A002 - matches ytmusicapi
        self.calls.append((query, filter, limit))
        return self.by_filter.get(filter, [])


def test_isrc_lookup_always_none():
    lookup = YTMusicLookup(client=FakeYT({}))
    assert lookup.lookup_by_isrc("GBxxx1234567") is None


def test_metadata_uses_songs_pass_first():
    fake = FakeYT({
        "songs": [
            {"videoId": "v1", "title": "Lost Track",
             "artists": [{"name": "Guri"}], "duration_seconds": 225},
        ],
    })
    lookup = YTMusicLookup(client=fake)
    refs = lookup.lookup_by_metadata("Guri", "Lost Track", 225_000, None)
    assert [r.vendor_track_id for r in refs] == ["v1"]
    assert [c[1] for c in fake.calls] == ["songs"]  # no fallback


def test_metadata_falls_back_to_videos_when_songs_empty():
    fake = FakeYT({
        "songs": [],
        "videos": [{"videoId": "v2", "title": "Edit", "artists": [{"name": "Guri"}]}],
    })
    lookup = YTMusicLookup(client=fake)
    refs = lookup.lookup_by_metadata("Guri", "Edit", None, None)
    assert [r.vendor_track_id for r in refs] == ["v2"]
    assert [c[1] for c in fake.calls] == ["songs", "videos"]


def test_metadata_skips_results_without_video_id():
    fake = FakeYT({"songs": [{"title": "no id", "artists": []}]})
    lookup = YTMusicLookup(client=fake)
    # songs pass produced no playable ref -> falls back to (empty) videos pass
    assert lookup.lookup_by_metadata("A", "B", None, None) == []
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `PYTHONPATH=src python -m pytest tests/unit/test_providers_ytmusic_lookup.py -v`
Expected: FAIL — the stub `lookup_by_isrc` raises `VendorDisabledError` and `lookup_by_metadata` raises too.

- [ ] **Step 3: Write the implementation (replace the file)**

```python
# src/collector/providers/ytmusic/lookup.py
"""YTMusicLookup — LookupProvider over ytmusicapi (unauthenticated search).

YT Music exposes no public ISRC search, so lookup_by_isrc always returns
None and matching relies entirely on lookup_by_metadata + the shared fuzzy
scorer in vendor_match_handler. The ytmusicapi client is built lazily via an
injectable factory: the module imports cleanly without the package, and tests
inject a fake.
"""

from __future__ import annotations

from typing import Any

from ...errors import VendorDisabledError
from ..base import VendorTrackRef
from .normalize import build_query, result_to_ref

_SEARCH_LIMIT = 10


def _default_client_factory() -> Any:
    from ytmusicapi import YTMusic  # lazy: only when a search actually runs

    return YTMusic()


class YTMusicLookup:
    vendor_name = "ytmusic"

    def __init__(
        self,
        client: Any | None = None,
        client_factory: Any = _default_client_factory,
        search_limit: int = _SEARCH_LIMIT,
    ) -> None:
        self._client = client
        self._client_factory = client_factory
        self._search_limit = search_limit

    def _get_client(self) -> Any:
        if self._client is None:
            self._client = self._client_factory()
        return self._client

    def lookup_batch_by_isrc(
        self, tracks: list[dict[str, str]], correlation_id: str
    ) -> list[Any]:
        # Consumed only by the Spotify worker's batch path.
        raise VendorDisabledError(self.vendor_name, reason="not_implemented")

    def lookup_by_isrc(self, isrc: str) -> VendorTrackRef | None:
        # YT Music has no ISRC search; the worker's ISRC fast-path is skipped.
        return None

    def lookup_by_metadata(
        self,
        artist: str,
        title: str,
        duration_ms: int | None,
        album: str | None,
    ) -> list[VendorTrackRef]:
        query = build_query(artist, title)
        client = self._get_client()
        candidates = self._search(client, query, "songs")
        if not candidates:
            candidates = self._search(client, query, "videos")
        return candidates

    def _search(self, client: Any, query: str, filter_name: str) -> list[VendorTrackRef]:
        raw_results = client.search(query, filter=filter_name, limit=self._search_limit)
        refs: list[VendorTrackRef] = []
        for raw in raw_results or []:
            if not isinstance(raw, dict):
                continue
            ref = result_to_ref(raw)
            if ref is not None:
                refs.append(ref)
        return refs
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `PYTHONPATH=src python -m pytest tests/unit/test_providers_ytmusic_lookup.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add src/collector/providers/ytmusic/lookup.py tests/unit/test_providers_ytmusic_lookup.py
git commit -m "feat(ytmusic): implement multi-pass metadata search"
```

---

## Task 3: Dependency + registry confirmation

**Files:**
- Modify: `src/collector/requirements.txt`
- Test: `tests/unit/test_providers_registry.py`

`_build_ytmusic` already returns `ProviderBundle(lookup=YTMusicLookup(), ...)`. Because the client is lazy, building the bundle runs no network. Add the runtime dependency and pin the registry behaviour with a test.

- [ ] **Step 1: Add the failing test**

Append to `tests/unit/test_providers_registry.py`:

```python
def test_get_lookup_ytmusic_returns_real_impl(monkeypatch):
    from collector.providers import registry
    from collector.providers.ytmusic.lookup import YTMusicLookup

    monkeypatch.setenv("VENDORS_ENABLED", "ytmusic")
    registry.reset_cache()
    lookup = registry.get_lookup("ytmusic")
    assert isinstance(lookup, YTMusicLookup)
    assert lookup.lookup_by_isrc("US1234567890") is None
```

- [ ] **Step 2: Run it to verify it passes or fails**

Run: `PYTHONPATH=src python -m pytest tests/unit/test_providers_registry.py::test_get_lookup_ytmusic_returns_real_impl -v`
Expected: PASS (the registry already wires `YTMusicLookup`; this test pins it). If it fails, confirm `_build_ytmusic` in `registry.py` constructs `YTMusicLookup()`.

- [ ] **Step 3: Add the dependency**

Edit `src/collector/requirements.txt`, add a line under the existing deps:

```
ytmusicapi>=1.7
```

- [ ] **Step 4: Verify packaging picks it up**

Run: `grep -n "requirements" scripts/package_lambda.sh`
Expected: the script `pip install`s `src/collector/requirements.txt` into the build dir. No code change needed; if the grep shows it installs a different requirements file, add `ytmusicapi>=1.7` there too.

- [ ] **Step 5: Commit**

```bash
git add src/collector/requirements.txt tests/unit/test_providers_registry.py
git commit -m "build(ytmusic): add ytmusicapi runtime dependency"
```

---

## Task 4: `no_match` index + repository method

**Files:**
- Create: `alembic/versions/20260530_01_review_no_match_index.py`
- Modify: `src/collector/repositories.py`
- Test: `tests/unit/test_repositories_review_no_match.py`

The read surface needs to tell `not_found` from `pending`. The worker will record a `match_review_queue` row with `status='no_match'` when a search yields zero candidates. A partial unique index keeps re-runs idempotent via `ON CONFLICT`.

- [ ] **Step 1: Write the migration**

```python
# alembic/versions/20260530_01_review_no_match_index.py
"""match_review_queue: partial unique index for no_match rows

Revision ID: 20260530_01
Revises: 20260421_10
Create Date: 2026-05-30
"""

from alembic import op
import sqlalchemy as sa

revision = "20260530_01"
down_revision = "20260421_10"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "uq_review_no_match",
        "match_review_queue",
        ["clouder_track_id", "vendor"],
        unique=True,
        postgresql_where=sa.text("status = 'no_match'"),
    )


def downgrade() -> None:
    op.drop_index("uq_review_no_match", table_name="match_review_queue")
```

Confirm `down_revision` matches the current head:

Run: `grep -rl "revision = " alembic/versions/20260421_10_vendor_match_tables.py && grep "^revision" alembic/versions/20260421_10_vendor_match_tables.py`
Expected: `revision = "20260421_10"`. If the project's latest migration is newer, set `down_revision` to that file's `revision` instead.

- [ ] **Step 2: Write the failing test**

```python
# tests/unit/test_repositories_review_no_match.py
from datetime import datetime, timezone

from collector.repositories import ClouderRepository


class FakeDataAPI:
    def __init__(self):
        self.calls = []

    def execute(self, sql, params=None, transaction_id=None):
        self.calls.append((sql, params))
        return []


def test_mark_no_match_inserts_no_match_row():
    api = FakeDataAPI()
    repo = ClouderRepository(api)
    repo.mark_no_match(
        clouder_track_id="t1",
        vendor="ytmusic",
        created_at=datetime(2026, 5, 30, tzinfo=timezone.utc),
    )
    sql, params = api.calls[-1]
    assert "INSERT INTO match_review_queue" in sql
    assert "'no_match'" in sql
    assert "ON CONFLICT" in sql and "status = 'no_match'" in sql
    assert params["clouder_track_id"] == "t1"
    assert params["vendor"] == "ytmusic"
```

- [ ] **Step 3: Run it to verify it fails**

Run: `PYTHONPATH=src python -m pytest tests/unit/test_repositories_review_no_match.py -v`
Expected: FAIL — `ClouderRepository` has no `mark_no_match`.

- [ ] **Step 4: Implement `mark_no_match`**

Add to `ClouderRepository` in `src/collector/repositories.py`, directly after `insert_review_candidate`:

```python
    def mark_no_match(
        self,
        *,
        clouder_track_id: str,
        vendor: str,
        created_at: datetime,
        transaction_id: str | None = None,
    ) -> None:
        """Record a terminal 'no match found' outcome so the read surface can
        return not_found (distinct from pending). Idempotent via the partial
        unique index uq_review_no_match."""
        from uuid import uuid4

        self._data_api.execute(
            """
            INSERT INTO match_review_queue (
                id, clouder_track_id, vendor, candidates, status, created_at
            ) VALUES (
                :id, :clouder_track_id, :vendor, :candidates, 'no_match', :created_at
            )
            ON CONFLICT (clouder_track_id, vendor)
                WHERE status = 'no_match'
                DO NOTHING
            """,
            {
                "id": str(uuid4()),
                "clouder_track_id": clouder_track_id,
                "vendor": vendor,
                "candidates": [],
                "created_at": created_at,
            },
            transaction_id=transaction_id,
        )
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `PYTHONPATH=src python -m pytest tests/unit/test_repositories_review_no_match.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add alembic/versions/20260530_01_review_no_match_index.py src/collector/repositories.py tests/unit/test_repositories_review_no_match.py
git commit -m "feat(vendor-match): record no_match terminal outcome"
```

---

## Task 5: Worker records `no_match` on zero candidates

**Files:**
- Modify: `src/collector/vendor_match_handler.py:_process_one`
- Test: `tests/unit/test_vendor_match_handler.py`

In `_process_one`, the `else` branch under "no candidates" currently only logs `vendor_match_no_candidates`. Add a `mark_no_match` call.

- [ ] **Step 1: Add the failing test**

Append to `tests/unit/test_vendor_match_handler.py` (reuse the file's existing fakes/fixtures for `VendorMatchMessage` and a repository double; mirror the nearest existing test that drives `_process_one` with an empty candidate list):

```python
def test_process_one_records_no_match_when_no_candidates(monkeypatch):
    from collector import vendor_match_handler as h
    from collector.schemas import VendorMatchMessage

    class Lookup:
        def lookup_by_isrc(self, isrc):
            return None

        def lookup_by_metadata(self, artist, title, duration_ms, album):
            return []

    monkeypatch.setattr(h.registry, "get_lookup", lambda vendor: Lookup())

    class Repo:
        def __init__(self):
            self.no_match = []

        def get_vendor_match(self, track_id, vendor):
            return None

        def upsert_vendor_match(self, cmd):
            raise AssertionError("should not upsert a match")

        def insert_review_candidate(self, **kw):
            raise AssertionError("should not queue review with no candidates")

        def mark_no_match(self, *, clouder_track_id, vendor, created_at):
            self.no_match.append((clouder_track_id, vendor))

    repo = Repo()
    msg = VendorMatchMessage(
        clouder_track_id="t1", vendor="ytmusic",
        artist="Guri", title="Lost Track",
    )
    assert h._process_one(msg, repo) is True
    assert repo.no_match == [("t1", "ytmusic")]
```

- [ ] **Step 2: Run it to verify it fails**

Run: `PYTHONPATH=src python -m pytest tests/unit/test_vendor_match_handler.py::test_process_one_records_no_match_when_no_candidates -v`
Expected: FAIL — `Repo.mark_no_match` is never called.

- [ ] **Step 3: Implement the change**

In `src/collector/vendor_match_handler.py`, find the final `else` branch in `_process_one`:

```python
    else:
        log_event(
            "WARNING",
            "vendor_match_no_candidates",
            track_id=message.clouder_track_id,
            vendor=message.vendor,
        )
    return True
```

Replace with:

```python
    else:
        repository.mark_no_match(
            clouder_track_id=message.clouder_track_id,
            vendor=message.vendor,
            created_at=now,
        )
        log_event(
            "WARNING",
            "vendor_match_no_candidates",
            track_id=message.clouder_track_id,
            vendor=message.vendor,
        )
    return True
```

(`now` is already defined earlier in `_process_one` as `datetime.now(timezone.utc)`.)

- [ ] **Step 4: Run the test to verify it passes**

Run: `PYTHONPATH=src python -m pytest tests/unit/test_vendor_match_handler.py -v`
Expected: PASS (existing tests still green).

- [ ] **Step 5: Commit**

```bash
git add src/collector/vendor_match_handler.py tests/unit/test_vendor_match_handler.py
git commit -m "feat(vendor-match): mark no_match when search returns nothing"
```

---

## Task 6: Repository — fetch enqueue inputs (unmatched only)

**Files:**
- Modify: `src/collector/curation/playlists_repository.py`
- Test: `tests/unit/test_playlists_repository_ytmusic_status.py` (shared test file for Tasks 6 & 9)

`fetch_unmatched_match_inputs` returns the metadata needed to build a `VendorMatchMessage` for tracks not yet in `vendor_track_map` for the vendor. Aurora Data API forbids array params, so the `IN` list is built parametrically (same pattern as `append_tracks`).

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_playlists_repository_ytmusic_status.py
from collector.curation.playlists_repository import PlaylistsRepository


class FakeDataAPI:
    def __init__(self, rows_by_marker):
        # rows_by_marker: list of (sql_substring, rows) checked in order
        self.rows_by_marker = rows_by_marker
        self.calls = []

    def execute(self, sql, params=None, transaction_id=None):
        self.calls.append((sql, params))
        for marker, rows in self.rows_by_marker:
            if marker in sql:
                return rows
        return []


def test_fetch_unmatched_match_inputs_filters_and_joins():
    api = FakeDataAPI([
        ("FROM clouder_tracks t", [
            {"track_id": "t1", "title": "Lost Track", "isrc": "GB123",
             "length_ms": 225000, "artist_names": "Guri, Eider",
             "album_title": "Lost EP"},
        ]),
    ])
    repo = PlaylistsRepository(api)
    inputs = repo.fetch_unmatched_match_inputs(track_ids=["t1", "t2"], vendor="ytmusic")
    assert len(inputs) == 1
    inp = inputs[0]
    assert inp.track_id == "t1"
    assert inp.artist == "Guri, Eider"
    assert inp.title == "Lost Track"
    assert inp.isrc == "GB123"
    assert inp.duration_ms == 225000
    assert inp.album == "Lost EP"
    # vendor filter + IN-list params present
    sql, params = api.calls[-1]
    assert params["vendor"] == "ytmusic"
    assert params["t0"] == "t1" and params["t1"] == "t2"


def test_fetch_unmatched_match_inputs_empty_returns_empty():
    repo = PlaylistsRepository(FakeDataAPI([]))
    assert repo.fetch_unmatched_match_inputs(track_ids=[], vendor="ytmusic") == []
```

- [ ] **Step 2: Run it to verify it fails**

Run: `PYTHONPATH=src python -m pytest tests/unit/test_playlists_repository_ytmusic_status.py -v`
Expected: FAIL — `fetch_unmatched_match_inputs` does not exist.

- [ ] **Step 3: Implement `MatchInput` + the method**

Add near the top of `src/collector/curation/playlists_repository.py` (after the existing dataclasses):

```python
@dataclass(frozen=True)
class MatchInput:
    track_id: str
    artist: str
    title: str
    isrc: str | None
    duration_ms: int | None
    album: str | None
```

Add to `PlaylistsRepository`:

```python
    def fetch_unmatched_match_inputs(
        self, *, track_ids: list[str], vendor: str
    ) -> list[MatchInput]:
        """Metadata for tracks not yet matched to `vendor`, ready to enqueue."""
        if not track_ids:
            return []
        placeholders = ", ".join(f":t{i}" for i in range(len(track_ids)))
        params: dict[str, Any] = {"vendor": vendor}
        for i, tid in enumerate(track_ids):
            params[f"t{i}"] = tid
        rows = self._data_api.execute(
            f"""
            SELECT
                t.id AS track_id,
                t.title,
                t.isrc,
                t.length_ms,
                alb.title AS album_title,
                COALESCE(STRING_AGG(DISTINCT a.name, ', '), '') AS artist_names
            FROM clouder_tracks t
            LEFT JOIN clouder_track_artists cta ON cta.track_id = t.id
            LEFT JOIN clouder_artists       a   ON a.id = cta.artist_id
            LEFT JOIN clouder_albums        alb ON alb.id = t.album_id
            LEFT JOIN vendor_track_map      vtm
                ON vtm.clouder_track_id = t.id AND vtm.vendor = :vendor
            WHERE t.id IN ({placeholders}) AND vtm.clouder_track_id IS NULL
            GROUP BY t.id, t.title, t.isrc, t.length_ms, alb.title
            """,
            params,
        )
        out: list[MatchInput] = []
        for r in rows:
            length = r.get("length_ms")
            out.append(
                MatchInput(
                    track_id=r["track_id"],
                    artist=r.get("artist_names") or "",
                    title=r.get("title") or "",
                    isrc=r.get("isrc"),
                    duration_ms=int(length) if length else None,
                    album=r.get("album_title"),
                )
            )
        return out
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `PYTHONPATH=src python -m pytest tests/unit/test_playlists_repository_ytmusic_status.py -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add src/collector/curation/playlists_repository.py tests/unit/test_playlists_repository_ytmusic_status.py
git commit -m "feat(playlists): fetch unmatched track inputs for vendor match"
```

---

## Task 7: Enqueue producer helper

**Files:**
- Create: `src/collector/vendor_match/enqueue.py`
- Test: `tests/unit/test_vendor_match_enqueue.py`

A standalone, side-effect-isolated helper that turns `MatchInput`s into `VendorMatchMessage`s and sends them to the queue. SQS errors are logged, never raised.

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/test_vendor_match_enqueue.py
from collector.curation.playlists_repository import MatchInput
from collector.vendor_match.enqueue import enqueue_vendor_matches


class FakeSqs:
    def __init__(self, fail=False):
        self.fail = fail
        self.sent = []

    def send_message(self, *, QueueUrl, MessageBody):
        if self.fail:
            raise RuntimeError("sqs down")
        self.sent.append((QueueUrl, MessageBody))


def _inp(track_id="t1", artist="Guri", title="Lost Track"):
    return MatchInput(track_id=track_id, artist=artist, title=title,
                      isrc="GB1", duration_ms=225000, album="EP")


def test_enqueue_sends_one_message_per_input():
    sqs = FakeSqs()
    n = enqueue_vendor_matches(
        track_inputs=[_inp("t1"), _inp("t2")], vendor="ytmusic",
        queue_url="http://q", sqs=sqs,
    )
    assert n == 2
    assert len(sqs.sent) == 2
    assert '"vendor":"ytmusic"' in sqs.sent[0][1].replace(" ", "")


def test_enqueue_no_queue_url_is_noop():
    sqs = FakeSqs()
    assert enqueue_vendor_matches(track_inputs=[_inp()], vendor="ytmusic",
                                  queue_url="", sqs=sqs) == 0
    assert sqs.sent == []


def test_enqueue_skips_invalid_input():
    # empty artist fails VendorMatchMessage validation -> skipped, not raised
    sqs = FakeSqs()
    bad = MatchInput(track_id="t1", artist="", title="X", isrc=None,
                     duration_ms=None, album=None)
    assert enqueue_vendor_matches(track_inputs=[bad], vendor="ytmusic",
                                  queue_url="http://q", sqs=sqs) == 0


def test_enqueue_swallows_sqs_errors():
    sqs = FakeSqs(fail=True)
    assert enqueue_vendor_matches(track_inputs=[_inp()], vendor="ytmusic",
                                  queue_url="http://q", sqs=sqs) == 0
```

- [ ] **Step 2: Run them to verify they fail**

Run: `PYTHONPATH=src python -m pytest tests/unit/test_vendor_match_enqueue.py -v`
Expected: FAIL — module does not exist.

- [ ] **Step 3: Implement the helper**

```python
# src/collector/vendor_match/enqueue.py
"""Producer: send VendorMatchMessage to the vendor-match queue.

Failures never propagate — enqueue is best-effort so a transient SQS issue
cannot fail the originating user request. The match simply arrives later.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol

from ..logging_utils import log_event
from ..schemas import VendorMatchMessage

if TYPE_CHECKING:
    from ..curation.playlists_repository import MatchInput

YTMUSIC_VENDOR = "ytmusic"


class SqsSender(Protocol):
    def send_message(self, *, QueueUrl: str, MessageBody: str) -> Any: ...


def enqueue_vendor_matches(
    *,
    track_inputs: "list[MatchInput]",
    vendor: str,
    queue_url: str,
    sqs: SqsSender,
    correlation_id: str = "",
) -> int:
    """Send one message per input. Returns the count actually sent."""
    if not queue_url:
        log_event(
            "WARNING", "vendor_match_enqueue_skipped",
            reason="no_queue_url", vendor=vendor,
        )
        return 0

    sent = 0
    for inp in track_inputs:
        try:
            message = VendorMatchMessage(
                clouder_track_id=inp.track_id,
                vendor=vendor,
                isrc=inp.isrc,
                artist=inp.artist,
                title=inp.title,
                duration_ms=inp.duration_ms,
                album=inp.album,
            )
        except Exception as exc:  # pydantic validation (e.g. empty artist/title)
            log_event(
                "WARNING", "vendor_match_enqueue_invalid",
                track_id=inp.track_id, vendor=vendor, error_message=str(exc),
            )
            continue
        try:
            sqs.send_message(QueueUrl=queue_url, MessageBody=message.model_dump_json())
            sent += 1
        except Exception as exc:
            log_event(
                "ERROR", "vendor_match_enqueue_failed",
                track_id=inp.track_id, vendor=vendor, error_message=str(exc),
            )

    log_event(
        "INFO", "vendor_match_enqueued",
        vendor=vendor, count=sent, correlation_id=correlation_id,
    )
    return sent
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `PYTHONPATH=src python -m pytest tests/unit/test_vendor_match_enqueue.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add src/collector/vendor_match/enqueue.py tests/unit/test_vendor_match_enqueue.py
git commit -m "feat(vendor-match): add best-effort enqueue producer"
```

---

## Task 8: Settings field + wire enqueue into curation handler

**Files:**
- Modify: `src/collector/settings.py:ApiSettings`
- Modify: `src/collector/curation_handler.py`
- Test: `tests/unit/test_curation_handler.py`

Add the queue-URL setting, a `_enqueue_ytmusic` helper in the handler, and call it after tracks are appended in both `_handle_add_playlist_tracks` and `_handle_import_spotify`.

- [ ] **Step 1: Add the settings field**

In `src/collector/settings.py`, add to `ApiSettings` (after `spotify_search_queue_url`):

```python
    vendor_match_queue_url: str = Field(default="", alias="VENDOR_MATCH_QUEUE_URL")
```

- [ ] **Step 2: Write the failing test**

Append to `tests/unit/test_curation_handler.py` (reuse the module's existing helpers for building events / repo doubles; this test asserts the handler calls the enqueue helper with the freshly-added ids):

```python
def test_add_playlist_tracks_enqueues_ytmusic(monkeypatch):
    from collector import curation_handler as ch

    captured = {}

    def fake_enqueue(repo, added_track_ids, correlation_id):
        captured["ids"] = list(added_track_ids)

    monkeypatch.setattr(ch, "_enqueue_ytmusic", fake_enqueue)

    class Repo:
        def validate_tracks_in_scope(self, *, user_id, track_ids):
            return set(track_ids)

        def append_tracks(self, *, user_id, playlist_id, track_ids, now):
            from collector.curation.playlists_repository import AppendTracksResult
            return AppendTracksResult(
                added_track_ids=["t1"], skipped_duplicates=["t2"], position_after=1,
            )

    event = {
        "pathParameters": {"id": "pl1"},
        "body": '{"track_ids": ["t1", "t2"]}',
    }
    ch._handle_add_playlist_tracks(event, Repo(), "user1", "corr1")
    assert captured["ids"] == ["t1"]  # only newly added, not skipped duplicates
```

- [ ] **Step 3: Run it to verify it fails**

Run: `PYTHONPATH=src python -m pytest tests/unit/test_curation_handler.py::test_add_playlist_tracks_enqueues_ytmusic -v`
Expected: FAIL — `_enqueue_ytmusic` does not exist.

- [ ] **Step 4: Implement the helper and wire it in**

In `src/collector/curation_handler.py`, add the helper near the other module-level helpers (e.g. after `_playlist_track_response`):

```python
def _enqueue_ytmusic(repo, added_track_ids, correlation_id) -> None:
    """Best-effort: enqueue YT Music match jobs for newly added tracks.

    Never raises — a failure here must not fail the track-add request.
    """
    if not added_track_ids:
        return
    try:
        import boto3

        from collector.settings import get_api_settings
        from collector.vendor_match.enqueue import (
            YTMUSIC_VENDOR,
            enqueue_vendor_matches,
        )

        queue_url = get_api_settings().vendor_match_queue_url
        if not queue_url:
            return
        inputs = repo.fetch_unmatched_match_inputs(
            track_ids=list(added_track_ids), vendor=YTMUSIC_VENDOR,
        )
        enqueue_vendor_matches(
            track_inputs=inputs,
            vendor=YTMUSIC_VENDOR,
            queue_url=queue_url,
            sqs=boto3.client("sqs"),
            correlation_id=correlation_id,
        )
    except Exception as exc:  # pragma: no cover - defensive
        log_event(
            "ERROR", "vendor_match_enqueue_unexpected",
            correlation_id=correlation_id, error_message=str(exc),
        )
```

In `_handle_add_playlist_tracks`, after the `log_event("INFO", "playlist_track_added", ...)` call and before building the response, add:

```python
    _enqueue_ytmusic(repo, result.added_track_ids, correlation_id)
```

In `_handle_import_spotify`, after its `repo.append_tracks(...)` returns `result`, add the same call:

```python
    _enqueue_ytmusic(repo, result.added_track_ids, correlation_id)
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `PYTHONPATH=src python -m pytest tests/unit/test_curation_handler.py -v`
Expected: PASS (new test + existing tests green).

- [ ] **Step 6: Commit**

```bash
git add src/collector/settings.py src/collector/curation_handler.py tests/unit/test_curation_handler.py
git commit -m "feat(curation): enqueue ytmusic match on track add and import"
```

---

## Task 9: Read surface — per-track match status

**Files:**
- Modify: `src/collector/curation/playlists_repository.py`
- Modify: `src/collector/curation_handler.py:_playlist_track_response`
- Test: `tests/unit/test_playlists_repository_ytmusic_status.py`

Add `YtmusicStatus`, `fetch_ytmusic_status`, the `ytmusic` field on `PlaylistTrackRow`, enrichment in `list_tracks`, and the response field.

- [ ] **Step 1: Add the failing test**

Append to `tests/unit/test_playlists_repository_ytmusic_status.py`:

```python
def test_fetch_ytmusic_status_derives_all_states():
    from collector.curation.playlists_repository import PlaylistsRepository

    api = FakeDataAPI([
        ("FROM vendor_track_map", [
            {"clouder_track_id": "t_matched", "vendor_track_id": "vid1",
             "confidence": "0.970"},
        ]),
        ("FROM match_review_queue", [
            {"clouder_track_id": "t_review", "status": "pending"},
            {"clouder_track_id": "t_none", "status": "no_match"},
        ]),
    ])
    repo = PlaylistsRepository(api)
    status = repo.fetch_ytmusic_status(["t_matched", "t_review", "t_none", "t_pending"])

    assert status["t_matched"].status == "matched"
    assert status["t_matched"].video_id == "vid1"
    assert status["t_matched"].url == "https://music.youtube.com/watch?v=vid1"
    assert abs(status["t_matched"].confidence - 0.97) < 1e-6
    assert status["t_review"].status == "needs_review"
    assert status["t_none"].status == "not_found"
    assert status["t_pending"].status == "pending"
```

- [ ] **Step 2: Run it to verify it fails**

Run: `PYTHONPATH=src python -m pytest tests/unit/test_playlists_repository_ytmusic_status.py::test_fetch_ytmusic_status_derives_all_states -v`
Expected: FAIL — `fetch_ytmusic_status` does not exist.

- [ ] **Step 3: Implement status read + row field + enrichment**

Add the dataclass near `MatchInput` in `playlists_repository.py`:

```python
@dataclass(frozen=True)
class YtmusicStatus:
    status: str  # matched | pending | needs_review | not_found
    video_id: str | None = None
    url: str | None = None
    confidence: float | None = None
```

Add the `ytmusic` field to `PlaylistTrackRow` (after `tags`):

```python
    ytmusic: dict | None = None
```

Add the method to `PlaylistsRepository`:

```python
    def fetch_ytmusic_status(
        self, track_ids: list[str]
    ) -> dict[str, "YtmusicStatus"]:
        """Per-track YT Music status. matched > needs_review > not_found > pending."""
        if not track_ids:
            return {}
        placeholders = ", ".join(f":t{i}" for i in range(len(track_ids)))
        params: dict[str, Any] = {"vendor": "ytmusic"}
        for i, tid in enumerate(track_ids):
            params[f"t{i}"] = tid

        matched_rows = self._data_api.execute(
            f"""
            SELECT clouder_track_id, vendor_track_id, confidence
            FROM vendor_track_map
            WHERE vendor = :vendor AND clouder_track_id IN ({placeholders})
            """,
            params,
        )
        review_rows = self._data_api.execute(
            f"""
            SELECT clouder_track_id, status
            FROM match_review_queue
            WHERE vendor = :vendor
              AND status IN ('pending', 'no_match')
              AND clouder_track_id IN ({placeholders})
            """,
            params,
        )

        matched = {
            r["clouder_track_id"]: r for r in matched_rows
        }
        review = {r["clouder_track_id"]: r["status"] for r in review_rows}

        out: dict[str, YtmusicStatus] = {}
        for tid in track_ids:
            if tid in matched:
                row = matched[tid]
                vid = row["vendor_track_id"]
                out[tid] = YtmusicStatus(
                    status="matched",
                    video_id=vid,
                    url=f"https://music.youtube.com/watch?v={vid}",
                    confidence=float(row["confidence"]),
                )
            elif review.get(tid) == "pending":
                out[tid] = YtmusicStatus(status="needs_review")
            elif review.get(tid) == "no_match":
                out[tid] = YtmusicStatus(status="not_found")
            else:
                out[tid] = YtmusicStatus(status="pending")
        return out
```

In `list_tracks`, after the `tags_repo` enrichment block and before `return out, total`, add:

```python
        if out:
            statuses = self.fetch_ytmusic_status([row.track_id for row in out])
            out = [
                replace(
                    row,
                    ytmusic={
                        "status": s.status,
                        "video_id": s.video_id,
                        "url": s.url,
                        "confidence": s.confidence,
                    } if (s := statuses.get(row.track_id)) else None,
                )
                for row in out
            ]
```

In `src/collector/curation_handler.py:_playlist_track_response`, add the field to the returned dict:

```python
        "ytmusic": getattr(row, "ytmusic", None),
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `PYTHONPATH=src python -m pytest tests/unit/test_playlists_repository_ytmusic_status.py tests/unit/test_curation_handler.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/collector/curation/playlists_repository.py src/collector/curation_handler.py tests/unit/test_playlists_repository_ytmusic_status.py
git commit -m "feat(playlists): expose per-track ytmusic match status"
```

---

## Task 10: OpenAPI + frontend schema regeneration

**Files:**
- Modify: `scripts/generate_openapi.py`
- Generated: `docs/api/openapi.yaml`, `frontend/src/api/schema.d.ts`

- [ ] **Step 1: Locate the playlist-track response schema**

Run: `grep -n "is_ai_suspected\|playlist.*track\|added_at" scripts/generate_openapi.py`
Expected: a schema block (the object with `track_id`, `title`, `artists`, `is_ai_suspected`, …). This is the object to extend.

- [ ] **Step 2: Add the `ytmusic` property**

In that schema's `properties`, add:

```python
        "ytmusic": {
            "type": "object",
            "nullable": True,
            "properties": {
                "status": {
                    "type": "string",
                    "enum": ["matched", "pending", "needs_review", "not_found"],
                },
                "video_id": {"type": "string", "nullable": True},
                "url": {"type": "string", "nullable": True},
                "confidence": {"type": "number", "nullable": True},
            },
            "required": ["status"],
        },
```

- [ ] **Step 3: Regenerate the OpenAPI document**

Run: `PYTHONPATH=src .venv/bin/python scripts/generate_openapi.py`
Expected: `docs/api/openapi.yaml` updated; `git diff --stat docs/api/openapi.yaml` shows the `ytmusic` addition.

- [ ] **Step 4: Regenerate the frontend types**

Run: `cd frontend && pnpm api:types && cd ..`
Expected: `frontend/src/api/schema.d.ts` updated with the `ytmusic` object. (`pnpm api:types` runs `openapi-typescript ../docs/api/openapi.yaml -o src/api/schema.d.ts`.)

- [ ] **Step 5: Commit**

```bash
git add scripts/generate_openapi.py docs/api/openapi.yaml frontend/src/api/schema.d.ts
git commit -m "docs(api): add ytmusic match status to playlist tracks"
```

---

## Task 11: Backfill script

**Files:**
- Create: `scripts/backfill_vendor_match.py`

Admin-run script: for every track that sits in a playlist but lacks a `vendor_track_map[ytmusic]` row, enqueue a match job. Reuses the repo read + enqueue helper.

- [ ] **Step 1: Write the script**

```python
# scripts/backfill_vendor_match.py
"""Enqueue YT Music match jobs for tracks already in playlists.

Usage:
    PYTHONPATH=src VENDOR_MATCH_QUEUE_URL=<url> .venv/bin/python \
        scripts/backfill_vendor_match.py

Idempotent: tracks already in vendor_track_map[ytmusic] are skipped by
fetch_unmatched_match_inputs.
"""

from __future__ import annotations

import os
import sys

import boto3

from collector.curation.playlists_repository import create_default_playlists_repository
from collector.vendor_match.enqueue import YTMUSIC_VENDOR, enqueue_vendor_matches


def main() -> int:
    queue_url = os.environ.get("VENDOR_MATCH_QUEUE_URL", "").strip()
    if not queue_url:
        print("VENDOR_MATCH_QUEUE_URL is required", file=sys.stderr)
        return 2

    repo = create_default_playlists_repository()
    if repo is None:
        print("Data API not configured", file=sys.stderr)
        return 2

    track_ids = [
        r["track_id"]
        for r in repo.data_api.execute(
            "SELECT DISTINCT track_id FROM playlist_tracks", {}
        )
    ]
    if not track_ids:
        print("No playlist tracks found.")
        return 0

    sqs = boto3.client("sqs")
    total = 0
    batch = 100
    for start in range(0, len(track_ids), batch):
        chunk = track_ids[start : start + batch]
        inputs = repo.fetch_unmatched_match_inputs(track_ids=chunk, vendor=YTMUSIC_VENDOR)
        total += enqueue_vendor_matches(
            track_inputs=inputs, vendor=YTMUSIC_VENDOR,
            queue_url=queue_url, sqs=sqs, correlation_id="backfill",
        )
    print(f"Enqueued {total} ytmusic match jobs from {len(track_ids)} playlist tracks.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 2: Verify it imports cleanly**

Run: `PYTHONPATH=src .venv/bin/python -c "import scripts.backfill_vendor_match"` (or `python -c "import ast; ast.parse(open('scripts/backfill_vendor_match.py').read())"` if `scripts` is not a package)
Expected: no error.

- [ ] **Step 3: Commit**

```bash
git add scripts/backfill_vendor_match.py
git commit -m "feat(vendor-match): add ytmusic backfill script"
```

---

## Task 12: Infrastructure + docs

**Files:**
- Modify: `infra/curation.tf`
- Modify: `infra/variables.tf`
- Modify: `docs/backend/providers.md`

- [ ] **Step 1: Add the queue URL env to the curation Lambda**

In `infra/curation.tf`, inside the curation function's `environment.variables`, add:

```hcl
      VENDOR_MATCH_QUEUE_URL                    = aws_sqs_queue.vendor_match.url
```

(The shared `collector_lambda` role already grants `sqs:SendMessage` on `aws_sqs_queue.vendor_match.arn` — see `infra/iam.tf` `AllowSQSSend`. No IAM change.)

- [ ] **Step 2: Enable ytmusic on the worker**

In `infra/variables.tf`, update the `vendor_match_vendors_enabled` default so the worker can resolve the vendor:

```hcl
  default = "ytmusic"
```

If a deployed `.tfvars` sets this variable, add `ytmusic` to that comma-separated value (keep any existing vendors, e.g. `"spotify,ytmusic"`).

- [ ] **Step 3: Validate Terraform**

Run: `cd infra && terraform fmt && terraform validate && cd ..`
Expected: `Success! The configuration is valid.`

- [ ] **Step 4: Update the providers doc**

In `docs/backend/providers.md`, move `ytmusic` out of the "Stubbed Vendors" table and add a subsection under "Wrapped Vendors":

```markdown
### YT Music (`lookup`)

- **Bundle:** `ProviderBundle(lookup=YTMusicLookup(), export=YTMusicExporter())`
- **Adapter:** `src/collector/providers/ytmusic/lookup.py`
- **Underlying client:** `ytmusicapi.YTMusic` (unauthenticated search, built lazily)
- **Lookup role:** `LookupProvider` — `lookup_by_isrc` always returns `None`
  (YT has no public ISRC search); `lookup_by_metadata` runs a multi-pass search
  (`songs`, then `videos` fallback) and returns `VendorTrackRef` candidates for
  the shared fuzzy scorer. `lookup_batch_by_isrc` raises `not_implemented`.
- **Export role:** still a stub (playlist creation is out of scope).
```

- [ ] **Step 5: Commit**

```bash
git add infra/curation.tf infra/variables.tf docs/backend/providers.md
git commit -m "chore(infra): wire ytmusic vendor-match queue and worker"
```

---

## Task 13: Frontend — YT Music badge

**Files:**
- Create: `frontend/src/features/playlists/components/YtMusicBadge.tsx`
- Create: `frontend/src/features/playlists/components/__tests__/YtMusicBadge.browser.test.tsx`
- Modify: `frontend/src/features/playlists/lib/playlistTypes.ts`
- Modify: `frontend/src/features/playlists/components/PlaylistTrackRow.tsx`

- [ ] **Step 1: Add the type**

In `frontend/src/features/playlists/lib/playlistTypes.ts`, add above `PlaylistTrack`:

```ts
export type YtMusicMatchStatus = 'matched' | 'pending' | 'needs_review' | 'not_found';

export interface YtMusicMatch {
  status: YtMusicMatchStatus;
  video_id?: string | null;
  url?: string | null;
  confidence?: number | null;
}
```

Add the field to `PlaylistTrack` (after `tags`):

```ts
  ytmusic?: YtMusicMatch | null;
```

- [ ] **Step 2: Write the failing browser test**

```tsx
// frontend/src/features/playlists/components/__tests__/YtMusicBadge.browser.test.tsx
import { render, screen } from '@testing-library/react';
import { MantineProvider } from '@mantine/core';
import { describe, it, expect } from 'vitest';
import { YtMusicBadge } from '../YtMusicBadge';

function renderBadge(match: Parameters<typeof YtMusicBadge>[0]['match']) {
  return render(
    <MantineProvider>
      <YtMusicBadge match={match} />
    </MantineProvider>,
  );
}

describe('YtMusicBadge', () => {
  it('renders a link to YT Music when matched', () => {
    renderBadge({ status: 'matched', video_id: 'vid1', url: 'https://music.youtube.com/watch?v=vid1' });
    const link = screen.getByRole('link');
    expect(link).toHaveAttribute('href', 'https://music.youtube.com/watch?v=vid1');
  });

  it('renders no link for pending', () => {
    renderBadge({ status: 'pending' });
    expect(screen.queryByRole('link')).toBeNull();
  });

  it('renders nothing when match is null', () => {
    const { container } = renderBadge(null);
    expect(container.firstChild).toBeNull();
  });
});
```

- [ ] **Step 3: Run it to verify it fails**

Run: `cd frontend && pnpm test:browser -- YtMusicBadge && cd ..`
Expected: FAIL — `../YtMusicBadge` does not exist.

- [ ] **Step 4: Implement the badge**

```tsx
// frontend/src/features/playlists/components/YtMusicBadge.tsx
import { ActionIcon, Text, Tooltip } from '@mantine/core';
import {
  IconBrandYoutube,
  IconClock,
  IconHelpCircle,
  IconMusicOff,
} from '@tabler/icons-react';
import { useTranslation } from 'react-i18next';
import type { YtMusicMatch } from '../lib/playlistTypes';

export interface YtMusicBadgeProps {
  match: YtMusicMatch | null | undefined;
}

export function YtMusicBadge({ match }: YtMusicBadgeProps) {
  const { t } = useTranslation();
  if (!match) return null;

  if (match.status === 'matched' && match.url) {
    const pct = match.confidence != null ? ` (${Math.round(match.confidence * 100)}%)` : '';
    return (
      <Tooltip label={`${t('playlists.ytmusic.matched', 'YT Music')}${pct}`}>
        <ActionIcon
          component="a"
          href={match.url}
          target="_blank"
          rel="noopener noreferrer"
          variant="subtle"
          color="red"
          aria-label={t('playlists.ytmusic.matched', 'YT Music')}
        >
          <IconBrandYoutube size={18} />
        </ActionIcon>
      </Tooltip>
    );
  }

  const { icon, label, color } =
    match.status === 'needs_review'
      ? { icon: <IconHelpCircle size={18} />, label: t('playlists.ytmusic.needsReview', 'Needs review'), color: 'yellow' }
      : match.status === 'not_found'
        ? { icon: <IconMusicOff size={18} />, label: t('playlists.ytmusic.notFound', 'Not on YT Music'), color: 'gray' }
        : { icon: <IconClock size={18} />, label: t('playlists.ytmusic.pending', 'Searching YT Music…'), color: 'gray' };

  return (
    <Tooltip label={label}>
      <Text c={color} component="span" aria-label={label} style={{ display: 'inline-flex' }}>
        {icon}
      </Text>
    </Tooltip>
  );
}
```

- [ ] **Step 5: Render it in the track row**

In `frontend/src/features/playlists/components/PlaylistTrackRow.tsx`, import the badge:

```tsx
import { YtMusicBadge } from './YtMusicBadge';
```

Place `<YtMusicBadge match={track.ytmusic} />` in the trailing controls group, next to the existing external-link / play controls (near the `IconExternalLink` usage).

- [ ] **Step 6: Run the browser test to verify it passes**

Run: `cd frontend && pnpm test:browser -- YtMusicBadge && cd ..`
Expected: PASS (3 tests).

- [ ] **Step 7: Verify jsdom suite + existing row test still pass**

Run: `cd frontend && pnpm test -- PlaylistTrackRow && cd ..`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add frontend/src/features/playlists/lib/playlistTypes.ts frontend/src/features/playlists/components/YtMusicBadge.tsx frontend/src/features/playlists/components/__tests__/YtMusicBadge.browser.test.tsx frontend/src/features/playlists/components/PlaylistTrackRow.tsx
git commit -m "feat(playlists): show YT Music match badge per track"
```

---

## Task 14: Full suite + integration check

**Files:** none (verification only)

- [ ] **Step 1: Run the full backend suite**

Run: `PYTHONPATH=src python -m pytest -q`
Expected: all green. Pay attention to `tests/integration/test_vendor_match_flow.py` and `tests/integration/test_playlists_flow.py` — if either asserts an exact playlist-track response shape, update the expected dict to include `"ytmusic"`.

- [ ] **Step 2: Run the frontend suites**

Run: `cd frontend && pnpm test && pnpm test:browser && cd ..`
Expected: all green.

- [ ] **Step 3: Final commit (only if Step 1 required a fixture update)**

```bash
git add tests/integration/
git commit -m "test(vendor-match): include ytmusic status in flow fixtures"
```

---

## Self-Review Notes

- **Spec coverage:** §5.1 YTMusicLookup → Tasks 1–2; §5.2 dependency → Task 3; §5.3 producer → Tasks 6–8; §5.4 backfill → Task 11; §5.5 read API + `no_match` → Tasks 4, 5, 9, 10; §5.6 frontend → Task 13; §5.7 config → Task 12; error handling (§7) → Tasks 5, 7; testing (§8) → every task + Task 14.
- **No-ISRC contract** pinned by `test_isrc_lookup_always_none` (Task 2) and the registry test (Task 3).
- **Type consistency:** `MatchInput`/`YtmusicStatus` defined in Task 6/9 and consumed in Tasks 7/8/9/11; `YtMusicMatch` defined in Task 13 step 1 before use; `enqueue_vendor_matches` signature identical across Tasks 7, 8, 11; `fetch_unmatched_match_inputs` / `fetch_ytmusic_status` signatures identical across producer and read paths.

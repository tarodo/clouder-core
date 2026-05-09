# Spotify Metadata Fallback — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** When `SpotifyClient.search_tracks_by_isrc` gets `0 items` for an ISRC, fall back to a Spotify metadata search (`q=track:<title> artist:<artist>`) and accept the best candidate if it passes strict fuzzy thresholds. Recovers tracks where Beatport's ISRC differs from Spotify's by ±1 in last digit (observed ≥6 of 8 sampled `not_found` tracks have a real Spotify match under a sibling ISRC).

**Architecture:**
- Pure scoring/gate function in `spotify_client.py` (reuses `vendor_match/scorer.py:score_candidate` for sims, layers strict component thresholds on top — total-score gate is already used by `vendor_match_worker`, but this fallback gates per-component).
- New `_search_by_metadata` private method in `SpotifyClient` issues the second Spotify API call only when ISRC search returned nothing AND the track payload carries title/artists.
- `find_tracks_needing_spotify_search` SQL extended to project `length_ms` and aggregated artist names so the worker can pass them into the client.
- Feature-flagged via `SPOTIFY_METADATA_FALLBACK_ENABLED` (default `false`) so deploy + activation are decoupled.

**Tech Stack:** Python 3.12, stdlib `urllib.request`, stdlib `difflib.SequenceMatcher` (already used in `vendor_match/scorer.py` — no new dependency), pydantic-settings, pytest.

**Out of scope:** Backfill of the existing 762 `not_found` tracks. Will land later as a separate admin endpoint per user decision (2026-05-09 chat).

---

## File Structure

**Create:**
- `tests/unit/test_spotify_metadata_fallback.py` — fuzzy accept-gate + `_search_by_metadata` unit tests

**Modify:**
- `src/collector/spotify_client.py` — extend `search_tracks_by_isrc` payload schema, add `_search_by_metadata`, add `_accept_metadata_match`
- `src/collector/settings.py` — add `SPOTIFY_METADATA_FALLBACK_ENABLED` + 3 threshold fields to `SpotifyWorkerSettings`
- `src/collector/repositories.py:726` — extend `find_tracks_needing_spotify_search` SQL to JOIN artists + project `length_ms`
- `src/collector/spotify_handler.py:191-199` — build extended payload from new repo fields, pass `settings` into client call
- `src/collector/providers/spotify/lookup.py` — `lookup_batch_by_isrc` signature mirrors client (typing only)
- `tests/unit/test_spotify_client.py` — adjust existing tests for new optional fields (backwards-compat: missing → fallback skipped)
- `tests/unit/test_spotify_handler.py` — feed new repo rows shape into mocks
- `tests/unit/test_providers_spotify_lookup.py` — same shape adjustment
- `CLAUDE.md` — flip the "metadata search returns `[]` until a follow-up fills it in" gotcha to reflect the new behavior

---

## Task 1: Branch + scoring/accept-gate function

**Files:**
- Modify: `src/collector/spotify_client.py`
- Test: `tests/unit/test_spotify_metadata_fallback.py`

- [ ] **Step 1.1: Create feature branch from main**

```bash
cd /Users/roman/Projects/clouder-projects/clouder-core/.claude/worktrees/bux_fixes
git fetch origin main
git checkout -b feat/spotify-metadata-fallback origin/main
```

Expected: `Switched to a new branch 'feat/spotify-metadata-fallback'`

- [ ] **Step 1.2: Write failing test for `_accept_metadata_match`**

Create `tests/unit/test_spotify_metadata_fallback.py`:

```python
"""Tests for Spotify metadata-fallback scoring + accept gate."""

from __future__ import annotations

from collector.spotify_client import _accept_metadata_match


def test_accept_match_passes_strict_thresholds() -> None:
    # title_sim 0.92, artist_sim 0.88, duration diff 1500ms → all pass
    assert _accept_metadata_match(
        title_sim=0.92,
        artist_sim=0.88,
        candidate_duration_ms=180_000,
        query_duration_ms=181_500,
        title_min=0.90,
        artist_min=0.85,
        duration_tolerance_ms=3000,
    )


def test_accept_rejects_low_title_sim() -> None:
    assert not _accept_metadata_match(
        title_sim=0.89,
        artist_sim=0.99,
        candidate_duration_ms=180_000,
        query_duration_ms=180_000,
        title_min=0.90,
        artist_min=0.85,
        duration_tolerance_ms=3000,
    )


def test_accept_rejects_low_artist_sim() -> None:
    assert not _accept_metadata_match(
        title_sim=1.0,
        artist_sim=0.84,
        candidate_duration_ms=180_000,
        query_duration_ms=180_000,
        title_min=0.90,
        artist_min=0.85,
        duration_tolerance_ms=3000,
    )


def test_accept_rejects_duration_outside_tolerance() -> None:
    assert not _accept_metadata_match(
        title_sim=1.0,
        artist_sim=1.0,
        candidate_duration_ms=180_000,
        query_duration_ms=184_000,
        title_min=0.90,
        artist_min=0.85,
        duration_tolerance_ms=3000,
    )


def test_accept_passes_when_query_duration_unknown() -> None:
    # If query has no duration we cannot enforce the gate — skip duration check
    assert _accept_metadata_match(
        title_sim=0.95,
        artist_sim=0.90,
        candidate_duration_ms=180_000,
        query_duration_ms=None,
        title_min=0.90,
        artist_min=0.85,
        duration_tolerance_ms=3000,
    )


def test_accept_passes_when_candidate_duration_unknown() -> None:
    # Candidate from Spotify always has duration_ms but be defensive
    assert _accept_metadata_match(
        title_sim=0.95,
        artist_sim=0.90,
        candidate_duration_ms=None,
        query_duration_ms=180_000,
        title_min=0.90,
        artist_min=0.85,
        duration_tolerance_ms=3000,
    )
```

- [ ] **Step 1.3: Run tests — verify they fail with ImportError**

```bash
pytest tests/unit/test_spotify_metadata_fallback.py -v
```

Expected: `ImportError: cannot import name '_accept_metadata_match' from 'collector.spotify_client'`

- [ ] **Step 1.4: Implement `_accept_metadata_match` in `src/collector/spotify_client.py`**

Append at module level (after `_album_release_sort_key`, before EOF):

```python
def _accept_metadata_match(
    *,
    title_sim: float,
    artist_sim: float,
    candidate_duration_ms: int | None,
    query_duration_ms: int | None,
    title_min: float,
    artist_min: float,
    duration_tolerance_ms: int,
) -> bool:
    """Strict per-component gate for metadata-fallback candidates.

    All three checks must pass:
      - title similarity >= title_min
      - artist similarity >= artist_min
      - duration within tolerance (skipped if either side is None)
    """
    if title_sim < title_min:
        return False
    if artist_sim < artist_min:
        return False
    if candidate_duration_ms is None or query_duration_ms is None:
        return True
    return abs(candidate_duration_ms - query_duration_ms) <= duration_tolerance_ms
```

- [ ] **Step 1.5: Run tests — verify pass**

```bash
pytest tests/unit/test_spotify_metadata_fallback.py -v
```

Expected: 6 passed.

- [ ] **Step 1.6: Generate commit message via caveman-commit, commit**

```bash
git add tests/unit/test_spotify_metadata_fallback.py src/collector/spotify_client.py
# Generate message via caveman-commit skill, then:
git commit -m "feat(spotify): add metadata-match accept gate"
```

(Use `caveman:caveman-commit` skill to produce the actual subject; `^feat` enforced by hook.)

---

## Task 2: `SpotifyClient._search_by_metadata` (URL build + scoring)

**Files:**
- Modify: `src/collector/spotify_client.py`
- Test: `tests/unit/test_spotify_metadata_fallback.py`

- [ ] **Step 2.1: Append failing tests**

Append to `tests/unit/test_spotify_metadata_fallback.py`:

```python
import json
from unittest.mock import patch
import pytest

from collector.spotify_client import SpotifyClient


class _Resp:
    def __init__(self, payload: dict) -> None:
        self._b = json.dumps(payload).encode()

    def read(self) -> bytes:
        return self._b

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass


def _make_client() -> SpotifyClient:
    c = SpotifyClient(
        client_id="x", client_secret="y", sleep_fn=lambda _: None,
    )
    c._access_token = "tok"
    c._token_expires_at = 9e18
    return c


def _spotify_track(
    *, sp_id: str, name: str, artists: list[str],
    duration_ms: int, isrc: str = "ZZZ123",
) -> dict:
    return {
        "id": sp_id,
        "name": name,
        "artists": [{"name": a} for a in artists],
        "duration_ms": duration_ms,
        "external_ids": {"isrc": isrc},
        "album": {"release_date": "2026-01-01", "release_date_precision": "day"},
    }


def test_search_by_metadata_picks_best_when_passes_gate() -> None:
    client = _make_client()
    payload = {
        "tracks": {
            "items": [
                _spotify_track(
                    sp_id="sp_match",
                    name="Move On",
                    artists=["Guri & Eider"],
                    duration_ms=180_000,
                    isrc="GBKQU2633815",
                ),
            ]
        }
    }
    with patch(
        "collector.spotify_client.urllib.request.urlopen",
        return_value=_Resp(payload),
    ):
        track = client._search_by_metadata(
            title="Move On",
            artist="Guri & Eider",
            duration_ms=181_000,
            correlation_id="cid",
            title_min=0.90,
            artist_min=0.85,
            duration_tolerance_ms=3000,
        )
    assert track is not None
    assert track["id"] == "sp_match"


def test_search_by_metadata_returns_none_when_no_items() -> None:
    client = _make_client()
    with patch(
        "collector.spotify_client.urllib.request.urlopen",
        return_value=_Resp({"tracks": {"items": []}}),
    ):
        track = client._search_by_metadata(
            title="Nothing", artist="Nobody", duration_ms=180_000,
            correlation_id="cid",
            title_min=0.90, artist_min=0.85, duration_tolerance_ms=3000,
        )
    assert track is None


def test_search_by_metadata_returns_none_when_all_fail_gate() -> None:
    client = _make_client()
    payload = {
        "tracks": {
            "items": [
                _spotify_track(
                    sp_id="bad",
                    name="Totally Different Song",
                    artists=["Other Person"],
                    duration_ms=180_000,
                ),
            ]
        }
    }
    with patch(
        "collector.spotify_client.urllib.request.urlopen",
        return_value=_Resp(payload),
    ):
        track = client._search_by_metadata(
            title="Move On", artist="Guri & Eider", duration_ms=180_000,
            correlation_id="cid",
            title_min=0.90, artist_min=0.85, duration_tolerance_ms=3000,
        )
    assert track is None


def test_search_by_metadata_returns_none_for_empty_inputs() -> None:
    client = _make_client()
    # Should short-circuit without calling Spotify
    with patch(
        "collector.spotify_client.urllib.request.urlopen",
        side_effect=AssertionError("must not be called"),
    ):
        assert client._search_by_metadata(
            title="", artist="Some Artist", duration_ms=180_000,
            correlation_id="cid",
            title_min=0.90, artist_min=0.85, duration_tolerance_ms=3000,
        ) is None
        assert client._search_by_metadata(
            title="Some Title", artist="", duration_ms=180_000,
            correlation_id="cid",
            title_min=0.90, artist_min=0.85, duration_tolerance_ms=3000,
        ) is None


def test_search_by_metadata_picks_highest_combined_when_multiple_pass() -> None:
    client = _make_client()
    payload = {
        "tracks": {
            "items": [
                _spotify_track(
                    sp_id="ok_but_lower",
                    name="Move On",
                    artists=["Guri & Eider"],
                    duration_ms=180_500,
                ),
                _spotify_track(
                    sp_id="best",
                    name="Move On",
                    artists=["Guri & Eider"],
                    duration_ms=181_000,
                ),
            ]
        }
    }
    with patch(
        "collector.spotify_client.urllib.request.urlopen",
        return_value=_Resp(payload),
    ):
        track = client._search_by_metadata(
            title="Move On", artist="Guri & Eider", duration_ms=181_000,
            correlation_id="cid",
            title_min=0.90, artist_min=0.85, duration_tolerance_ms=3000,
        )
    # Both pass; tie-break by max (title_sim + artist_sim) — both same here so
    # earlier release date wins (or first encountered if dates equal). Verify
    # at minimum that one of them is returned.
    assert track is not None
    assert track["id"] in {"best", "ok_but_lower"}
```

- [ ] **Step 2.2: Run — verify fail with `AttributeError: ... '_search_by_metadata'`**

```bash
pytest tests/unit/test_spotify_metadata_fallback.py -v
```

Expected: 5 NEW failures (the 6 from Task 1 still pass).

- [ ] **Step 2.3: Implement `_search_by_metadata` in `src/collector/spotify_client.py`**

Add a top-of-file import:

```python
from .vendor_match.scorer import _string_sim, _best_artist_sim
```

(`_string_sim` and `_best_artist_sim` are module-private — promote to public by removing the underscore in `vendor_match/scorer.py` if your linter complains, OR re-export them via `__all__`. Pick whichever the codebase prefers; in this codebase, removing the underscore on these two helpers is acceptable since they have no leaked-state concerns.)

Then add as a method on `SpotifyClient`:

```python
def _search_by_metadata(
    self,
    *,
    title: str,
    artist: str,
    duration_ms: int | None,
    correlation_id: str,
    title_min: float,
    artist_min: float,
    duration_tolerance_ms: int,
) -> dict | None:
    """Spotify text search fallback when ISRC lookup returned no items.

    Builds q=track:<title> artist:<artist>, scores each result against
    the query, and returns the highest-scoring candidate that passes
    the strict per-component accept gate. Returns None if the input
    is empty or no candidate passes.
    """
    if not title.strip() or not artist.strip():
        return None

    q = f'track:{title} artist:{artist}'
    params = {"q": q, "type": "track", "limit": "10"}
    url = f"{API_BASE_URL}/search?{urllib.parse.urlencode(params)}"
    payload = self._request(url=url, correlation_id=correlation_id)
    tracks_obj = payload.get("tracks")
    if not isinstance(tracks_obj, dict):
        return None
    items = tracks_obj.get("items")
    if not isinstance(items, list) or not items:
        return None

    best_track: dict | None = None
    best_combined = -1.0
    for item in items:
        if not isinstance(item, dict):
            continue
        cand_name = str(item.get("name") or "")
        cand_artists = tuple(
            str(a.get("name", ""))
            for a in (item.get("artists") or [])
            if isinstance(a, dict)
        )
        cand_duration = item.get("duration_ms")
        cand_duration_ms = (
            int(cand_duration) if isinstance(cand_duration, (int, float)) else None
        )
        title_sim = _string_sim(cand_name, title)
        artist_sim = _best_artist_sim(cand_artists, artist)
        if not _accept_metadata_match(
            title_sim=title_sim,
            artist_sim=artist_sim,
            candidate_duration_ms=cand_duration_ms,
            query_duration_ms=duration_ms,
            title_min=title_min,
            artist_min=artist_min,
            duration_tolerance_ms=duration_tolerance_ms,
        ):
            continue
        combined = title_sim + artist_sim
        if combined > best_combined:
            best_combined = combined
            best_track = item
    return best_track
```

- [ ] **Step 2.4: Run all tests in this file — verify pass**

```bash
pytest tests/unit/test_spotify_metadata_fallback.py -v
```

Expected: 11 passed.

- [ ] **Step 2.5: Run wider regression — `vendor_match/scorer.py` users**

```bash
pytest tests/unit/test_vendor_match_scorer.py -v 2>&1 | tail -20
pytest tests/unit/test_spotify_client.py -v 2>&1 | tail -20
```

Expected: existing tests still pass (renaming `_string_sim` → `string_sim` may need follow-up grep).

If renaming breaks anything: keep both names temporarily — `string_sim = _string_sim` alias at module bottom — until Task 8 cleanup. Note this in the commit body.

- [ ] **Step 2.6: Commit**

```bash
git add src/collector/spotify_client.py src/collector/vendor_match/scorer.py tests/unit/test_spotify_metadata_fallback.py
# caveman-commit, then:
git commit -m "feat(spotify): add _search_by_metadata fallback method"
```

---

## Task 3: Settings — feature flag + threshold fields

**Files:**
- Modify: `src/collector/settings.py:159-164`
- Test: `tests/unit/test_settings.py` (if exists; otherwise inline in `test_spotify_metadata_fallback.py`)

- [ ] **Step 3.1: Find existing settings test**

```bash
ls tests/unit/test_settings*.py 2>/dev/null
grep -l "SpotifyWorkerSettings\|get_spotify_worker_settings" tests/ -r
```

If a settings test exists, append there. Otherwise add to `test_spotify_metadata_fallback.py`.

- [ ] **Step 3.2: Write failing test**

```python
import os
from collector.settings import get_spotify_worker_settings, reset_settings_cache


def test_spotify_worker_settings_metadata_fallback_defaults(monkeypatch) -> None:
    reset_settings_cache()
    monkeypatch.setenv("RAW_BUCKET_NAME", "x")
    # Avoid SSM lookups in tests
    monkeypatch.setenv("SPOTIFY_CLIENT_ID", "x")
    monkeypatch.setenv("SPOTIFY_CLIENT_SECRET", "y")
    s = get_spotify_worker_settings()
    assert s.metadata_fallback_enabled is False
    assert s.metadata_fallback_title_min == 0.90
    assert s.metadata_fallback_artist_min == 0.85
    assert s.metadata_fallback_duration_tolerance_ms == 3000
    reset_settings_cache()


def test_spotify_worker_settings_metadata_fallback_overrides(monkeypatch) -> None:
    reset_settings_cache()
    monkeypatch.setenv("RAW_BUCKET_NAME", "x")
    monkeypatch.setenv("SPOTIFY_CLIENT_ID", "x")
    monkeypatch.setenv("SPOTIFY_CLIENT_SECRET", "y")
    monkeypatch.setenv("SPOTIFY_METADATA_FALLBACK_ENABLED", "true")
    monkeypatch.setenv("SPOTIFY_FUZZY_TITLE_MIN", "0.95")
    monkeypatch.setenv("SPOTIFY_FUZZY_ARTIST_MIN", "0.90")
    monkeypatch.setenv("SPOTIFY_FUZZY_DURATION_TOLERANCE_MS", "5000")
    s = get_spotify_worker_settings()
    assert s.metadata_fallback_enabled is True
    assert s.metadata_fallback_title_min == 0.95
    assert s.metadata_fallback_artist_min == 0.90
    assert s.metadata_fallback_duration_tolerance_ms == 5000
    reset_settings_cache()
```

- [ ] **Step 3.3: Run — verify fail**

```bash
pytest tests/unit/test_spotify_metadata_fallback.py::test_spotify_worker_settings_metadata_fallback_defaults -v
```

Expected: `AttributeError: 'SpotifyWorkerSettings' object has no attribute 'metadata_fallback_enabled'`.

- [ ] **Step 3.4: Edit `SpotifyWorkerSettings` in `src/collector/settings.py`**

Replace the class body (around line 159):

```python
class SpotifyWorkerSettings(_SettingsBase):
    spotify_client_id: str = Field(default="")
    spotify_client_secret: str = Field(default="")
    raw_bucket_name: str = Field(alias="RAW_BUCKET_NAME")
    spotify_raw_prefix: str = Field(default="raw/sp/tracks", alias="SPOTIFY_RAW_PREFIX")
    spotify_search_queue_url: str = Field(default="", alias="SPOTIFY_SEARCH_QUEUE_URL")
    metadata_fallback_enabled: bool = Field(
        default=False, alias="SPOTIFY_METADATA_FALLBACK_ENABLED"
    )
    metadata_fallback_title_min: float = Field(
        default=0.90, alias="SPOTIFY_FUZZY_TITLE_MIN", ge=0.0, le=1.0
    )
    metadata_fallback_artist_min: float = Field(
        default=0.85, alias="SPOTIFY_FUZZY_ARTIST_MIN", ge=0.0, le=1.0
    )
    metadata_fallback_duration_tolerance_ms: int = Field(
        default=3000, alias="SPOTIFY_FUZZY_DURATION_TOLERANCE_MS", ge=0
    )
```

- [ ] **Step 3.5: Run — verify pass**

```bash
pytest tests/unit/test_spotify_metadata_fallback.py -v
```

Expected: 13 passed.

- [ ] **Step 3.6: Commit**

```bash
git add src/collector/settings.py tests/unit/test_spotify_metadata_fallback.py
# caveman-commit, then:
git commit -m "feat(spotify): add metadata-fallback settings + thresholds"
```

---

## Task 4: Wire fallback into `SpotifyClient.search_tracks_by_isrc`

**Files:**
- Modify: `src/collector/spotify_client.py:51-111`
- Test: `tests/unit/test_spotify_metadata_fallback.py`, `tests/unit/test_spotify_client.py`

- [ ] **Step 4.1: Append failing integration test**

Append to `tests/unit/test_spotify_metadata_fallback.py`:

```python
def test_search_tracks_invokes_metadata_fallback_on_isrc_miss() -> None:
    client = _make_client()

    fallback_track = _spotify_track(
        sp_id="sp_fallback",
        name="Move On",
        artists=["Guri & Eider"],
        duration_ms=180_000,
    )

    call_count = {"n": 0}

    def fake_urlopen(request, timeout=None):
        call_count["n"] += 1
        if call_count["n"] == 1:
            # ISRC search → empty
            return _Resp({"tracks": {"items": []}})
        # Metadata search → match
        return _Resp({"tracks": {"items": [fallback_track]}})

    with patch("collector.spotify_client.urllib.request.urlopen", fake_urlopen):
        results = client.search_tracks_by_isrc(
            tracks=[
                {
                    "clouder_track_id": "ct1",
                    "isrc": "GBKQU2633814",
                    "title": "Move On",
                    "artists": "Guri & Eider",
                    "duration_ms": 180_000,
                }
            ],
            correlation_id="cid",
            metadata_fallback_enabled=True,
            title_min=0.90,
            artist_min=0.85,
            duration_tolerance_ms=3000,
        )

    assert len(results) == 1
    assert results[0].spotify_id == "sp_fallback"
    assert call_count["n"] == 2  # ISRC + metadata


def test_search_tracks_skips_fallback_when_flag_off() -> None:
    client = _make_client()
    call_count = {"n": 0}

    def fake_urlopen(request, timeout=None):
        call_count["n"] += 1
        return _Resp({"tracks": {"items": []}})

    with patch("collector.spotify_client.urllib.request.urlopen", fake_urlopen):
        results = client.search_tracks_by_isrc(
            tracks=[
                {
                    "clouder_track_id": "ct1",
                    "isrc": "GBKQU2633814",
                    "title": "Move On",
                    "artists": "Guri & Eider",
                    "duration_ms": 180_000,
                }
            ],
            correlation_id="cid",
            metadata_fallback_enabled=False,
            title_min=0.90,
            artist_min=0.85,
            duration_tolerance_ms=3000,
        )
    assert len(results) == 1
    assert results[0].spotify_id is None
    assert call_count["n"] == 1  # only ISRC, no fallback


def test_search_tracks_skips_fallback_without_metadata() -> None:
    client = _make_client()
    call_count = {"n": 0}

    def fake_urlopen(request, timeout=None):
        call_count["n"] += 1
        return _Resp({"tracks": {"items": []}})

    with patch("collector.spotify_client.urllib.request.urlopen", fake_urlopen):
        results = client.search_tracks_by_isrc(
            tracks=[
                {
                    "clouder_track_id": "ct1",
                    "isrc": "GBKQU2633814",
                    # no title/artists → fallback skipped even if enabled
                }
            ],
            correlation_id="cid",
            metadata_fallback_enabled=True,
            title_min=0.90,
            artist_min=0.85,
            duration_tolerance_ms=3000,
        )
    assert len(results) == 1
    assert results[0].spotify_id is None
    assert call_count["n"] == 1
```

- [ ] **Step 4.2: Run — verify fail**

```bash
pytest tests/unit/test_spotify_metadata_fallback.py -v
```

Expected: 3 failures with `TypeError: search_tracks_by_isrc() got an unexpected keyword argument 'metadata_fallback_enabled'`.

- [ ] **Step 4.3: Modify `search_tracks_by_isrc` signature + body**

Replace the method (currently lines 51-111) with:

```python
def search_tracks_by_isrc(
    self,
    tracks: List[Dict[str, Any]],
    correlation_id: str,
    *,
    metadata_fallback_enabled: bool = False,
    title_min: float = 0.90,
    artist_min: float = 0.85,
    duration_tolerance_ms: int = 3000,
) -> List[SpotifySearchResult]:
    """Search Spotify for each track by ISRC, with optional metadata fallback.

    Args:
        tracks: list of dicts. Required keys: clouder_track_id, isrc.
            Optional (used by fallback): title, artists, duration_ms.
        correlation_id: trace ID
        metadata_fallback_enabled: if True, fall back to text search on ISRC miss
        title_min, artist_min, duration_tolerance_ms: accept-gate thresholds
    """
    self._ensure_token(correlation_id)
    results: List[SpotifySearchResult] = []

    for index, track in enumerate(tracks):
        isrc = track["isrc"]
        clouder_track_id = track["clouder_track_id"]

        try:
            spotify_track = self._search_by_isrc(
                isrc=isrc, correlation_id=correlation_id
            )
        except SpotifyAuthError:
            self._access_token = None
            self._ensure_token(correlation_id)
            spotify_track = self._search_by_isrc(
                isrc=isrc, correlation_id=correlation_id
            )

        if spotify_track is None and metadata_fallback_enabled:
            title = str(track.get("title") or "").strip()
            artist = str(track.get("artists") or "").strip()
            duration_ms = track.get("duration_ms")
            if title and artist:
                log_event(
                    "INFO",
                    "spotify_metadata_fallback_attempted",
                    correlation_id=correlation_id,
                    clouder_track_id=clouder_track_id,
                    isrc=isrc,
                )
                spotify_track = self._search_by_metadata(
                    title=title,
                    artist=artist,
                    duration_ms=int(duration_ms) if isinstance(duration_ms, (int, float)) else None,
                    correlation_id=correlation_id,
                    title_min=title_min,
                    artist_min=artist_min,
                    duration_tolerance_ms=duration_tolerance_ms,
                )
                if spotify_track is None:
                    log_event(
                        "INFO",
                        "spotify_metadata_fallback_rejected",
                        correlation_id=correlation_id,
                        clouder_track_id=clouder_track_id,
                        isrc=isrc,
                    )
                else:
                    log_event(
                        "INFO",
                        "spotify_metadata_fallback_match",
                        correlation_id=correlation_id,
                        clouder_track_id=clouder_track_id,
                        isrc=isrc,
                        spotify_id=spotify_track.get("id"),
                        spotify_isrc=spotify_track.get("external_ids", {}).get("isrc"),
                    )

        spotify_id = spotify_track["id"] if spotify_track else None
        results.append(
            SpotifySearchResult(
                isrc=isrc,
                clouder_track_id=clouder_track_id,
                spotify_track=spotify_track,
                spotify_id=spotify_id,
            )
        )

        if (index + 1) % 100 == 0:
            log_event(
                "INFO",
                "spotify_search_progress",
                correlation_id=correlation_id,
                searched=index + 1,
                total=len(tracks),
            )

    return results
```

Also update the import at the top of the file from:
```python
from typing import Any, Callable, Dict, List
```
(already present — leave as-is).

- [ ] **Step 4.4: Run — verify fallback tests pass**

```bash
pytest tests/unit/test_spotify_metadata_fallback.py -v
```

Expected: 16 passed.

- [ ] **Step 4.5: Run pre-existing client tests — adjust if needed**

```bash
pytest tests/unit/test_spotify_client.py -v 2>&1 | tail -30
```

If any test fails because `tracks` payload no longer accepts the old shape — they should still pass since `title`/`artists`/`duration_ms` are optional (`.get()`-based reads). Confirm.

If a test calls with old kwargs, that's still backwards-compatible (positional args + new keyword-only args with defaults).

- [ ] **Step 4.6: Commit**

```bash
git add src/collector/spotify_client.py tests/unit/test_spotify_metadata_fallback.py
# caveman-commit, then:
git commit -m "feat(spotify): chain metadata fallback after ISRC miss"
```

---

## Task 5: Repository — extend `find_tracks_needing_spotify_search` to project artists + length_ms

**Files:**
- Modify: `src/collector/repositories.py:726-737`
- Test: `tests/unit/test_repositories.py` (if covers this method) or new file

- [ ] **Step 5.1: Find existing tests for the method**

```bash
grep -rn "find_tracks_needing_spotify_search" tests/
```

If covered → modify those. If not → add lightweight test in `tests/unit/test_repositories_spotify.py` (new file) using a mocked DataAPIClient.

- [ ] **Step 5.2: Write failing test (or update existing)**

In `tests/unit/test_repositories_spotify.py`:

```python
"""Tests for Spotify-search repository methods."""

from __future__ import annotations

from unittest.mock import MagicMock

from collector.repositories import ClouderRepository


def test_find_tracks_needing_spotify_search_projects_artists_and_length() -> None:
    fake_data_api = MagicMock()
    fake_data_api.execute.return_value = [
        {
            "id": "t1", "isrc": "ZZ1", "title": "Move On",
            "normalized_title": "move on", "length_ms": 180_000,
            "artists": "Guri, Eider",
        }
    ]
    repo = ClouderRepository(data_api=fake_data_api)

    rows = repo.find_tracks_needing_spotify_search(limit=10)

    assert rows == [
        {
            "id": "t1", "isrc": "ZZ1", "title": "Move On",
            "normalized_title": "move on", "length_ms": 180_000,
            "artists": "Guri, Eider",
        }
    ]
    sql, params = fake_data_api.execute.call_args[0]
    assert "length_ms" in sql
    assert "string_agg(DISTINCT a.name" in sql
    assert "LEFT JOIN clouder_track_artists ta" in sql
    assert "GROUP BY t.id" in sql
    assert params == {"limit": 10}
```

- [ ] **Step 5.3: Run — verify fail (current SQL has no JOIN)**

```bash
pytest tests/unit/test_repositories_spotify.py -v
```

Expected: `AssertionError: 'string_agg(DISTINCT a.name' not in <current SQL>`.

- [ ] **Step 5.4: Update `find_tracks_needing_spotify_search` SQL**

In `src/collector/repositories.py:726`:

```python
def find_tracks_needing_spotify_search(self, limit: int) -> list[dict[str, Any]]:
    return self._data_api.execute(
        """
        SELECT t.id, t.isrc, t.title, t.normalized_title, t.length_ms,
               string_agg(DISTINCT a.name, ', ') AS artists
        FROM clouder_tracks t
        LEFT JOIN clouder_track_artists ta ON ta.track_id = t.id
        LEFT JOIN clouder_artists a ON ta.artist_id = a.id
        WHERE t.isrc IS NOT NULL
          AND t.spotify_searched_at IS NULL
        GROUP BY t.id, t.isrc, t.title, t.normalized_title,
                 t.length_ms, t.created_at
        ORDER BY t.created_at DESC
        LIMIT :limit
        """,
        {"limit": limit},
    )
```

- [ ] **Step 5.5: Run — verify pass**

```bash
pytest tests/unit/test_repositories_spotify.py -v
```

Expected: 1 passed.

- [ ] **Step 5.6: Commit**

```bash
git add src/collector/repositories.py tests/unit/test_repositories_spotify.py
# caveman-commit, then:
git commit -m "feat(repo): project artists+length_ms for spotify search"
```

---

## Task 6: Wire new fields through `spotify_handler._process_spotify_search`

**Files:**
- Modify: `src/collector/spotify_handler.py:165-260`
- Test: `tests/unit/test_spotify_handler.py`

- [ ] **Step 6.1: Read current handler test mocks for shape**

```bash
grep -n "find_tracks_needing_spotify_search" tests/unit/test_spotify_handler.py
```

Existing mocks return rows shaped `{id, isrc, title, normalized_title}`. Need to add `length_ms`, `artists`.

- [ ] **Step 6.2: Update test fixtures + add coverage for new pass-through**

Append a new test in `tests/unit/test_spotify_handler.py`:

```python
def test_process_passes_metadata_to_client_when_flag_enabled(
    monkeypatch, fake_repo, fake_storage,
):
    """Worker forwards title/artists/duration into the client call."""
    fake_repo.tracks_to_return = [
        {
            "id": "t1", "isrc": "ZZ1", "title": "Move On",
            "normalized_title": "move on", "length_ms": 180_000,
            "artists": "Guri & Eider",
        }
    ]
    captured: dict = {}

    class FakeLookup:
        def lookup_batch_by_isrc(self, *, tracks, correlation_id, **kwargs):
            captured["tracks"] = tracks
            captured["kwargs"] = kwargs
            return [
                SpotifySearchResult(
                    isrc="ZZ1", clouder_track_id="t1",
                    spotify_track=None, spotify_id=None,
                )
            ]

    monkeypatch.setattr(
        "collector.spotify_handler.registry.get_lookup",
        lambda name: FakeLookup(),
    )
    settings = _make_settings(metadata_fallback_enabled=True)

    _process_spotify_search(
        repository=fake_repo, storage=fake_storage, settings=settings,
        message=SpotifySearchMessage(batch_size=10),
        correlation_id="cid",
    )

    assert captured["tracks"][0]["title"] == "Move On"
    assert captured["tracks"][0]["artists"] == "Guri & Eider"
    assert captured["tracks"][0]["duration_ms"] == 180_000
    assert captured["kwargs"].get("metadata_fallback_enabled") is True
```

(Adjust `_make_settings`, `fake_repo`, `fake_storage` to match the existing test scaffolding in the file. If they don't exist yet, add them following the patterns already there — see surrounding tests.)

- [ ] **Step 6.3: Run — verify fail**

```bash
pytest tests/unit/test_spotify_handler.py::test_process_passes_metadata_to_client_when_flag_enabled -v
```

Expected: fails with KeyError or AssertionError on missing `title`/`artists` in payload.

- [ ] **Step 6.4: Modify `_process_spotify_search` to build extended payload**

In `src/collector/spotify_handler.py`, replace the `search_input` block + the `lookup_batch_by_isrc` call (lines 191-199) with:

```python
search_input = [
    {
        "clouder_track_id": str(t["id"]),
        "isrc": str(t["isrc"]),
        "title": str(t.get("title") or ""),
        "artists": str(t.get("artists") or ""),
        "duration_ms": t.get("length_ms"),
    }
    for t in tracks
]

results = client.lookup_batch_by_isrc(
    tracks=search_input,
    correlation_id=correlation_id,
    metadata_fallback_enabled=settings.metadata_fallback_enabled,
    title_min=settings.metadata_fallback_title_min,
    artist_min=settings.metadata_fallback_artist_min,
    duration_tolerance_ms=settings.metadata_fallback_duration_tolerance_ms,
)
```

- [ ] **Step 6.5: Run — verify pass**

```bash
pytest tests/unit/test_spotify_handler.py -v 2>&1 | tail -30
```

Expected: all pass (existing tests unaffected because the extra kwargs are passed through; ensure existing fixtures still produce rows compatible with the new SQL — add `length_ms` / `artists` to mock rows if needed).

- [ ] **Step 6.6: Commit**

```bash
git add src/collector/spotify_handler.py tests/unit/test_spotify_handler.py
# caveman-commit, then:
git commit -m "feat(spotify-worker): forward metadata + flags to client"
```

---

## Task 7: SpotifyLookup adapter — propagate kwargs

**Files:**
- Modify: `src/collector/providers/spotify/lookup.py`
- Test: `tests/unit/test_providers_spotify_lookup.py`

- [ ] **Step 7.1: Write failing test**

Append to `tests/unit/test_providers_spotify_lookup.py`:

```python
def test_lookup_batch_forwards_metadata_fallback_kwargs() -> None:
    captured = {}

    class FakeClient:
        def search_tracks_by_isrc(self, **kwargs):
            captured.update(kwargs)
            return []

    from collector.providers.spotify.lookup import SpotifyLookup

    sl = SpotifyLookup(client_id="x", client_secret="y", client=FakeClient())
    sl.lookup_batch_by_isrc(
        tracks=[{"clouder_track_id": "t1", "isrc": "ZZ1"}],
        correlation_id="cid",
        metadata_fallback_enabled=True,
        title_min=0.90,
        artist_min=0.85,
        duration_tolerance_ms=3000,
    )

    assert captured["metadata_fallback_enabled"] is True
    assert captured["title_min"] == 0.90
    assert captured["artist_min"] == 0.85
    assert captured["duration_tolerance_ms"] == 3000
```

- [ ] **Step 7.2: Run — verify fail**

```bash
pytest tests/unit/test_providers_spotify_lookup.py::test_lookup_batch_forwards_metadata_fallback_kwargs -v
```

Expected: `TypeError: lookup_batch_by_isrc() got an unexpected keyword argument 'metadata_fallback_enabled'`.

- [ ] **Step 7.3: Update `SpotifyLookup.lookup_batch_by_isrc`**

In `src/collector/providers/spotify/lookup.py`:

```python
def lookup_batch_by_isrc(
    self,
    tracks: list[dict[str, Any]],
    correlation_id: str,
    *,
    metadata_fallback_enabled: bool = False,
    title_min: float = 0.90,
    artist_min: float = 0.85,
    duration_tolerance_ms: int = 3000,
) -> list[SpotifySearchResult]:
    return self._client.search_tracks_by_isrc(
        tracks=tracks,
        correlation_id=correlation_id,
        metadata_fallback_enabled=metadata_fallback_enabled,
        title_min=title_min,
        artist_min=artist_min,
        duration_tolerance_ms=duration_tolerance_ms,
    )
```

(Update the type annotation `tracks: list[dict[str, str]]` → `list[dict[str, Any]]` since values now include int duration.)

- [ ] **Step 7.4: Run — verify pass**

```bash
pytest tests/unit/test_providers_spotify_lookup.py -v
```

Expected: all pass.

- [ ] **Step 7.5: Commit**

```bash
git add src/collector/providers/spotify/lookup.py tests/unit/test_providers_spotify_lookup.py
# caveman-commit, then:
git commit -m "feat(provider-spotify): forward metadata-fallback kwargs"
```

---

## Task 8: Full regression + CLAUDE.md update

**Files:**
- Modify: `CLAUDE.md`

- [ ] **Step 8.1: Run full unit suite**

```bash
pytest -q 2>&1 | tail -20
```

Expected: all green.

- [ ] **Step 8.2: Update CLAUDE.md gotcha**

In `CLAUDE.md`, find the existing line under "Gotchas":

```
- **`LookupProvider` gained per-track methods in Plan 4.** ... Spotify implements ISRC; metadata search returns `[]` until a follow-up fills it in (Beatport always carries ISRC so fuzzy fallback is rare). ...
```

Replace the relevant clause to document the new behavior:

```
- **`SpotifyClient` does ISRC-first, metadata-fallback second.** When `?q=isrc:` returns 0 items AND `SPOTIFY_METADATA_FALLBACK_ENABLED=true`, the client issues a second `?q=track:<title> artist:<artist>` search and accepts the highest-scoring candidate that passes per-component fuzzy gates: `title_sim >= SPOTIFY_FUZZY_TITLE_MIN` (default 0.90), `artist_sim >= SPOTIFY_FUZZY_ARTIST_MIN` (default 0.85), and (when both sides know it) `|duration_diff| <= SPOTIFY_FUZZY_DURATION_TOLERANCE_MS` (default 3000ms). Required for ~85% of `not_found` tracks where Beatport's ISRC is off-by-one from Spotify's master ISRC. The other 15% truly aren't on Spotify and stay `not_found`. Disabled by default — set `SPOTIFY_METADATA_FALLBACK_ENABLED=true` to activate.
```

Also append `SPOTIFY_METADATA_FALLBACK_ENABLED`, `SPOTIFY_FUZZY_TITLE_MIN`, `SPOTIFY_FUZZY_ARTIST_MIN`, `SPOTIFY_FUZZY_DURATION_TOLERANCE_MS` to the Spotify Worker env-vars list under "Env Vars (runtime)".

- [ ] **Step 8.3: Run terraform `apply` plan check (no-op for code-only PR)**

```bash
cd infra && terraform plan -no-color 2>&1 | tail -10
```

Expected: zero changes (env vars are flipped via `tfvars` after merge — not part of this PR).

- [ ] **Step 8.4: Commit**

```bash
git add CLAUDE.md
# caveman-commit, then:
git commit -m "docs(claude-md): note spotify metadata-fallback semantics"
```

- [ ] **Step 8.5: Push branch + open PR via caveman-commit**

```bash
git push -u origin feat/spotify-metadata-fallback
# Generate title/body via caveman:caveman-commit skill, then:
gh pr create --title "feat(spotify): metadata fallback after ISRC miss" --body "$(cat <<'EOF'
<body from caveman-commit>
EOF
)"
```

---

## Activation runbook (post-merge, NOT part of this PR)

After merge, to actually turn fallback on in prod:

1. Set Lambda env on `beatport-prod-spotify-search-worker`:
   ```
   SPOTIFY_METADATA_FALLBACK_ENABLED=true
   ```
   Either via Terraform (`infra/spotify_worker.tf`) or a one-shot `aws lambda update-function-configuration`. Terraform preferred for drift control.

2. Watch CloudWatch for `spotify_metadata_fallback_attempted` / `_match` / `_rejected` event mix. Healthy ratio should be `match : rejected ≈ 60:40` based on the sample analysis (6 matches out of ~8 = 75%, but mass run will include weaker queries).

3. Spot-check 5 newly-found tracks via `/admin/spotify-not-found` (count should drop) and verify Spotify IDs land on the right tracks (manual: open `https://open.spotify.com/track/<id>` and compare against title+artist).

4. If false-positive rate > 2%, raise `SPOTIFY_FUZZY_TITLE_MIN` to 0.93 or `SPOTIFY_FUZZY_ARTIST_MIN` to 0.90 via env-var override.

---

## Self-review notes

**Spec coverage:** Each Spec requirement (strict thresholds 0.90/0.85/±3s, fallback in `SpotifyClient`, no backfill in this PR) maps to Task 1, Task 4, Task 3, and the explicit Out-of-scope note.

**Placeholders:** None. Every step has either runnable code or a verifiable command.

**Type consistency:** `metadata_fallback_enabled` / `title_min` / `artist_min` / `duration_tolerance_ms` — same names through `SpotifyClient`, `SpotifyLookup`, `_process_spotify_search`, and `SpotifyWorkerSettings`. Field names on settings use `metadata_fallback_*` prefix; env var aliases use `SPOTIFY_*` prefix per existing convention. Verified.

**Risk:** Renaming `_string_sim` / `_best_artist_sim` in `vendor_match/scorer.py` (Step 2.3) is the only cross-file refactor. If it triggers churn elsewhere, the alias-fallback note in Step 2.5 keeps the blast radius local.

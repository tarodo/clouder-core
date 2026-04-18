# Vendor-Sync Plan 2 — Ingestion Enrichment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `release_type` (single/ep/album/compilation) and `is_ai_suspected` soft-filter flags to canonical entities, populated from Beatport + Spotify enrichment.

**Architecture:** A new alembic migration adds columns to `clouder_tracks`, `clouder_albums`, `clouder_labels`, `clouder_artists`. `NormalizedAlbum` grows `release_type`; `canonicalize.py` maps Beatport fields to the canonical value. A new `reconcile_release_type` phase runs after Spotify ISRC lookup, preferring Spotify's `album.album_type` for compilation detection. A propagation step on `ai_search_results` insert sets `is_ai_suspected` on the matching canonical row.

**Tech Stack:** Python 3.12, SQLAlchemy 2, Alembic, pydantic v2, Postgres 16.

**Spec:** [docs/superpowers/specs/2026-04-18-vendor-sync-readiness-design.md](../specs/2026-04-18-vendor-sync-readiness-design.md) §5.2 (column additions), §6.1 (Beatport release_type), §6.2 (Spotify reconcile), §6.3 (AI flag propagation).

**Prereqs:**
- Plan 1 merged (generic search worker, SSM, IAM auth).
- Operator has access to run `scripts/inspect_raw_sample.py` locally (AWS creds to pull one S3 object).

---

## File Structure

Files this plan creates:
- `scripts/inspect_raw_sample.py` — dev-only CLI to dump Beatport release fields.
- `alembic/versions/20260420_09_release_type_and_ai_flag.py` — schema migration.
- `tests/unit/test_release_type_mapping.py` — Beatport → canonical mapping rules.
- `tests/unit/test_reconcile_release_type.py` — Beatport × Spotify conflict matrix.
- `tests/unit/test_ai_flag_propagation.py` — set/clear behaviour of `is_ai_suspected`.

Files this plan modifies:
- `src/collector/db_models.py` — add columns.
- `src/collector/models.py` — `NormalizedAlbum.release_type`, `NormalizedTrack.release_type`.
- `src/collector/normalize.py` — extract `release_type` from Beatport payload.
- `src/collector/canonicalize.py` — write `release_type` on tracks+albums; call `reconcile_release_type` after Spotify phase; propagate `is_ai_suspected` after AI result save.
- `src/collector/spotify_handler.py` — extract `album.album_type` alongside `spotify_id`.
- `src/collector/repositories.py` — update commands for new columns; new methods `update_album_release_type`, `update_label_is_ai_suspected`.
- `src/collector/settings.py` — add `AI_FLAG_CONFIDENCE_THRESHOLD` and `COMPILATION_ARTIST_THRESHOLD`.

---

## Task 1: Inspect raw Beatport sample (one-shot script)

Before coding mapping rules, pin them to real Beatport response shape.

**Files:**
- Create: `scripts/inspect_raw_sample.py`

- [ ] **Step 1: Write the script**

```python
#!/usr/bin/env python3
"""Download one raw releases.json.gz from S3, print fields relevant to release_type.

Usage:
    python scripts/inspect_raw_sample.py <s3_key>
    # e.g. raw/bp/releases/style_id=5/year=2026/week=9/releases.json.gz
"""
from __future__ import annotations

import gzip
import json
import os
import sys
from collections import Counter

import boto3


def main(s3_key: str) -> None:
    bucket = os.environ["RAW_BUCKET_NAME"]
    s3 = boto3.client("s3")
    body = s3.get_object(Bucket=bucket, Key=s3_key)["Body"].read()
    payload = json.loads(gzip.decompress(body))

    releases = payload.get("releases") or payload.get("data") or []
    print(f"Total releases: {len(releases)}")

    type_counter: Counter[str] = Counter()
    keys_seen: Counter[str] = Counter()
    va_flags = 0

    for release in releases[:50]:
        keys_seen.update(release.keys())
        for field in ("type", "release_type", "is_compilation", "various_artists"):
            if field in release:
                val = release[field]
                type_counter[f"{field}={val}"] += 1
        artists = release.get("artists") or []
        if isinstance(artists, list) and len(artists) >= 4:
            va_flags += 1

    print("\nTop-level keys frequency (first 50):")
    for k, v in keys_seen.most_common(30):
        print(f"  {k}: {v}")

    print("\nType-related field values:")
    for k, v in type_counter.most_common():
        print(f"  {k}: {v}")

    print(f"\nReleases with >=4 artists (VA heuristic hit): {va_flags}")

    print("\nFirst release (pretty):")
    print(json.dumps(releases[0], indent=2, ensure_ascii=False)[:2000])


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("Usage: inspect_raw_sample.py <s3_key>")
    main(sys.argv[1])
```

- [ ] **Step 2: Run against a real object**

```bash
export RAW_BUCKET_NAME=beatport-prod-raw-223458487728
python scripts/inspect_raw_sample.py raw/bp/releases/style_id=5/year=2026/week=9/releases.json.gz | tee /tmp/inspect.txt
```

Expected output: counts of `type=...`, `release_type=...`, and similar keys. Use this to decide the mapping in Task 4.

- [ ] **Step 3: Commit**

```bash
git add scripts/inspect_raw_sample.py
git commit -m "<caveman-commit output>"
```

(Use `caveman:caveman-commit` skill for subject. No test — dev-only one-shot script.)

---

## Task 2: Alembic migration — add columns

**Files:**
- Create: `alembic/versions/20260420_09_release_type_and_ai_flag.py`
- Test: `tests/unit/test_migration_09_sql.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_migration_09_sql.py`:

```python
from __future__ import annotations

import importlib.util
from pathlib import Path


def _load_migration(filename: str):
    path = Path(__file__).resolve().parents[2] / "alembic" / "versions" / filename
    spec = importlib.util.spec_from_file_location("migration_under_test", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_migration_09_revision_chain() -> None:
    module = _load_migration("20260420_09_release_type_and_ai_flag.py")
    assert module.revision == "20260420_09"
    assert module.down_revision == "20260419_08"


def test_migration_09_adds_expected_columns() -> None:
    path = (
        Path(__file__).resolve().parents[2]
        / "alembic" / "versions"
        / "20260420_09_release_type_and_ai_flag.py"
    )
    text = path.read_text()
    assert "clouder_tracks" in text and "release_type" in text
    assert "clouder_tracks" in text and "is_ai_suspected" in text
    assert "clouder_albums" in text and "release_type" in text
    assert "clouder_labels" in text and "is_ai_suspected" in text
    assert "clouder_artists" in text and "is_ai_suspected" in text
```

- [ ] **Step 2: Run, confirm FAIL**

```bash
pytest tests/unit/test_migration_09_sql.py -q
```

Expected: FAIL with FileNotFoundError on the migration module path.

- [ ] **Step 3: Write the migration**

Create `alembic/versions/20260420_09_release_type_and_ai_flag.py`:

```python
"""add release_type and is_ai_suspected columns

Revision ID: 20260420_09
Revises: 20260419_08
Create Date: 2026-04-20 00:00:00
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260420_09"
down_revision = "20260419_08"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "clouder_tracks",
        sa.Column("release_type", sa.String(16), nullable=True),
    )
    op.add_column(
        "clouder_tracks",
        sa.Column(
            "is_ai_suspected",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("FALSE"),
        ),
    )
    op.add_column(
        "clouder_albums",
        sa.Column("release_type", sa.String(16), nullable=True),
    )
    op.add_column(
        "clouder_labels",
        sa.Column(
            "is_ai_suspected",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("FALSE"),
        ),
    )
    op.add_column(
        "clouder_artists",
        sa.Column(
            "is_ai_suspected",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("FALSE"),
        ),
    )


def downgrade() -> None:
    op.drop_column("clouder_artists", "is_ai_suspected")
    op.drop_column("clouder_labels", "is_ai_suspected")
    op.drop_column("clouder_albums", "release_type")
    op.drop_column("clouder_tracks", "is_ai_suspected")
    op.drop_column("clouder_tracks", "release_type")
```

- [ ] **Step 4: Run tests — confirm PASS**

```bash
pytest tests/unit/test_migration_09_sql.py -q
# Expected: 2 passed

# Local alembic smoke (if Postgres available):
export PYTHONPATH=src
export ALEMBIC_DATABASE_URL='postgresql+psycopg://postgres:postgres@localhost:5432/postgres'
alembic upgrade head && alembic downgrade -1 && alembic upgrade head
```

- [ ] **Step 5: Update `db_models.py`**

Add fields to the SQLAlchemy models:

```python
# ClouderTrack
release_type: Mapped[str | None] = mapped_column(String(16))
is_ai_suspected: Mapped[bool] = mapped_column(
    Boolean, nullable=False, server_default=text("FALSE")
)

# ClouderAlbum
release_type: Mapped[str | None] = mapped_column(String(16))

# ClouderLabel
is_ai_suspected: Mapped[bool] = mapped_column(
    Boolean, nullable=False, server_default=text("FALSE")
)

# ClouderArtist
is_ai_suspected: Mapped[bool] = mapped_column(
    Boolean, nullable=False, server_default=text("FALSE")
)
```

Add import at top: `from sqlalchemy import Boolean`.

Run `pytest -q` to ensure nothing breaks — existing test suite should still pass.

- [ ] **Step 6: Commit**

```bash
git add alembic/versions/20260420_09_release_type_and_ai_flag.py \
        tests/unit/test_migration_09_sql.py src/collector/db_models.py
git commit -m "<caveman-commit output>"
```

---

## Task 3: Add `release_type` to `NormalizedAlbum` / `NormalizedTrack`

**Files:**
- Modify: `src/collector/models.py`
- Test: `tests/unit/test_models.py` (extend)

- [ ] **Step 1: Write test**

Append to `tests/unit/test_models.py`:

```python
def test_normalized_album_release_type_default_none() -> None:
    from collector.models import NormalizedAlbum

    album = NormalizedAlbum(
        bp_release_id=1,
        title="X",
        normalized_title="x",
        release_date=None,
        bp_label_id=None,
        payload={},
    )
    assert album.release_type is None


def test_normalized_album_release_type_set() -> None:
    from collector.models import NormalizedAlbum

    album = NormalizedAlbum(
        bp_release_id=1,
        title="X",
        normalized_title="x",
        release_date=None,
        bp_label_id=None,
        payload={},
        release_type="single",
    )
    assert album.release_type == "single"
```

- [ ] **Step 2: Run — confirm FAIL**

```bash
pytest tests/unit/test_models.py -q
# Expected: unexpected keyword 'release_type'
```

- [ ] **Step 3: Add the field**

In `src/collector/models.py`, find `NormalizedAlbum` (frozen dataclass). Add:

```python
release_type: str | None = None
```

Similarly on `NormalizedTrack` if the current design puts release_type on tracks directly (decision: keep on album only; tracks inherit via album_id at canonicalize time). Leave `NormalizedTrack` alone.

- [ ] **Step 4: Run — confirm PASS**

```bash
pytest tests/unit/test_models.py -q
```

- [ ] **Step 5: Commit**

```bash
git add src/collector/models.py tests/unit/test_models.py
git commit -m "<caveman-commit output>"
```

---

## Task 4: Extract `release_type` from Beatport in `normalize.py`

**Exact Beatport field** — use findings from Task 1. Mapping rules codified as pure functions.

**Files:**
- Modify: `src/collector/normalize.py`
- Test: `tests/unit/test_release_type_mapping.py` (new)

- [ ] **Step 1: Write failing test**

Create `tests/unit/test_release_type_mapping.py`:

```python
from __future__ import annotations

import pytest

from collector.normalize import classify_release_type


def _release(**overrides):
    base = {"type": "Release", "tracks": [], "artists": []}
    base.update(overrides)
    return base


def test_single_track_release_is_single() -> None:
    r = _release(type="Release", tracks=[{"id": 1}])
    assert classify_release_type(r) == "single"


def test_small_album_is_ep() -> None:
    r = _release(type="Album", tracks=[{"id": i} for i in range(3)])
    assert classify_release_type(r) == "ep"


def test_big_album_is_album() -> None:
    r = _release(type="Album", tracks=[{"id": i} for i in range(8)])
    assert classify_release_type(r) == "album"


def test_explicit_compilation_flag() -> None:
    r = _release(type="Album", is_compilation=True)
    assert classify_release_type(r) == "compilation"


def test_va_heuristic_compilation() -> None:
    r = _release(
        type="Album",
        tracks=[{"id": i} for i in range(8)],
        artists=[{"id": i} for i in range(5)],
    )
    assert classify_release_type(r) == "compilation"


def test_unknown_type_returns_none() -> None:
    r = _release(type="Unknown")
    assert classify_release_type(r) is None
```

- [ ] **Step 2: Run — confirm FAIL**

- [ ] **Step 3: Implement `classify_release_type`**

In `src/collector/normalize.py`, add:

```python
def classify_release_type(release: Mapping[str, Any]) -> str | None:
    """Derive release_type label from a Beatport release payload.

    Rules (precedence top to bottom):
      1. Explicit compilation marker (`is_compilation=true`) → 'compilation'.
      2. VA heuristic: type=Album with >=COMPILATION_ARTIST_THRESHOLD distinct
         artists → 'compilation'.
      3. type=Release (single-track wrapper) → 'single'.
      4. type=Album with 1-3 tracks → 'ep'.
      5. type=Album with 4+ tracks → 'album'.
      6. Else → None (unknown).
    """
    from collector.settings import get_ingestion_settings

    settings = get_ingestion_settings()

    if release.get("is_compilation") is True:
        return "compilation"

    rel_type = str(release.get("type", "")).strip().lower()
    tracks = release.get("tracks") or []
    artists = release.get("artists") or []

    if rel_type == "album" and len(artists) >= settings.compilation_artist_threshold:
        return "compilation"

    if rel_type == "release":
        return "single"

    if rel_type == "album":
        if 1 <= len(tracks) <= 3:
            return "ep"
        if len(tracks) >= 4:
            return "album"

    return None
```

In `normalize_release_payload` (or equivalent), populate the album's `release_type`:

```python
# Where NormalizedAlbum is constructed:
NormalizedAlbum(
    bp_release_id=...,
    title=...,
    normalized_title=...,
    release_date=...,
    bp_label_id=...,
    payload=release,
    release_type=classify_release_type(release),
)
```

- [ ] **Step 4: Add `IngestionSettings` to `src/collector/settings.py`**

```python
class IngestionSettings(_SettingsBase):
    compilation_artist_threshold: int = Field(
        default=4, alias="COMPILATION_ARTIST_THRESHOLD"
    )
    ai_flag_confidence_threshold: float = Field(
        default=0.6, alias="AI_FLAG_CONFIDENCE_THRESHOLD"
    )


@functools.lru_cache
def get_ingestion_settings() -> IngestionSettings:
    return IngestionSettings()
```

And extend `reset_settings_cache`:
```python
get_ingestion_settings.cache_clear()
```

- [ ] **Step 5: Run — confirm PASS**

```bash
pytest tests/unit/test_release_type_mapping.py -q
pytest -q  # full suite
```

- [ ] **Step 6: Commit**

```bash
git add src/collector/normalize.py src/collector/settings.py \
        tests/unit/test_release_type_mapping.py
git commit -m "<caveman-commit output>"
```

---

## Task 5: Write `release_type` on canonical tracks + albums

**Files:**
- Modify: `src/collector/canonicalize.py`
- Modify: `src/collector/repositories.py` — extend `CreateAlbumCmd` / `ConservativeUpdateTrackCmd` etc. with `release_type`
- Test: `tests/unit/test_canonicalize.py` (extend)

- [ ] **Step 1: Write test**

Append to `tests/unit/test_canonicalize.py`:

```python
def test_canonicalize_writes_release_type_on_album(clouder_repo_fake) -> None:
    from collector.canonicalize import Canonicalizer
    from collector.models import NormalizedAlbum, NormalizedBundle

    album = NormalizedAlbum(
        bp_release_id=42,
        title="Sample Album",
        normalized_title="sample album",
        release_date=None,
        bp_label_id=None,
        payload={},
        release_type="ep",
    )
    bundle = NormalizedBundle(
        artists=(), labels=(), styles=(),
        albums=(album,), tracks=(), relations=(),
    )
    Canonicalizer(run_id="r1", repository=clouder_repo_fake).canonicalize(bundle)

    saved = clouder_repo_fake.albums_created[-1]
    assert saved.release_type == "ep"
```

Add `release_type` to the fake repo's captured commands too.

- [ ] **Step 2: Extend `CreateAlbumCmd` in `repositories.py`**

```python
@dataclass(frozen=True)
class CreateAlbumCmd:
    album_id: str
    title: str
    normalized_title: str
    release_date: date | None
    label_id: str | None
    release_type: str | None   # NEW
    at: datetime
```

Update the repository method that consumes this command to include `release_type` in the SQL INSERT. Similarly update `UpsertAlbumCmd` if it exists.

- [ ] **Step 3: In `canonicalize.py`, pass `release_type` from NormalizedAlbum into the command**

```python
cmd = CreateAlbumCmd(
    album_id=...,
    title=album.title,
    normalized_title=album.normalized_title,
    release_date=album.release_date,
    label_id=...,
    release_type=album.release_type,
    at=now,
)
```

Tracks inherit `release_type` from their album at canonicalize time. In `CreateTrackCmd`, add `release_type: str | None`. Pass it as `release_type=album.release_type` when creating tracks.

- [ ] **Step 4: Run full suite**

```bash
pytest -q
```

Expected: all pass including the new assertion.

- [ ] **Step 5: Commit**

```bash
git add src/collector/canonicalize.py src/collector/repositories.py \
        tests/unit/test_canonicalize.py
git commit -m "<caveman-commit output>"
```

---

## Task 6: Spotify enrich — extract `album.album_type`

**Files:**
- Modify: `src/collector/spotify_handler.py`
- Modify: `src/collector/repositories.py` — extend `UpdateSpotifyResultCmd` or add new method
- Test: `tests/unit/test_spotify_handler.py` (extend)

- [ ] **Step 1: Write test**

Append to `tests/unit/test_spotify_handler.py`:

```python
def test_spotify_handler_captures_album_type(monkeypatch) -> None:
    repo = _setup_spotify_worker(monkeypatch)  # existing helper
    # Mock Spotify API to return a track with album.album_type="compilation"
    fake_spotify_response = {
        "tracks": [
            {
                "id": "sp-id-1",
                "external_ids": {"isrc": "USRC17600001"},
                "album": {"album_type": "compilation", "id": "alb-sp-1"},
            }
        ]
    }
    monkeypatch.setattr(
        "collector.spotify_handler.spotify_search_batch",
        lambda *a, **kw: fake_spotify_response,
    )
    # ... invoke handler ...
    saved = repo.spotify_results[-1]
    assert saved.album_type == "compilation"
```

- [ ] **Step 2: Run — FAIL**

- [ ] **Step 3: Thread `album_type` through spotify_handler → repository**

In `spotify_handler.py`, after parsing each track, capture `album.album_type`. Extend the repository call to pass it.

In `repositories.py`:
```python
@dataclass(frozen=True)
class UpdateSpotifyResultCmd:
    track_id: str
    spotify_id: str | None
    spotify_album_type: str | None  # NEW
    searched_at: datetime
```

Update the SQL UPDATE in the implementation to set `spotify_album_type` → write to a new column? Or store on a generic path?

**Decision**: store on `clouder_tracks.spotify_album_type` is overkill; instead, `reconcile_release_type` (next task) reads directly from `source_entities` (where Spotify raw payload is stored) and updates `clouder_albums.release_type`. So no new column needed.

Simplify: do NOT add `spotify_album_type` column. Instead, ensure `source_entities` (source=spotify, entity_type=album) stores the `album.album_type` in its payload JSON — which it already does if we save the raw Spotify album. If not, update `spotify_handler.py` to also upsert a `source_entities` row for Spotify albums.

- [ ] **Step 4: Run tests — adjust**

Rewrite the test to verify `source_entities` contains the album_type in payload.

- [ ] **Step 5: Commit**

```bash
git add src/collector/spotify_handler.py src/collector/repositories.py \
        tests/unit/test_spotify_handler.py
git commit -m "<caveman-commit output>"
```

---

## Task 7: `reconcile_release_type` phase

**Files:**
- Modify: `src/collector/canonicalize.py` — new phase
- Test: `tests/unit/test_reconcile_release_type.py` (new)

- [ ] **Step 1: Write tests**

Create `tests/unit/test_reconcile_release_type.py`:

```python
from __future__ import annotations

import pytest

from collector.canonicalize import reconcile_release_type


@pytest.mark.parametrize(
    "beatport,spotify,expected",
    [
        ("album", "compilation", "compilation"),  # Spotify wins for compilation
        ("album", "album", "album"),
        ("ep", "album", "ep"),                    # Beatport wins otherwise
        ("single", "single", "single"),
        ("album", None, "album"),                 # Spotify missing → keep Beatport
        (None, "compilation", "compilation"),     # Beatport missing → take Spotify
        (None, None, None),
    ],
)
def test_reconcile_release_type(beatport, spotify, expected):
    assert reconcile_release_type(beatport, spotify) == expected
```

- [ ] **Step 2: Run — FAIL**

- [ ] **Step 3: Implement in `canonicalize.py`**

```python
def reconcile_release_type(
    beatport_type: str | None,
    spotify_album_type: str | None,
) -> str | None:
    """Resolve canonical release_type from Beatport + Spotify signals.

    Rules:
      - If Spotify says 'compilation', trust Spotify (more reliable signal).
      - Otherwise, prefer Beatport.
      - If Beatport missing, fall back to Spotify.
    """
    if spotify_album_type == "compilation":
        return "compilation"
    return beatport_type or spotify_album_type
```

Wire this into the canonicalize flow: after Spotify enrichment phase writes to `source_entities`, iterate over albums that have a matching Spotify source_entity, compute reconciled `release_type`, and update `clouder_albums.release_type` + inherited `clouder_tracks.release_type`. This runs as a separate phase `RECONCILE_RELEASE_TYPE` after Spotify enrichment.

Add new repository method:
```python
def update_album_release_type(self, album_id: str, release_type: str | None, tx_id: str | None = None) -> None:
    ...  # SQL UPDATE clouder_albums SET release_type=... WHERE id=...
    # + matching UPDATE clouder_tracks SET release_type=... WHERE album_id=...
```

- [ ] **Step 4: Run — PASS**

- [ ] **Step 5: Commit**

```bash
git add src/collector/canonicalize.py src/collector/repositories.py \
        tests/unit/test_reconcile_release_type.py
git commit -m "<caveman-commit output>"
```

---

## Task 8: `is_ai_suspected` propagation

**Files:**
- Modify: `src/collector/search_handler.py` — after `save_search_result`, call propagation
- Modify: `src/collector/repositories.py` — new method `update_entity_is_ai_suspected`
- Test: `tests/unit/test_ai_flag_propagation.py` (new)

- [ ] **Step 1: Write tests**

Create `tests/unit/test_ai_flag_propagation.py`:

```python
from __future__ import annotations

from collector.search_handler import propagate_ai_flag
from collector.search.schemas import LabelSearchResult


def _result(ai_content: str, confidence: float) -> LabelSearchResult:
    return LabelSearchResult(
        label_name="X", style="Y",
        size="small", size_details="", age="new", age_details="",
        ai_content=ai_content, ai_content_details="",
        summary="", confidence=confidence,
    )


class FakeRepo:
    def __init__(self):
        self.updates: list[tuple] = []

    def update_entity_is_ai_suspected(self, entity_type, entity_id, value, tx_id=None):
        self.updates.append((entity_type, entity_id, value))


def test_confirmed_above_threshold_sets_flag() -> None:
    repo = FakeRepo()
    propagate_ai_flag(
        repo, entity_type="label", entity_id="L1",
        result=_result("confirmed", 0.8), threshold=0.6,
    )
    assert repo.updates == [("label", "L1", True)]


def test_none_detected_clears_flag() -> None:
    repo = FakeRepo()
    propagate_ai_flag(
        repo, entity_type="label", entity_id="L1",
        result=_result("none_detected", 0.9), threshold=0.6,
    )
    assert repo.updates == [("label", "L1", False)]


def test_low_confidence_no_update() -> None:
    repo = FakeRepo()
    propagate_ai_flag(
        repo, entity_type="label", entity_id="L1",
        result=_result("confirmed", 0.4), threshold=0.6,
    )
    assert repo.updates == []


def test_unknown_status_no_update() -> None:
    repo = FakeRepo()
    propagate_ai_flag(
        repo, entity_type="label", entity_id="L1",
        result=_result("unknown", 0.9), threshold=0.6,
    )
    assert repo.updates == []
```

- [ ] **Step 2: Run — FAIL**

- [ ] **Step 3: Implement**

In `src/collector/search_handler.py`, add:

```python
def propagate_ai_flag(
    repository: Any,
    *,
    entity_type: str,
    entity_id: str,
    result: Any,  # LabelSearchResult
    threshold: float,
) -> None:
    """Set/clear is_ai_suspected on the canonical row based on AI result."""
    status = str(getattr(result, "ai_content", "unknown")).lower()
    confidence = float(getattr(result, "confidence", 0.0))

    if confidence < threshold:
        return

    if status in ("suspected", "confirmed"):
        repository.update_entity_is_ai_suspected(entity_type, entity_id, True)
    elif status == "none_detected":
        repository.update_entity_is_ai_suspected(entity_type, entity_id, False)
    # unknown → no update
```

In `_run_label_search` (after `repository.save_search_result(...)`), add:

```python
propagate_ai_flag(
    repository,
    entity_type="label",
    entity_id=message.entity_id,
    result=result,
    threshold=get_ingestion_settings().ai_flag_confidence_threshold,
)
```

In `repositories.py`, add:

```python
def update_entity_is_ai_suspected(
    self, entity_type: str, entity_id: str, value: bool, tx_id: str | None = None
) -> None:
    table = {
        "label": "clouder_labels",
        "artist": "clouder_artists",
        "track": "clouder_tracks",
    }.get(entity_type)
    if table is None:
        raise ValueError(f"unsupported entity_type: {entity_type}")
    self._execute(
        f"UPDATE {table} SET is_ai_suspected = :v WHERE id = :id",
        [{"name": "v", "value": {"booleanValue": value}},
         {"name": "id", "value": {"stringValue": entity_id}}],
        tx_id=tx_id,
    )
```

(Adjust to match existing `_execute`/Data API patterns in the codebase.)

- [ ] **Step 4: Run — PASS**

```bash
pytest tests/unit/test_ai_flag_propagation.py tests/unit/test_search_handler.py -q
pytest -q
```

- [ ] **Step 5: Commit**

```bash
git add src/collector/search_handler.py src/collector/repositories.py \
        tests/unit/test_ai_flag_propagation.py
git commit -m "<caveman-commit output>"
```

---

## Task 9: Update CLAUDE.md + data-model docs

**Files:**
- Modify: `docs/data-model.md` — add new columns to relevant tables.
- Modify: `CLAUDE.md` — add a one-liner to "Env Vars (runtime)" and "Gotchas" about the new settings.

- [ ] **Step 1: Update docs**

In `docs/data-model.md`, add `release_type` rows to `clouder_tracks` and `clouder_albums` tables, and `is_ai_suspected` to `clouder_tracks`, `clouder_labels`, `clouder_artists`.

In `CLAUDE.md`:
- Add to Env Vars section: `COMPILATION_ARTIST_THRESHOLD` (default 4), `AI_FLAG_CONFIDENCE_THRESHOLD` (default 0.6).
- Add to Gotchas: "Release type comes from Beatport `type`/`is_compilation`, reconciled against Spotify `album.album_type` for compilation override."

- [ ] **Step 2: Commit**

```bash
git add docs/data-model.md CLAUDE.md
git commit -m "<caveman-commit output>"
```

---

## Execution Order Summary

1. Task 1 — Inspect raw sample (one-shot, may update Task 4 mapping)
2. Task 2 — Alembic migration + db_models
3. Task 3 — NormalizedAlbum.release_type
4. Task 4 — classify_release_type + settings
5. Task 5 — canonicalize writes release_type
6. Task 6 — Spotify enrich captures album_type in source_entities
7. Task 7 — reconcile_release_type phase
8. Task 8 — is_ai_suspected propagation
9. Task 9 — Docs

Each task is an independent PR-able unit. CI (`pytest -q`, `alembic-check`, `terraform validate`) must remain green after every commit.

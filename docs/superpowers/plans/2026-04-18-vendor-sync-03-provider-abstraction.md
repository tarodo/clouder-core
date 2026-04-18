# Vendor-Sync Plan 3 — Provider Abstraction Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Introduce a provider registry with four role Protocols (`IngestProvider`, `LookupProvider`, `EnrichProvider`, `ExportProvider`). Move existing Beatport / Spotify / Perplexity clients into `src/collector/providers/`. Stub YT Music / Deezer / Apple / Tidal providers that raise `VendorDisabledError`.

**Architecture:** One public surface (`src/collector/providers/registry.py`) returns role-typed providers keyed by vendor name. Handlers stop importing vendor-specific modules and instead call `registry.get_lookup("spotify")` etc. Adding a vendor = new file + registry entry + flag flip.

**Tech Stack:** Python 3.12 `typing.Protocol`, existing httpx / boto3 clients.

**Spec:** [docs/superpowers/specs/2026-04-18-vendor-sync-readiness-design.md](../specs/2026-04-18-vendor-sync-readiness-design.md) §4, §7.4 partial (ExportProvider signature only).

**Prereqs:** Plans 1 and 2 merged. No alembic migration needed.

**Scope note:** This is a **refactor** — existing behaviour must be preserved exactly. Every rewired handler must have an integration test proving the end-to-end flow still works.

---

## File Structure

New files:
```
src/collector/providers/
  __init__.py
  base.py                # Protocols + VendorTrackRef + dataclasses + errors
  registry.py            # PROVIDERS dict, accessors
  beatport.py            # moved from src/collector/beatport_client.py
  spotify/
    __init__.py
    lookup.py            # moved from src/collector/spotify_client.py
    enrich.py            # extracted from spotify_handler
    export.py            # scaffold raising VendorDisabledError
  perplexity/
    __init__.py
    label.py             # moved from src/collector/search/perplexity_client.py
    artist.py            # stub — NotImplementedError inside enrich()
  ytmusic/
    __init__.py
    lookup.py            # stub
    export.py            # stub
  deezer/
    __init__.py
    lookup.py            # stub
    export.py            # stub
  apple/
    __init__.py
    lookup.py            # stub
    export.py            # stub
  tidal/
    __init__.py
    lookup.py            # stub
    export.py            # stub
```

Modified files:
- `src/collector/handler.py` — `from .providers.beatport import BeatportProvider` (or via registry).
- `src/collector/spotify_handler.py` — use `registry.get_lookup("spotify")`.
- `src/collector/search_handler.py` — `_dispatch_entity_search` uses `registry.get_enricher(prompt_slug)`.
- `src/collector/settings.py` — add `VENDORS_ENABLED` env var.
- `src/collector/errors.py` — add `VendorDisabledError`.

Removed files (after rewire proven):
- `src/collector/beatport_client.py`
- `src/collector/spotify_client.py`
- `src/collector/search/perplexity_client.py`
- `src/collector/search/prompts.py` → moved to `providers/perplexity/prompts.py`

---

## Task 1: Protocols + `VendorTrackRef` + `ProviderBundle` + error class

**Files:**
- Create: `src/collector/providers/__init__.py` (empty)
- Create: `src/collector/providers/base.py`
- Modify: `src/collector/errors.py` — add `VendorDisabledError`
- Test: `tests/unit/test_providers_base.py`

- [ ] **Step 1: Write failing test**

```python
# tests/unit/test_providers_base.py
from __future__ import annotations

import pytest

from collector.providers.base import (
    VendorTrackRef, ProviderBundle, IngestProvider, LookupProvider,
    EnrichProvider, ExportProvider,
)
from collector.errors import VendorDisabledError


def test_vendor_track_ref_basic() -> None:
    ref = VendorTrackRef(
        vendor="spotify", vendor_track_id="abc",
        isrc="USRC00000001", artist_names=("Foo",),
        title="Bar", duration_ms=200_000,
        album_name="Baz", raw_payload={"id": "abc"},
    )
    assert ref.vendor == "spotify"
    assert ref.artist_names == ("Foo",)
    with pytest.raises(Exception):
        ref.vendor = "other"  # frozen


def test_provider_bundle_defaults_none() -> None:
    b = ProviderBundle()
    assert b.ingest is None
    assert b.lookup is None
    assert b.enrich is None
    assert b.export is None


def test_vendor_disabled_error_has_code() -> None:
    err = VendorDisabledError("ytmusic")
    assert err.error_code == "vendor_disabled"
    assert "ytmusic" in str(err)
```

- [ ] **Step 2: Run — FAIL (ImportError)**

- [ ] **Step 3: Implement**

`src/collector/providers/base.py`:

```python
"""Provider protocols and shared types for vendor integrations."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


@dataclass(frozen=True)
class VendorTrackRef:
    vendor: str
    vendor_track_id: str
    isrc: str | None
    artist_names: tuple[str, ...]
    title: str
    duration_ms: int | None
    album_name: str | None
    raw_payload: dict[str, Any]


@dataclass(frozen=True)
class VendorPlaylistRef:
    vendor: str
    vendor_playlist_id: str
    url: str | None


@dataclass(frozen=True)
class EnrichResult:
    entity_type: str
    entity_id: str
    prompt_slug: str
    prompt_version: str
    payload: dict[str, Any]


@dataclass(frozen=True)
class RawIngestPayload:
    source: str
    data: dict[str, Any]
    meta: dict[str, Any]


@runtime_checkable
class IngestProvider(Protocol):
    source_name: str

    def fetch_releases(
        self, style_id: int, iso_year: int, iso_week: int, token: str
    ) -> RawIngestPayload: ...


@runtime_checkable
class LookupProvider(Protocol):
    vendor_name: str

    def lookup_by_isrc(self, isrc: str) -> VendorTrackRef | None: ...

    def lookup_by_metadata(
        self, artist: str, title: str, duration_ms: int | None,
        album: str | None,
    ) -> list[VendorTrackRef]: ...


@runtime_checkable
class EnrichProvider(Protocol):
    vendor_name: str
    entity_types: tuple[str, ...]
    prompt_slug: str
    prompt_version: str

    def enrich(
        self, entity_type: str, entity_id: str, payload: dict[str, Any],
    ) -> EnrichResult: ...


@runtime_checkable
class ExportProvider(Protocol):
    vendor_name: str

    def create_playlist(
        self, user_token: str, name: str,
        track_refs: list[VendorTrackRef],
    ) -> VendorPlaylistRef: ...


@dataclass(frozen=True)
class ProviderBundle:
    ingest: IngestProvider | None = None
    lookup: LookupProvider | None = None
    enrich: EnrichProvider | None = None
    export: ExportProvider | None = None
```

Also add to `src/collector/errors.py`:

```python
class VendorDisabledError(AppError):
    status_code = 400
    error_code = "vendor_disabled"

    def __init__(self, vendor: str):
        super().__init__(f"vendor is disabled or not implemented: {vendor}")
        self.vendor = vendor
```

And `src/collector/providers/__init__.py`:
```python
"""Provider registry and vendor implementations."""
```

- [ ] **Step 4: Run — PASS**

- [ ] **Step 5: Commit**

```bash
git add src/collector/providers/__init__.py src/collector/providers/base.py \
        src/collector/errors.py tests/unit/test_providers_base.py
git commit -m "<caveman-commit output>"
```

---

## Task 2: Registry with accessors + `VENDORS_ENABLED` filter

**Files:**
- Create: `src/collector/providers/registry.py`
- Modify: `src/collector/settings.py` — add `VENDORS_ENABLED`
- Test: `tests/unit/test_providers_registry.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/unit/test_providers_registry.py
from __future__ import annotations

import pytest

from collector.providers import registry
from collector.errors import VendorDisabledError


def test_get_lookup_known_vendor(monkeypatch) -> None:
    monkeypatch.setenv("VENDORS_ENABLED", "spotify")
    registry.reset_cache()
    provider = registry.get_lookup("spotify")
    assert provider.vendor_name == "spotify"


def test_get_lookup_disabled_vendor_raises(monkeypatch) -> None:
    monkeypatch.setenv("VENDORS_ENABLED", "")  # all disabled
    registry.reset_cache()
    with pytest.raises(VendorDisabledError):
        registry.get_lookup("spotify")


def test_get_lookup_unknown_vendor_raises(monkeypatch) -> None:
    monkeypatch.setenv("VENDORS_ENABLED", "spotify")
    registry.reset_cache()
    with pytest.raises(VendorDisabledError):
        registry.get_lookup("nonexistent")


def test_list_enabled_exporters(monkeypatch) -> None:
    monkeypatch.setenv("VENDORS_ENABLED", "spotify,ytmusic,deezer")
    registry.reset_cache()
    names = [p.vendor_name for p in registry.list_enabled_exporters()]
    assert set(names) == {"spotify", "ytmusic", "deezer"}
```

- [ ] **Step 2: Run — FAIL**

- [ ] **Step 3: Implement registry**

```python
# src/collector/providers/registry.py
from __future__ import annotations

import functools
import os
from typing import Iterable

from .base import (
    ProviderBundle, IngestProvider, LookupProvider,
    EnrichProvider, ExportProvider,
)
from ..errors import VendorDisabledError


# Stub implementations for disabled vendors — imports inlined to avoid circulars.
def _build_registry() -> dict[str, ProviderBundle]:
    from .beatport import BeatportProvider
    from .spotify.lookup import SpotifyLookup
    from .spotify.enrich import SpotifyEnricher
    from .spotify.export import SpotifyExporter
    from .perplexity.label import PerplexityLabelEnricher
    from .ytmusic.lookup import YTMusicLookup
    from .ytmusic.export import YTMusicExporter
    from .deezer.lookup import DeezerLookup
    from .deezer.export import DeezerExporter
    from .apple.lookup import AppleLookup
    from .apple.export import AppleExporter
    from .tidal.lookup import TidalLookup
    from .tidal.export import TidalExporter

    return {
        "beatport":         ProviderBundle(ingest=BeatportProvider()),
        "spotify":          ProviderBundle(
            lookup=SpotifyLookup(),
            enrich=SpotifyEnricher(),
            export=SpotifyExporter(),
        ),
        "perplexity_label": ProviderBundle(enrich=PerplexityLabelEnricher()),
        "ytmusic":          ProviderBundle(
            lookup=YTMusicLookup(), export=YTMusicExporter(),
        ),
        "deezer":           ProviderBundle(
            lookup=DeezerLookup(), export=DeezerExporter(),
        ),
        "apple":            ProviderBundle(
            lookup=AppleLookup(), export=AppleExporter(),
        ),
        "tidal":            ProviderBundle(
            lookup=TidalLookup(), export=TidalExporter(),
        ),
    }


@functools.lru_cache(maxsize=1)
def _registry() -> dict[str, ProviderBundle]:
    return _build_registry()


def _enabled_vendors() -> set[str]:
    raw = os.environ.get("VENDORS_ENABLED", "").strip()
    if not raw:
        return set()
    return {v.strip() for v in raw.split(",") if v.strip()}


def reset_cache() -> None:
    _registry.cache_clear()


def _require_enabled(name: str) -> ProviderBundle:
    if name not in _enabled_vendors():
        raise VendorDisabledError(name)
    bundle = _registry().get(name)
    if bundle is None:
        raise VendorDisabledError(name)
    return bundle


def get_ingest(name: str) -> IngestProvider:
    bundle = _require_enabled(name)
    if bundle.ingest is None:
        raise VendorDisabledError(name)
    return bundle.ingest


def get_lookup(name: str) -> LookupProvider:
    bundle = _require_enabled(name)
    if bundle.lookup is None:
        raise VendorDisabledError(name)
    return bundle.lookup


def get_enricher(prompt_slug: str) -> EnrichProvider:
    """Find an enricher that handles the given prompt_slug."""
    for name, bundle in _registry().items():
        if bundle.enrich is None:
            continue
        if bundle.enrich.prompt_slug == prompt_slug:
            if name not in _enabled_vendors() and name != "perplexity_label":
                # perplexity_label is always enabled if PERPLEXITY_API_KEY is configured
                raise VendorDisabledError(name)
            return bundle.enrich
    raise VendorDisabledError(prompt_slug)


def get_exporter(name: str) -> ExportProvider:
    bundle = _require_enabled(name)
    if bundle.export is None:
        raise VendorDisabledError(name)
    return bundle.export


def list_enabled_exporters() -> Iterable[ExportProvider]:
    enabled = _enabled_vendors()
    for name, bundle in _registry().items():
        if name in enabled and bundle.export is not None:
            yield bundle.export
```

- [ ] **Step 4: Add `VENDORS_ENABLED` to settings (informational — already read via os.environ in registry)**

In `CLAUDE.md` Env Vars section, add: `VENDORS_ENABLED` (comma-separated list; vendors not listed raise `VendorDisabledError`). Also in README.

- [ ] **Step 5: Run — PASS**

At this point Task 3+ will provide the actual provider classes. Registry tests will fail until they exist. **Skip test execution here**; the imports at top of `_build_registry` don't resolve yet. Move to Task 3 and continue TDD in dependency order.

- [ ] **Step 6: Commit registry + tests (expect test failure until stubs exist)**

Commit with `[WIP]` marker in branch, to be resolved when stubs land:

```bash
git add src/collector/providers/registry.py tests/unit/test_providers_registry.py
git commit -m "<caveman-commit output>"
```

---

## Task 3: Move `BeatportClient` → `providers/beatport.py`

**Files:**
- Create: `src/collector/providers/beatport.py`
- Delete: `src/collector/beatport_client.py` (after rewire)
- Modify: `src/collector/handler.py` — `from .providers.beatport import BeatportProvider`
- Modify: existing tests that import `beatport_client` → update import paths

- [ ] **Step 1: Copy existing `beatport_client.py` content into `providers/beatport.py`**

```python
# src/collector/providers/beatport.py
"""Beatport API client — conforms to IngestProvider Protocol."""
from __future__ import annotations

# (copy existing BeatportClient code here, rename class to BeatportProvider)
# Set `source_name = "beatport"` as class attribute.
# Signature of fetch_releases must match IngestProvider Protocol.

class BeatportProvider:
    source_name = "beatport"

    def fetch_releases(self, style_id, iso_year, iso_week, token) -> RawIngestPayload:
        # existing fetch logic
        ...
```

Return type should wrap raw response into `RawIngestPayload(source="beatport", data=..., meta=...)`.

- [ ] **Step 2: Update `handler.py` import**

```python
# Before:
from .beatport_client import BeatportClient

# After:
from .providers.beatport import BeatportProvider
```

Replace all `BeatportClient` references with `BeatportProvider`. Call signature stays the same.

- [ ] **Step 3: Update tests**

```bash
grep -rn "beatport_client\|BeatportClient" tests/ src/
```

Update each import. Existing test `tests/unit/test_beatport_client.py` → rename to `tests/unit/test_providers_beatport.py` and fix imports.

- [ ] **Step 4: Run full suite**

```bash
pytest -q
```

Expected: all pass (baseline + the two registry tests that still need stubs to exist — they'll fail; that's OK for this commit, will pass after Task 5+).

- [ ] **Step 5: Delete old file**

```bash
git rm src/collector/beatport_client.py
```

- [ ] **Step 6: Commit**

```bash
git add src/collector/providers/beatport.py src/collector/handler.py \
        tests/unit/test_providers_beatport.py
git commit -m "<caveman-commit output>"
```

---

## Task 4: Move Spotify lookup → `providers/spotify/lookup.py`

**Files:**
- Create: `src/collector/providers/spotify/__init__.py` (empty)
- Create: `src/collector/providers/spotify/lookup.py` — `class SpotifyLookup`
- Modify: `src/collector/spotify_handler.py` — use `registry.get_lookup("spotify")` OR direct import
- Delete (later): `src/collector/spotify_client.py`

- [ ] **Step 1: Write the provider class**

```python
# src/collector/providers/spotify/lookup.py
"""Spotify Web API lookup by ISRC / metadata."""
from __future__ import annotations

# Move existing client logic here. Expose:
class SpotifyLookup:
    vendor_name = "spotify"

    def lookup_by_isrc(self, isrc: str) -> VendorTrackRef | None:
        # existing ISRC search, map result → VendorTrackRef
        ...

    def lookup_by_metadata(self, artist, title, duration_ms, album) -> list[VendorTrackRef]:
        # Spotify search with q= parameter
        ...
```

Both methods return typed `VendorTrackRef` objects constructed from Spotify track JSON.

- [ ] **Step 2: Rewire `spotify_handler.py`**

```python
# Before:
from .spotify_client import spotify_search_batch, ...

# After:
from .providers.spotify.lookup import SpotifyLookup
_lookup = SpotifyLookup()

# Use _lookup.lookup_by_isrc(isrc) inside the loop.
```

- [ ] **Step 3: Update tests**

`tests/unit/test_spotify_client.py` → `tests/unit/test_providers_spotify_lookup.py`. Same tests, new import.
`tests/unit/test_spotify_handler.py` — update monkeypatch targets to `collector.providers.spotify.lookup.SpotifyLookup.*`.

- [ ] **Step 4: Run — PASS**

- [ ] **Step 5: Delete old file**

```bash
git rm src/collector/spotify_client.py
```

- [ ] **Step 6: Commit**

```bash
git add ... && git commit -m "<caveman-commit output>"
```

---

## Task 5: `providers/spotify/enrich.py` + `providers/spotify/export.py` scaffolds

**Files:**
- Create: `src/collector/providers/spotify/enrich.py`
- Create: `src/collector/providers/spotify/export.py`

- [ ] **Step 1: Enrich**

```python
# src/collector/providers/spotify/enrich.py
"""Spotify enrich — pulls album.album_type from lookup results."""
from __future__ import annotations

from ..base import EnrichProvider, EnrichResult
from .lookup import SpotifyLookup


class SpotifyEnricher:
    vendor_name = "spotify"
    entity_types = ("track",)
    prompt_slug = "spotify_release_type"
    prompt_version = "v1"

    def __init__(self, lookup: SpotifyLookup | None = None):
        self._lookup = lookup or SpotifyLookup()

    def enrich(self, entity_type: str, entity_id: str, payload: dict) -> EnrichResult:
        if entity_type != "track":
            raise ValueError(f"SpotifyEnricher supports entity_type=track, got {entity_type}")
        isrc = payload.get("isrc")
        if not isrc:
            return EnrichResult(
                entity_type=entity_type, entity_id=entity_id,
                prompt_slug=self.prompt_slug, prompt_version=self.prompt_version,
                payload={"status": "no_isrc"},
            )
        ref = self._lookup.lookup_by_isrc(isrc)
        if ref is None:
            return EnrichResult(
                entity_type=entity_type, entity_id=entity_id,
                prompt_slug=self.prompt_slug, prompt_version=self.prompt_version,
                payload={"status": "not_found"},
            )
        album_type = (ref.raw_payload or {}).get("album", {}).get("album_type")
        return EnrichResult(
            entity_type=entity_type, entity_id=entity_id,
            prompt_slug=self.prompt_slug, prompt_version=self.prompt_version,
            payload={
                "spotify_id": ref.vendor_track_id,
                "album_type": album_type,
            },
        )
```

- [ ] **Step 2: Export scaffold**

```python
# src/collector/providers/spotify/export.py
"""Spotify playlist export — user OAuth required. Not implemented until user-layer."""
from __future__ import annotations

from ..base import ExportProvider, VendorPlaylistRef, VendorTrackRef
from ...errors import VendorDisabledError


class SpotifyExporter:
    vendor_name = "spotify"

    def create_playlist(
        self, user_token: str, name: str, track_refs: list[VendorTrackRef],
    ) -> VendorPlaylistRef:
        raise VendorDisabledError("spotify-export-not-implemented")
```

- [ ] **Step 3: Tests**

Write minimal tests asserting `SpotifyEnricher.enrich` routes correctly, and `SpotifyExporter.create_playlist` raises `VendorDisabledError`.

- [ ] **Step 4: Run — PASS**

- [ ] **Step 5: Commit**

---

## Task 6: Move Perplexity label enricher + add artist stub

**Files:**
- Create: `src/collector/providers/perplexity/__init__.py`
- Create: `src/collector/providers/perplexity/label.py`
- Create: `src/collector/providers/perplexity/artist.py`
- Create: `src/collector/providers/perplexity/prompts.py` (moved from `search/prompts.py`)
- Delete: `src/collector/search/perplexity_client.py` (after rewire)

- [ ] **Step 1: Label enricher**

```python
# src/collector/providers/perplexity/label.py
"""Perplexity-backed label enricher."""
from __future__ import annotations

from ..base import EnrichProvider, EnrichResult
# existing imports (openai/httpx client, LabelSearchResult schema)


class PerplexityLabelEnricher:
    vendor_name = "perplexity_label"
    entity_types = ("label",)
    prompt_slug = "label_info"
    prompt_version = "v1"

    def enrich(self, entity_type: str, entity_id: str, payload: dict) -> EnrichResult:
        if entity_type != "label":
            raise ValueError(f"supports label, got {entity_type}")
        label_name = str(payload.get("label_name", ""))
        styles = str(payload.get("styles", ""))
        # existing search_label logic, reading config via get_prompt
        result = _search_label(label_name=label_name, style=styles, ...)
        return EnrichResult(
            entity_type=entity_type, entity_id=entity_id,
            prompt_slug=self.prompt_slug, prompt_version=self.prompt_version,
            payload=result.model_dump(),
        )
```

- [ ] **Step 2: Artist stub**

```python
# src/collector/providers/perplexity/artist.py
"""Perplexity artist enricher — architecture ready, not activated."""
from __future__ import annotations

from ..base import EnrichProvider, EnrichResult


class PerplexityArtistEnricher:
    vendor_name = "perplexity_artist"
    entity_types = ("artist",)
    prompt_slug = "artist_info"
    prompt_version = "v1"

    def enrich(self, entity_type: str, entity_id: str, payload: dict) -> EnrichResult:
        raise NotImplementedError("artist enrichment not yet wired to a prompt")
```

- [ ] **Step 3: Rewire `search_handler.py`**

Replace the current inline dispatch `if entity_type == "label": _run_label_search(...)` with registry lookup:

```python
from .providers import registry

def _dispatch_entity_search(message, settings, repository, correlation_id):
    try:
        enricher = registry.get_enricher(message.prompt_slug)
    except VendorDisabledError:
        log_event("WARNING", "search_entity_type_unsupported", ...)
        return False
    result = enricher.enrich(message.entity_type, message.entity_id, message.context)
    repository.save_search_result(..., result=result.payload, ...)
    propagate_ai_flag(repository, ...)  # from Plan 2
    return True
```

- [ ] **Step 4: Update `tests/unit/test_search_handler.py`**

Monkeypatch targets change: instead of `collector.search_handler.search_label`, patch `collector.providers.perplexity.label.PerplexityLabelEnricher.enrich`.

- [ ] **Step 5: Delete old file**

```bash
git rm src/collector/search/perplexity_client.py
# Keep src/collector/search/prompts.py if still imported, or move to providers/perplexity/prompts.py
```

- [ ] **Step 6: Run — PASS**

- [ ] **Step 7: Commit**

---

## Task 7: Stub vendors (YT Music / Deezer / Apple / Tidal)

Each vendor follows the same pattern. Show one; repeat structure for others.

**Files:**
- Create per vendor: `src/collector/providers/<vendor>/__init__.py`, `lookup.py`, `export.py`
- Test: `tests/contract/test_vendor_stubs.py`

- [ ] **Step 1: YT Music stub**

```python
# src/collector/providers/ytmusic/__init__.py
# empty

# src/collector/providers/ytmusic/lookup.py
from ..base import LookupProvider, VendorTrackRef
from ...errors import VendorDisabledError


class YTMusicLookup:
    vendor_name = "ytmusic"

    def lookup_by_isrc(self, isrc: str) -> VendorTrackRef | None:
        raise VendorDisabledError(self.vendor_name)

    def lookup_by_metadata(self, artist, title, duration_ms, album) -> list[VendorTrackRef]:
        raise VendorDisabledError(self.vendor_name)

# src/collector/providers/ytmusic/export.py
from ..base import ExportProvider, VendorPlaylistRef, VendorTrackRef
from ...errors import VendorDisabledError


class YTMusicExporter:
    vendor_name = "ytmusic"

    def create_playlist(self, user_token, name, track_refs) -> VendorPlaylistRef:
        raise VendorDisabledError(self.vendor_name)
```

- [ ] **Step 2: Repeat for deezer, apple, tidal**

Same shape. Class names: `DeezerLookup`, `DeezerExporter`, `AppleLookup`, `AppleExporter`, `TidalLookup`, `TidalExporter`. Vendor names: `"deezer"`, `"apple"`, `"tidal"`.

- [ ] **Step 3: Contract tests**

```python
# tests/contract/test_vendor_stubs.py
from __future__ import annotations

import pytest

from collector.providers.base import LookupProvider, ExportProvider
from collector.errors import VendorDisabledError


@pytest.mark.parametrize("name", ["ytmusic", "deezer", "apple", "tidal"])
def test_stub_lookup_protocol_and_raises(name) -> None:
    from collector.providers import registry
    registry.reset_cache()
    bundle = registry._registry()[name]
    assert bundle.lookup is not None
    assert isinstance(bundle.lookup, LookupProvider)

    with pytest.raises(VendorDisabledError):
        bundle.lookup.lookup_by_isrc("USRC17600001")


@pytest.mark.parametrize("name", ["ytmusic", "deezer", "apple", "tidal"])
def test_stub_export_protocol_and_raises(name) -> None:
    from collector.providers import registry
    registry.reset_cache()
    bundle = registry._registry()[name]
    assert bundle.export is not None
    assert isinstance(bundle.export, ExportProvider)

    with pytest.raises(VendorDisabledError):
        bundle.export.create_playlist("t", "n", [])
```

- [ ] **Step 4: Run**

```bash
pytest tests/contract/ -q
pytest -q
```

All pass.

- [ ] **Step 5: Commit**

---

## Task 8: Update docs + CLAUDE.md

- [ ] Add to `CLAUDE.md` Layout section: `src/collector/providers/` — vendor protocols, registry, implementations.
- [ ] Add to Env Vars: `VENDORS_ENABLED` — comma-separated; defaults to empty (only non-vendor providers like `perplexity_label` available).
- [ ] Note in Gotchas: "New vendors need entry in `providers/registry.py` + `VENDORS_ENABLED` toggle."
- [ ] Commit.

---

## Execution Order Summary

1. Task 1 — Protocols + VendorTrackRef + VendorDisabledError
2. Task 2 — Registry (broken until Task 3+)
3. Task 3 — Beatport move + rewire handler
4. Task 4 — Spotify lookup move + rewire spotify_handler
5. Task 5 — Spotify enrich + export scaffold
6. Task 6 — Perplexity move + rewire search_handler to use registry
7. Task 7 — Stub vendors + contract tests
8. Task 8 — Docs

After this plan lands:
- Plans 4 and 5 can reference `VendorTrackRef`, `registry.get_lookup/get_exporter`, `VendorDisabledError`.
- No runtime behaviour change from users' perspective.

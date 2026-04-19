# Vendor-Sync Plan 3 (Variant A — Adapter) — Provider Abstraction Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ввести единый реестр провайдеров и роли (`IngestProvider`, `LookupProvider`, `EnrichProvider`, `ExportProvider`). Существующие клиенты (`BeatportClient`, `SpotifyClient`, `search_label`) **обернуть** тонкими адаптерами под Protocol; внутреннее поведение хендлеров не меняется. Добавить stub-вендоры YT Music / Deezer / Apple / Tidal, отдающие `VendorDisabledError`. Управление включением — env-флаг `VENDORS_ENABLED`.

**Architecture:** Один публичный фасад `src/collector/providers/registry.py` возвращает провайдеры по имени вендора. Адаптеры (`providers/<vendor>/...`) держат внутри существующий клиент и выставляют наружу методы, **точно соответствующие текущим вызовам в хендлерах** (батч + `correlation_id`). Хендлеры меняют только импорт. Добавление нового вендора = новый файл + строка в `registry._build_registry()` + флаг в `VENDORS_ENABLED`.

**Tech Stack:** Python 3.12 `typing.Protocol` (+ `runtime_checkable`), существующие httpx/urllib клиенты, `pydantic` для конфигов промптов.

**Spec:** [docs/superpowers/specs/2026-04-18-vendor-sync-readiness-design.md](../specs/2026-04-18-vendor-sync-readiness-design.md) §4, §7.4 (только сигнатура `ExportProvider`).

**Prereqs:** Plans 1 и 2 смержены. Миграции БД не нужны.

**Scope note:** Это **рефакторинг с обёртками** — наружное поведение хендлеров и логи не меняются. Сигнатуры Protocol-ов проектируем под реальные вызовы, а не под идеальную картину. Per-track API (`lookup_by_isrc`, `lookup_by_metadata`) добавим в Protocol позже, когда появится первый потребитель (Plan 4 — playlists). Сейчас в Lookup только `lookup_batch_by_isrc`.

---

## File Structure

Новые файлы:
```
src/collector/providers/
  __init__.py
  base.py                 # Protocols + dataclasses + RawIngestPayload
  registry.py             # ProviderBundle, _build_registry, аксессоры
  beatport.py             # BeatportProvider — обёртка над BeatportClient
  spotify/
    __init__.py
    lookup.py             # SpotifyLookup — обёртка над SpotifyClient
    enrich.py             # SpotifyEnricher — заглушка `release_type` через lookup
    export.py             # SpotifyExporter — stub, raises VendorDisabledError
  perplexity/
    __init__.py
    label.py              # PerplexityLabelEnricher — обёртка над search_label
    artist.py             # PerplexityArtistEnricher — stub, NotImplementedError
  ytmusic/
    __init__.py
    lookup.py             # YTMusicLookup — stub
    export.py             # YTMusicExporter — stub
  deezer/
    __init__.py
    lookup.py             # DeezerLookup — stub
    export.py             # DeezerExporter — stub
  apple/
    __init__.py
    lookup.py             # AppleLookup — stub
    export.py             # AppleExporter — stub
  tidal/
    __init__.py
    lookup.py             # TidalLookup — stub
    export.py             # TidalExporter — stub
```

Изменяемые файлы:
- `src/collector/handler.py` — импорт `BeatportClient` заменить на `registry.get_ingest("beatport").client` ИЛИ оставить прямой импорт `from .providers.beatport import BeatportProvider` (см. Task 3 — выбираем второй путь, прозрачнее).
- `src/collector/spotify_handler.py` — импорт `SpotifyClient` → `from .providers.spotify.lookup import SpotifyLookup`.
- `src/collector/search_handler.py` — диспатч по `prompt_slug` через `registry.get_enricher_for_prompt(prompt_slug)`.
- `src/collector/errors.py` — добавить `VendorDisabledError` (с правильным super-вызовом dataclass `AppError`).
- `src/collector/settings.py` — нет изменений: `VENDORS_ENABLED` читается напрямую из `os.environ` в registry (как сейчас сделано с другими env-переключателями вне `BaseSettings`).
- `CLAUDE.md`, `README.md` — добавить раздел про providers и `VENDORS_ENABLED`.

**НЕ удаляем** старые файлы `src/collector/beatport_client.py`, `src/collector/spotify_client.py`, `src/collector/search/perplexity_client.py`, `src/collector/search/prompts.py` — провайдеры импортируют их внутри. Это сознательное решение Variant A: меньше касаний, минимальный риск регрессий.

---

## Task 1: Protocols + dataclasses + `VendorDisabledError`

**Files:**
- Create: `src/collector/providers/__init__.py`
- Create: `src/collector/providers/base.py`
- Modify: `src/collector/errors.py` — добавить `VendorDisabledError`
- Test: `tests/unit/test_providers_base.py`

- [ ] **Step 1: Написать падающий тест**

Создать файл `tests/unit/test_providers_base.py`:

```python
"""Unit tests for provider Protocol surface and shared types."""
from __future__ import annotations

import pytest

from collector.errors import AppError, VendorDisabledError
from collector.providers.base import (
    EnrichProvider,
    EnrichResult,
    ExportProvider,
    IngestProvider,
    LookupProvider,
    ProviderBundle,
    RawIngestPayload,
    VendorPlaylistRef,
    VendorTrackRef,
)


def test_vendor_track_ref_is_frozen() -> None:
    ref = VendorTrackRef(
        vendor="spotify",
        vendor_track_id="abc",
        isrc="USRC00000001",
        artist_names=("Foo",),
        title="Bar",
        duration_ms=200_000,
        album_name="Baz",
        raw_payload={"id": "abc"},
    )
    assert ref.vendor == "spotify"
    assert ref.artist_names == ("Foo",)
    with pytest.raises(Exception):
        ref.vendor = "other"  # frozen dataclass


def test_provider_bundle_defaults_none() -> None:
    bundle = ProviderBundle()
    assert bundle.ingest is None
    assert bundle.lookup is None
    assert bundle.enrich is None
    assert bundle.export is None


def test_raw_ingest_payload_holds_source_and_meta() -> None:
    payload = RawIngestPayload(
        source="beatport",
        items=[{"id": 1}],
        meta={"pages": 2},
    )
    assert payload.source == "beatport"
    assert payload.items == [{"id": 1}]
    assert payload.meta == {"pages": 2}


def test_enrich_result_required_fields() -> None:
    result = EnrichResult(
        entity_type="label",
        entity_id="42",
        prompt_slug="label_info",
        prompt_version="v1",
        payload={"size": "small"},
    )
    assert result.entity_type == "label"
    assert result.payload == {"size": "small"}


def test_vendor_playlist_ref_basic() -> None:
    ref = VendorPlaylistRef(vendor="spotify", vendor_playlist_id="pl1", url=None)
    assert ref.vendor == "spotify"


def test_vendor_disabled_error_is_app_error() -> None:
    err = VendorDisabledError("ytmusic")
    assert isinstance(err, AppError)
    assert err.status_code == 400
    assert err.error_code == "vendor_disabled"
    assert "ytmusic" in err.message
    assert err.vendor == "ytmusic"
    assert "ytmusic" in str(err)


def test_protocol_classes_are_runtime_checkable() -> None:
    # Negative check — random object isn't a provider.
    assert not isinstance(object(), IngestProvider)
    assert not isinstance(object(), LookupProvider)
    assert not isinstance(object(), EnrichProvider)
    assert not isinstance(object(), ExportProvider)
```

- [ ] **Step 2: Запустить — FAIL (`ImportError`)**

```bash
pytest tests/unit/test_providers_base.py -v
```

Ожидаем: `ImportError: cannot import name 'VendorDisabledError' from 'collector.errors'` (или модуля `providers`).

- [ ] **Step 3: Создать `src/collector/providers/__init__.py`**

```python
"""Provider registry and vendor implementations."""
```

- [ ] **Step 4: Создать `src/collector/providers/base.py`**

```python
"""Provider Protocols and shared dataclasses for vendor integrations.

Variant A note: Protocol method signatures match the existing call sites
(batch + correlation_id), not the long-term per-track ideal. New methods
will be added when first consumed (e.g. per-track lookup for playlist
export in Plan 4).
"""

from __future__ import annotations

from dataclasses import dataclass
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
    items: list[dict[str, Any]]
    meta: dict[str, Any]


@runtime_checkable
class IngestProvider(Protocol):
    source_name: str

    def fetch_weekly_releases(
        self,
        bp_token: str,
        style_id: int,
        week_start: str,
        week_end: str,
        correlation_id: str,
    ) -> tuple[list[dict[str, Any]], int]:
        """Return (items, pages_fetched). Signature matches BeatportClient."""
        ...


@runtime_checkable
class LookupProvider(Protocol):
    vendor_name: str

    def lookup_batch_by_isrc(
        self,
        tracks: list[dict[str, str]],
        correlation_id: str,
    ) -> list[Any]:
        """Batch ISRC search. Returns provider-specific result objects."""
        ...


@runtime_checkable
class EnrichProvider(Protocol):
    vendor_name: str
    entity_types: tuple[str, ...]
    prompt_slug: str
    prompt_version: str

    def enrich(
        self,
        entity_type: str,
        entity_id: str,
        context: dict[str, Any],
        correlation_id: str,
    ) -> EnrichResult: ...


@runtime_checkable
class ExportProvider(Protocol):
    vendor_name: str

    def create_playlist(
        self,
        user_token: str,
        name: str,
        track_refs: list[VendorTrackRef],
    ) -> VendorPlaylistRef: ...


@dataclass(frozen=True)
class ProviderBundle:
    ingest: IngestProvider | None = None
    lookup: LookupProvider | None = None
    enrich: EnrichProvider | None = None
    export: ExportProvider | None = None
```

- [ ] **Step 5: Добавить `VendorDisabledError` в `src/collector/errors.py`**

В конец файла:

```python
class VendorDisabledError(AppError):
    def __init__(self, vendor: str) -> None:
        super().__init__(
            status_code=400,
            error_code="vendor_disabled",
            message=f"vendor is disabled or not implemented: {vendor}",
        )
        self.vendor = vendor
```

- [ ] **Step 6: Запустить — PASS**

```bash
pytest tests/unit/test_providers_base.py -v
```

Ожидаем: 7 passed.

- [ ] **Step 7: Прогнать полный suite, чтобы убедиться, что ничего не задели**

```bash
pytest -q
```

Ожидаем: все существующие тесты PASS.

- [ ] **Step 8: Коммит**

Сгенерировать сообщение через `caveman:caveman-commit`, затем:

```bash
git add src/collector/providers/__init__.py \
        src/collector/providers/base.py \
        src/collector/errors.py \
        tests/unit/test_providers_base.py
git commit -m "<caveman-commit output>"
```

---

## Task 2: Registry + `VENDORS_ENABLED` filter

**Files:**
- Create: `src/collector/providers/registry.py`
- Test: `tests/unit/test_providers_registry.py`

В этой задаче registry собирает только `BeatportProvider` (Task 3 ещё не сделан). Spotify/Perplexity/stubs импортируются в `_build_registry()` лениво начиная с Task 3+; до тех пор ставим временные **No-op заглушки**, чтобы тесты Task 2 проходили независимо.

- [ ] **Step 1: Написать падающий тест**

Создать `tests/unit/test_providers_registry.py`:

```python
"""Unit tests for provider registry and VENDORS_ENABLED gating."""
from __future__ import annotations

import pytest

from collector.errors import VendorDisabledError
from collector.providers import registry


@pytest.fixture(autouse=True)
def _reset_cache() -> None:
    registry.reset_cache()
    yield
    registry.reset_cache()


def test_enabled_vendors_parse_csv(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VENDORS_ENABLED", "beatport, spotify ,, ytmusic")
    assert registry._enabled_vendors() == {"beatport", "spotify", "ytmusic"}


def test_enabled_vendors_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VENDORS_ENABLED", "")
    assert registry._enabled_vendors() == set()


def test_get_disabled_vendor_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VENDORS_ENABLED", "")
    with pytest.raises(VendorDisabledError) as exc_info:
        registry.get_lookup("spotify")
    assert exc_info.value.vendor == "spotify"


def test_get_unknown_vendor_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VENDORS_ENABLED", "spotify")
    with pytest.raises(VendorDisabledError):
        registry.get_lookup("nonexistent")


def test_list_enabled_exporters_filters(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VENDORS_ENABLED", "ytmusic,deezer")
    names = sorted(p.vendor_name for p in registry.list_enabled_exporters())
    assert names == ["deezer", "ytmusic"]


def test_get_enricher_for_prompt_known(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VENDORS_ENABLED", "perplexity_label")
    enricher = registry.get_enricher_for_prompt("label_info")
    assert enricher.prompt_slug == "label_info"


def test_get_enricher_for_prompt_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VENDORS_ENABLED", "")
    with pytest.raises(VendorDisabledError):
        registry.get_enricher_for_prompt("label_info")


def test_get_enricher_for_prompt_unknown(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VENDORS_ENABLED", "perplexity_label")
    with pytest.raises(VendorDisabledError):
        registry.get_enricher_for_prompt("totally_unknown_slug")
```

- [ ] **Step 2: Запустить — FAIL** (`ImportError: cannot import name 'registry'`)

```bash
pytest tests/unit/test_providers_registry.py -v
```

- [ ] **Step 3: Создать `src/collector/providers/registry.py`**

```python
"""Provider registry — single public surface for vendor lookups.

VENDORS_ENABLED env var controls which vendors can be resolved:
  VENDORS_ENABLED="beatport,spotify,perplexity_label"

Vendors not in the list raise VendorDisabledError on access. The set is
re-read on every call, but the underlying provider instances are cached
via _registry() lru_cache. Use reset_cache() in tests after setenv.
"""

from __future__ import annotations

import functools
import os
from typing import Iterable

from ..errors import VendorDisabledError
from .base import (
    EnrichProvider,
    ExportProvider,
    IngestProvider,
    LookupProvider,
    ProviderBundle,
)


def _build_registry() -> dict[str, ProviderBundle]:
    """Construct provider bundles. Imports inlined to avoid import cycles."""
    # Task 2 placeholder — Task 3+ replace these with real providers.
    return {}


@functools.lru_cache(maxsize=1)
def _registry() -> dict[str, ProviderBundle]:
    return _build_registry()


def reset_cache() -> None:
    _registry.cache_clear()


def _enabled_vendors() -> set[str]:
    raw = os.environ.get("VENDORS_ENABLED", "").strip()
    if not raw:
        return set()
    return {part.strip() for part in raw.split(",") if part.strip()}


def _require_enabled_bundle(name: str) -> ProviderBundle:
    if name not in _enabled_vendors():
        raise VendorDisabledError(name)
    bundle = _registry().get(name)
    if bundle is None:
        raise VendorDisabledError(name)
    return bundle


def get_ingest(name: str) -> IngestProvider:
    bundle = _require_enabled_bundle(name)
    if bundle.ingest is None:
        raise VendorDisabledError(name)
    return bundle.ingest


def get_lookup(name: str) -> LookupProvider:
    bundle = _require_enabled_bundle(name)
    if bundle.lookup is None:
        raise VendorDisabledError(name)
    return bundle.lookup


def get_enricher(name: str) -> EnrichProvider:
    bundle = _require_enabled_bundle(name)
    if bundle.enrich is None:
        raise VendorDisabledError(name)
    return bundle.enrich


def get_enricher_for_prompt(prompt_slug: str) -> EnrichProvider:
    """Find an enabled enricher that handles the given prompt_slug.

    Raises VendorDisabledError if no enabled vendor exposes this slug.
    """
    enabled = _enabled_vendors()
    for name, bundle in _registry().items():
        if bundle.enrich is None:
            continue
        if bundle.enrich.prompt_slug != prompt_slug:
            continue
        if name not in enabled:
            continue
        return bundle.enrich
    raise VendorDisabledError(prompt_slug)


def get_exporter(name: str) -> ExportProvider:
    bundle = _require_enabled_bundle(name)
    if bundle.export is None:
        raise VendorDisabledError(name)
    return bundle.export


def list_enabled_exporters() -> Iterable[ExportProvider]:
    enabled = _enabled_vendors()
    for name, bundle in _registry().items():
        if name in enabled and bundle.export is not None:
            yield bundle.export
```

- [ ] **Step 4: Запустить тест — частично PASS**

```bash
pytest tests/unit/test_providers_registry.py -v
```

Ожидаем:
- `_enabled_vendors_*` — PASS.
- `get_disabled/unknown/...` — PASS (registry пуст, всё падает с `VendorDisabledError`).
- `get_enricher_for_prompt_known` — FAIL (нет `perplexity_label` в registry).
- `list_enabled_exporters_filters` — PASS, но `names == []` (нет вендоров).

`get_enricher_for_prompt_known` и `list_enabled_exporters_filters` починятся в Tasks 6 и 7 соответственно. **Помечаем их `@pytest.mark.skip(reason="enabled in Task 6/7")` временно**:

В `tests/unit/test_providers_registry.py` добавить декораторы:

```python
@pytest.mark.skip(reason="enabled in Task 7 (stub vendors)")
def test_list_enabled_exporters_filters(...): ...

@pytest.mark.skip(reason="enabled in Task 6 (perplexity)")
def test_get_enricher_for_prompt_known(...): ...
```

- [ ] **Step 5: Прогнать полный suite**

```bash
pytest -q
```

Ожидаем: всё PASS, два skip.

- [ ] **Step 6: Коммит**

```bash
git add src/collector/providers/registry.py \
        tests/unit/test_providers_registry.py
git commit -m "<caveman-commit output>"
```

---

## Task 3: `BeatportProvider` adapter + rewire `handler.py`

**Files:**
- Create: `src/collector/providers/beatport.py`
- Modify: `src/collector/providers/registry.py` — добавить bundle `beatport`
- Modify: `src/collector/handler.py:27,170` — заменить импорт и инстанциацию
- Test: `tests/unit/test_providers_beatport.py`

**Не удаляем** `src/collector/beatport_client.py` — провайдер импортирует `BeatportClient` оттуда.

- [ ] **Step 1: Написать падающий тест**

Создать `tests/unit/test_providers_beatport.py`:

```python
"""Unit tests for the BeatportProvider adapter."""
from __future__ import annotations

from typing import Any

import pytest

from collector.providers.base import IngestProvider
from collector.providers.beatport import BeatportProvider


def test_beatport_provider_implements_protocol() -> None:
    provider = BeatportProvider(base_url="https://example.test/v4/catalog")
    assert isinstance(provider, IngestProvider)
    assert provider.source_name == "beatport"


def test_beatport_provider_delegates_to_client(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    def fake_fetch(self: Any, **kwargs: Any) -> tuple[list[dict[str, Any]], int]:
        captured.update(kwargs)
        return [{"id": 1}], 3

    from collector.beatport_client import BeatportClient

    monkeypatch.setattr(BeatportClient, "fetch_weekly_releases", fake_fetch)

    provider = BeatportProvider(base_url="https://example.test/v4/catalog")
    items, pages = provider.fetch_weekly_releases(
        bp_token="tok",
        style_id=11,
        week_start="2026-01-05",
        week_end="2026-01-11",
        correlation_id="corr-1",
    )

    assert items == [{"id": 1}]
    assert pages == 3
    assert captured == {
        "bp_token": "tok",
        "style_id": 11,
        "week_start": "2026-01-05",
        "week_end": "2026-01-11",
        "correlation_id": "corr-1",
    }
```

- [ ] **Step 2: Запустить — FAIL** (`ImportError: cannot import name 'BeatportProvider'`)

```bash
pytest tests/unit/test_providers_beatport.py -v
```

- [ ] **Step 3: Создать `src/collector/providers/beatport.py`**

```python
"""BeatportProvider — IngestProvider adapter over BeatportClient."""

from __future__ import annotations

from typing import Any

from ..beatport_client import BeatportClient


class BeatportProvider:
    """Thin adapter — delegates everything to BeatportClient.

    Exists so handlers depend on the providers package surface, not on
    vendor-specific modules. Internal client behavior (retries, pagination,
    correlation_id propagation) is preserved as-is.
    """

    source_name = "beatport"

    def __init__(
        self,
        base_url: str,
        client: BeatportClient | None = None,
    ) -> None:
        self._client = client or BeatportClient(base_url=base_url)

    def fetch_weekly_releases(
        self,
        bp_token: str,
        style_id: int,
        week_start: str,
        week_end: str,
        correlation_id: str,
    ) -> tuple[list[dict[str, Any]], int]:
        return self._client.fetch_weekly_releases(
            bp_token=bp_token,
            style_id=style_id,
            week_start=week_start,
            week_end=week_end,
            correlation_id=correlation_id,
        )
```

- [ ] **Step 4: Подключить в `_build_registry()`**

В `src/collector/providers/registry.py` заменить тело `_build_registry()`:

```python
def _build_registry() -> dict[str, ProviderBundle]:
    from .beatport import BeatportProvider
    # NOTE: BeatportProvider needs base_url from settings, but registry must
    # not depend on settings. Construct lazily — handlers pass base_url.
    # Workaround: lazily build in get_ingest("beatport") OR construct here
    # reading env directly (matches current handler that reads settings).

    from ..settings import get_api_settings
    api_settings = get_api_settings()

    return {
        "beatport": ProviderBundle(
            ingest=BeatportProvider(base_url=api_settings.beatport_api_base_url),
        ),
    }
```

- [ ] **Step 5: Запустить — PASS**

```bash
pytest tests/unit/test_providers_beatport.py -v
```

- [ ] **Step 6: Перевести `handler.py` на провайдер**

В `src/collector/handler.py`:

Заменить строку 27:
```python
from .beatport_client import BeatportClient
```
на:
```python
from .providers.beatport import BeatportProvider
```

Заменить строку 170:
```python
beatport_client = BeatportClient(base_url=settings.beatport_api_base_url)
```
на:
```python
beatport_client = BeatportProvider(base_url=settings.beatport_api_base_url)
```

(Имя локальной переменной `beatport_client` оставляем — меньше дифф.)

- [ ] **Step 7: Прогнать существующие тесты handler.py**

```bash
pytest tests/unit/test_handler.py tests/integration/test_handler.py -v
```

Ожидаем: PASS. Если тесты мокают `collector.handler.BeatportClient` — переименовать таргет на `collector.handler.BeatportProvider`. Найти такие места:

```bash
grep -rn "collector.handler.BeatportClient\|handler\.BeatportClient" tests/
```

Заменить на `BeatportProvider`. Если тест мокает на уровне `collector.beatport_client.BeatportClient` — это тоже работает (внутренний клиент тот же), оставить.

- [ ] **Step 8: Прогнать полный suite**

```bash
pytest -q
```

Ожидаем: всё PASS.

- [ ] **Step 9: Коммит**

```bash
git add src/collector/providers/beatport.py \
        src/collector/providers/registry.py \
        src/collector/handler.py \
        tests/unit/test_providers_beatport.py \
        tests/unit/test_handler.py
git commit -m "<caveman-commit output>"
```

---

## Task 4: `SpotifyLookup` adapter + rewire `spotify_handler.py`

**Files:**
- Create: `src/collector/providers/spotify/__init__.py`
- Create: `src/collector/providers/spotify/lookup.py`
- Modify: `src/collector/providers/registry.py` — добавить bundle `spotify`
- Modify: `src/collector/spotify_handler.py:26,158-161,168` — импорт + инстанциация
- Test: `tests/unit/test_providers_spotify_lookup.py`

**Не удаляем** `src/collector/spotify_client.py` — `SpotifyLookup` импортирует `SpotifyClient` и `SpotifySearchResult`.

- [ ] **Step 1: Написать падающий тест**

Создать `tests/unit/test_providers_spotify_lookup.py`:

```python
"""Unit tests for SpotifyLookup adapter."""
from __future__ import annotations

from typing import Any

import pytest

from collector.providers.base import LookupProvider
from collector.providers.spotify.lookup import SpotifyLookup


def test_spotify_lookup_implements_protocol() -> None:
    lookup = SpotifyLookup(client_id="cid", client_secret="csec")
    assert isinstance(lookup, LookupProvider)
    assert lookup.vendor_name == "spotify"


def test_spotify_lookup_delegates_to_client(monkeypatch: pytest.MonkeyPatch) -> None:
    from collector.spotify_client import SpotifyClient, SpotifySearchResult

    captured: dict[str, Any] = {}

    def fake_search(
        self: Any,
        tracks: list[dict[str, str]],
        correlation_id: str,
    ) -> list[SpotifySearchResult]:
        captured["tracks"] = tracks
        captured["correlation_id"] = correlation_id
        return [
            SpotifySearchResult(
                isrc="USRC00000001",
                clouder_track_id="t1",
                spotify_track={"id": "sp1"},
                spotify_id="sp1",
            )
        ]

    monkeypatch.setattr(SpotifyClient, "search_tracks_by_isrc", fake_search)

    lookup = SpotifyLookup(client_id="cid", client_secret="csec")
    results = lookup.lookup_batch_by_isrc(
        tracks=[{"clouder_track_id": "t1", "isrc": "USRC00000001"}],
        correlation_id="corr-9",
    )

    assert len(results) == 1
    assert results[0].spotify_id == "sp1"
    assert captured["tracks"] == [
        {"clouder_track_id": "t1", "isrc": "USRC00000001"}
    ]
    assert captured["correlation_id"] == "corr-9"
```

- [ ] **Step 2: Запустить — FAIL**

- [ ] **Step 3: Создать пакет**

`src/collector/providers/spotify/__init__.py`:
```python
"""Spotify provider implementations (lookup, enrich, export)."""
```

`src/collector/providers/spotify/lookup.py`:
```python
"""SpotifyLookup — LookupProvider adapter over SpotifyClient."""

from __future__ import annotations

from ...spotify_client import SpotifyClient, SpotifySearchResult


class SpotifyLookup:
    """Thin adapter — delegates batch ISRC search to SpotifyClient.

    The underlying client caches its OAuth token across calls; we keep
    the client instance on self so spotify_handler reuses one auth handshake
    per worker invocation, exactly as before this refactor.
    """

    vendor_name = "spotify"

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        client: SpotifyClient | None = None,
    ) -> None:
        self._client = client or SpotifyClient(
            client_id=client_id,
            client_secret=client_secret,
        )

    def lookup_batch_by_isrc(
        self,
        tracks: list[dict[str, str]],
        correlation_id: str,
    ) -> list[SpotifySearchResult]:
        return self._client.search_tracks_by_isrc(
            tracks=tracks,
            correlation_id=correlation_id,
        )
```

- [ ] **Step 4: Подключить в `_build_registry()`**

В `src/collector/providers/registry.py` добавить:

```python
def _build_registry() -> dict[str, ProviderBundle]:
    from .beatport import BeatportProvider
    from .spotify.lookup import SpotifyLookup
    from ..settings import get_api_settings, get_spotify_worker_settings

    api_settings = get_api_settings()
    sp_settings = get_spotify_worker_settings()

    return {
        "beatport": ProviderBundle(
            ingest=BeatportProvider(base_url=api_settings.beatport_api_base_url),
        ),
        "spotify": ProviderBundle(
            lookup=SpotifyLookup(
                client_id=sp_settings.spotify_client_id,
                client_secret=sp_settings.spotify_client_secret,
            ),
        ),
    }
```

- [ ] **Step 5: Запустить тест адаптера — PASS**

```bash
pytest tests/unit/test_providers_spotify_lookup.py -v
```

- [ ] **Step 6: Перевести `spotify_handler.py`**

В `src/collector/spotify_handler.py`:

Строка 26 — заменить:
```python
from .spotify_client import SpotifyClient, SpotifySearchResult
```
на:
```python
from .providers.spotify.lookup import SpotifyLookup
from .spotify_client import SpotifySearchResult  # тип всё ещё нужен в _process_results_chunk
```

Строки 158-161 — заменить:
```python
client = SpotifyClient(
    client_id=settings.spotify_client_id,
    client_secret=settings.spotify_client_secret,
)
```
на:
```python
client = SpotifyLookup(
    client_id=settings.spotify_client_id,
    client_secret=settings.spotify_client_secret,
)
```

Строки 168-171 — заменить вызов:
```python
results = client.search_tracks_by_isrc(
    tracks=search_input,
    correlation_id=correlation_id,
)
```
на:
```python
results = client.lookup_batch_by_isrc(
    tracks=search_input,
    correlation_id=correlation_id,
)
```

- [ ] **Step 7: Обновить тесты `test_spotify_handler.py`**

```bash
grep -n "SpotifyClient\|search_tracks_by_isrc" tests/unit/test_spotify_handler.py
```

Каждое вхождение `monkeypatch.setattr(SpotifyClient, "search_tracks_by_isrc", ...)` заменить на:
```python
monkeypatch.setattr(
    "collector.providers.spotify.lookup.SpotifyLookup.lookup_batch_by_isrc",
    fake_search,
)
```

Каждое вхождение `monkeypatch.setattr("collector.spotify_handler.SpotifyClient", ...)` (если есть) заменить на `SpotifyLookup`.

- [ ] **Step 8: Прогнать тесты spotify_handler**

```bash
pytest tests/unit/test_spotify_handler.py tests/integration/test_spotify_handler.py -v
```

Ожидаем: PASS. Если упало — внимательно прочитать ошибку: чаще всего сигнатура `fake_search(self, tracks, correlation_id)` теперь должна быть `fake_search(self, tracks, correlation_id)` (вместо `fake_search(self, tracks, correlation_id)` для `SpotifyClient`). Сигнатуры одинаковые, должно работать.

- [ ] **Step 9: Прогнать полный suite**

```bash
pytest -q
```

- [ ] **Step 10: Коммит**

```bash
git add src/collector/providers/spotify/__init__.py \
        src/collector/providers/spotify/lookup.py \
        src/collector/providers/registry.py \
        src/collector/spotify_handler.py \
        tests/unit/test_providers_spotify_lookup.py \
        tests/unit/test_spotify_handler.py
git commit -m "<caveman-commit output>"
```

---

## Task 5: `SpotifyEnricher` + `SpotifyExporter` (scaffolds)

**Files:**
- Create: `src/collector/providers/spotify/enrich.py`
- Create: `src/collector/providers/spotify/export.py`
- Modify: `src/collector/providers/registry.py` — заполнить `enrich` + `export` для bundle `spotify`
- Test: `tests/unit/test_providers_spotify_enrich.py`
- Test: `tests/unit/test_providers_spotify_export.py`

`SpotifyEnricher` сейчас не подключён ни в один хендлер — это задел для будущего pipeline-а, где album_type будет тянуться через единый интерфейс enrich. Текущий `spotify_handler` продолжает извлекать `album_type` напрямую (строки 33-44 + 282-289) — не трогаем.

- [ ] **Step 1: Тесты enricher**

Создать `tests/unit/test_providers_spotify_enrich.py`:

```python
"""Unit tests for SpotifyEnricher (release_type extraction)."""
from __future__ import annotations

from typing import Any

import pytest

from collector.providers.base import EnrichProvider, EnrichResult
from collector.providers.spotify.enrich import SpotifyEnricher
from collector.providers.spotify.lookup import SpotifyLookup
from collector.spotify_client import SpotifySearchResult


class _FakeLookup:
    vendor_name = "spotify"

    def __init__(self, result: SpotifySearchResult | None) -> None:
        self._result = result

    def lookup_batch_by_isrc(
        self, tracks: list[dict[str, str]], correlation_id: str
    ) -> list[SpotifySearchResult]:
        return [self._result] if self._result else []


def test_enricher_implements_protocol() -> None:
    enricher = SpotifyEnricher(lookup=_FakeLookup(None))
    assert isinstance(enricher, EnrichProvider)
    assert enricher.entity_types == ("track",)
    assert enricher.prompt_slug == "spotify_release_type"


def test_enricher_returns_album_type_when_found() -> None:
    fake = _FakeLookup(
        SpotifySearchResult(
            isrc="USRC00000001",
            clouder_track_id="t1",
            spotify_track={"id": "sp1", "album": {"album_type": "single"}},
            spotify_id="sp1",
        )
    )
    enricher = SpotifyEnricher(lookup=fake)
    result = enricher.enrich(
        entity_type="track",
        entity_id="t1",
        context={"isrc": "USRC00000001"},
        correlation_id="corr",
    )
    assert isinstance(result, EnrichResult)
    assert result.payload == {"spotify_id": "sp1", "album_type": "single"}


def test_enricher_returns_no_isrc_when_missing() -> None:
    enricher = SpotifyEnricher(lookup=_FakeLookup(None))
    result = enricher.enrich(
        entity_type="track",
        entity_id="t1",
        context={},
        correlation_id="corr",
    )
    assert result.payload == {"status": "no_isrc"}


def test_enricher_returns_not_found() -> None:
    fake = _FakeLookup(
        SpotifySearchResult(
            isrc="USRC00000001",
            clouder_track_id="t1",
            spotify_track=None,
            spotify_id=None,
        )
    )
    enricher = SpotifyEnricher(lookup=fake)
    result = enricher.enrich(
        entity_type="track",
        entity_id="t1",
        context={"isrc": "USRC00000001"},
        correlation_id="corr",
    )
    assert result.payload == {"status": "not_found"}


def test_enricher_rejects_wrong_entity_type() -> None:
    enricher = SpotifyEnricher(lookup=_FakeLookup(None))
    with pytest.raises(ValueError, match="entity_type=track"):
        enricher.enrich(
            entity_type="label",
            entity_id="x",
            context={},
            correlation_id="corr",
        )
```

- [ ] **Step 2: Тесты exporter**

Создать `tests/unit/test_providers_spotify_export.py`:

```python
"""Unit tests for SpotifyExporter stub."""
from __future__ import annotations

import pytest

from collector.errors import VendorDisabledError
from collector.providers.base import ExportProvider
from collector.providers.spotify.export import SpotifyExporter


def test_exporter_implements_protocol() -> None:
    exporter = SpotifyExporter()
    assert isinstance(exporter, ExportProvider)
    assert exporter.vendor_name == "spotify"


def test_exporter_raises_until_implemented() -> None:
    exporter = SpotifyExporter()
    with pytest.raises(VendorDisabledError) as exc_info:
        exporter.create_playlist(user_token="t", name="n", track_refs=[])
    assert "spotify" in exc_info.value.vendor
```

- [ ] **Step 3: Запустить — FAIL**

- [ ] **Step 4: Создать `src/collector/providers/spotify/enrich.py`**

```python
"""SpotifyEnricher — wraps SpotifyLookup to expose release_type as EnrichResult.

Currently NOT wired to any handler. Scaffolded so future pipelines can
treat album_type extraction as a generic EnrichProvider call instead of
a Spotify-specific path inside spotify_handler.
"""

from __future__ import annotations

from typing import Any

from ..base import EnrichResult
from .lookup import SpotifyLookup


class SpotifyEnricher:
    vendor_name = "spotify"
    entity_types = ("track",)
    prompt_slug = "spotify_release_type"
    prompt_version = "v1"

    def __init__(self, lookup: SpotifyLookup) -> None:
        self._lookup = lookup

    def enrich(
        self,
        entity_type: str,
        entity_id: str,
        context: dict[str, Any],
        correlation_id: str,
    ) -> EnrichResult:
        if entity_type != "track":
            raise ValueError(
                f"SpotifyEnricher supports entity_type=track, got {entity_type}"
            )

        isrc = context.get("isrc")
        if not isrc:
            return self._wrap(entity_id, {"status": "no_isrc"})

        results = self._lookup.lookup_batch_by_isrc(
            tracks=[{"clouder_track_id": entity_id, "isrc": str(isrc)}],
            correlation_id=correlation_id,
        )
        if not results or not results[0].spotify_id:
            return self._wrap(entity_id, {"status": "not_found"})

        track = results[0].spotify_track or {}
        album_type = (track.get("album") or {}).get("album_type")
        return self._wrap(
            entity_id,
            {"spotify_id": results[0].spotify_id, "album_type": album_type},
        )

    def _wrap(self, entity_id: str, payload: dict[str, Any]) -> EnrichResult:
        return EnrichResult(
            entity_type="track",
            entity_id=entity_id,
            prompt_slug=self.prompt_slug,
            prompt_version=self.prompt_version,
            payload=payload,
        )
```

- [ ] **Step 5: Создать `src/collector/providers/spotify/export.py`**

```python
"""SpotifyExporter — stub. Real implementation requires user OAuth (Plan 4)."""

from __future__ import annotations

from ...errors import VendorDisabledError
from ..base import VendorPlaylistRef, VendorTrackRef


class SpotifyExporter:
    vendor_name = "spotify"

    def create_playlist(
        self,
        user_token: str,
        name: str,
        track_refs: list[VendorTrackRef],
    ) -> VendorPlaylistRef:
        raise VendorDisabledError("spotify")
```

- [ ] **Step 6: Заполнить `spotify` bundle**

В `src/collector/providers/registry.py` обновить bundle `spotify` — переиспользовать **один** инстанс `SpotifyLookup` для `lookup` и `enrich`, чтобы OAuth-токен кэшировался во внутреннем `SpotifyClient` единым экземпляром:

```python
spotify_lookup = SpotifyLookup(
    client_id=sp_settings.spotify_client_id,
    client_secret=sp_settings.spotify_client_secret,
)
# ...
"spotify": ProviderBundle(
    lookup=spotify_lookup,
    enrich=SpotifyEnricher(lookup=spotify_lookup),
    export=SpotifyExporter(),
),
```

И добавить импорты в начале `_build_registry`:
```python
from .spotify.enrich import SpotifyEnricher
from .spotify.export import SpotifyExporter
```

- [ ] **Step 7: Запустить тесты Task 5 — PASS**

```bash
pytest tests/unit/test_providers_spotify_enrich.py tests/unit/test_providers_spotify_export.py -v
```

- [ ] **Step 8: Прогнать полный suite**

```bash
pytest -q
```

- [ ] **Step 9: Коммит**

```bash
git add src/collector/providers/spotify/enrich.py \
        src/collector/providers/spotify/export.py \
        src/collector/providers/registry.py \
        tests/unit/test_providers_spotify_enrich.py \
        tests/unit/test_providers_spotify_export.py
git commit -m "<caveman-commit output>"
```

---

## Task 6: `PerplexityLabelEnricher` + `PerplexityArtistEnricher` stub + rewire `search_handler.py`

**Files:**
- Create: `src/collector/providers/perplexity/__init__.py`
- Create: `src/collector/providers/perplexity/label.py`
- Create: `src/collector/providers/perplexity/artist.py`
- Modify: `src/collector/providers/registry.py` — bundle `perplexity_label` + `perplexity_artist`
- Modify: `src/collector/search_handler.py:18-19,105-209` — диспатч через registry
- Test: `tests/unit/test_providers_perplexity_label.py`
- Test: `tests/unit/test_providers_perplexity_artist.py`

**Не удаляем** `src/collector/search/perplexity_client.py` и `src/collector/search/prompts.py` — провайдер их использует.

- [ ] **Step 1: Тесты label enricher**

Создать `tests/unit/test_providers_perplexity_label.py`:

```python
"""Unit tests for PerplexityLabelEnricher adapter."""
from __future__ import annotations

from typing import Any

import pytest

from collector.providers.base import EnrichProvider, EnrichResult
from collector.providers.perplexity.label import PerplexityLabelEnricher
from collector.search.schemas import AIContentStatus, LabelSearchResult


def test_enricher_implements_protocol() -> None:
    enricher = PerplexityLabelEnricher(api_key="key")
    assert isinstance(enricher, EnrichProvider)
    assert enricher.vendor_name == "perplexity_label"
    assert enricher.entity_types == ("label",)
    assert enricher.prompt_slug == "label_info"


def test_enricher_calls_search_label(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    def fake_search(label_name: str, style: str, config: Any, api_key: str) -> Any:
        captured["label_name"] = label_name
        captured["style"] = style
        captured["api_key"] = api_key
        captured["prompt_slug"] = config.slug
        return LabelSearchResult(
            size="small",
            age="new",
            founded_year=None,
            ai_content=AIContentStatus.NONE_DETECTED,
            confidence=0.85,
            sources=[],
        )

    monkeypatch.setattr(
        "collector.providers.perplexity.label.search_label", fake_search
    )

    enricher = PerplexityLabelEnricher(api_key="my-key")
    result = enricher.enrich(
        entity_type="label",
        entity_id="lbl-1",
        context={"label_name": "FooRec", "styles": "Techno"},
        correlation_id="corr",
    )

    assert isinstance(result, EnrichResult)
    assert result.entity_id == "lbl-1"
    assert result.prompt_slug == "label_info"
    assert result.payload["confidence"] == 0.85
    assert captured == {
        "label_name": "FooRec",
        "style": "Techno",
        "api_key": "my-key",
        "prompt_slug": "label_info",
    }


def test_enricher_rejects_non_label_entity() -> None:
    enricher = PerplexityLabelEnricher(api_key="k")
    with pytest.raises(ValueError, match="entity_type=label"):
        enricher.enrich(
            entity_type="track",
            entity_id="x",
            context={},
            correlation_id="c",
        )


def test_enricher_validates_context() -> None:
    enricher = PerplexityLabelEnricher(api_key="k")
    with pytest.raises(ValueError, match="label_name"):
        enricher.enrich(
            entity_type="label",
            entity_id="x",
            context={"styles": "Techno"},
            correlation_id="c",
        )
```

- [ ] **Step 2: Тесты artist stub**

Создать `tests/unit/test_providers_perplexity_artist.py`:

```python
"""Unit tests for PerplexityArtistEnricher stub."""
from __future__ import annotations

import pytest

from collector.providers.base import EnrichProvider
from collector.providers.perplexity.artist import PerplexityArtistEnricher


def test_artist_enricher_implements_protocol() -> None:
    enricher = PerplexityArtistEnricher(api_key="k")
    assert isinstance(enricher, EnrichProvider)
    assert enricher.vendor_name == "perplexity_artist"
    assert enricher.entity_types == ("artist",)


def test_artist_enricher_not_implemented() -> None:
    enricher = PerplexityArtistEnricher(api_key="k")
    with pytest.raises(NotImplementedError):
        enricher.enrich(
            entity_type="artist",
            entity_id="a",
            context={},
            correlation_id="c",
        )
```

- [ ] **Step 3: Запустить — FAIL**

- [ ] **Step 4: Создать пакет**

`src/collector/providers/perplexity/__init__.py`:
```python
"""Perplexity-backed enrichment providers (label, artist)."""
```

`src/collector/providers/perplexity/label.py`:
```python
"""PerplexityLabelEnricher — EnrichProvider adapter over search_label()."""

from __future__ import annotations

from typing import Any

from ...search.perplexity_client import search_label
from ...search.prompts import get_prompt
from ..base import EnrichResult


class PerplexityLabelEnricher:
    vendor_name = "perplexity_label"
    entity_types = ("label",)
    prompt_slug = "label_info"
    prompt_version = "v1"

    def __init__(self, api_key: str) -> None:
        self._api_key = api_key

    def enrich(
        self,
        entity_type: str,
        entity_id: str,
        context: dict[str, Any],
        correlation_id: str,
    ) -> EnrichResult:
        if entity_type != "label":
            raise ValueError(
                f"PerplexityLabelEnricher supports entity_type=label, got {entity_type}"
            )

        label_name = str(context.get("label_name", "")).strip()
        styles = str(context.get("styles", "")).strip()
        if not label_name:
            raise ValueError("context.label_name is required")
        if not styles:
            raise ValueError("context.styles is required")

        config = get_prompt(self.prompt_slug, self.prompt_version)
        result = search_label(
            label_name=label_name,
            style=styles,
            config=config,
            api_key=self._api_key,
        )
        return EnrichResult(
            entity_type=entity_type,
            entity_id=entity_id,
            prompt_slug=self.prompt_slug,
            prompt_version=self.prompt_version,
            payload=result.model_dump(),
        )
```

`src/collector/providers/perplexity/artist.py`:
```python
"""PerplexityArtistEnricher — stub. Wire to a real prompt when artist research lands."""

from __future__ import annotations

from typing import Any

from ..base import EnrichResult


class PerplexityArtistEnricher:
    vendor_name = "perplexity_artist"
    entity_types = ("artist",)
    prompt_slug = "artist_info"
    prompt_version = "v1"

    def __init__(self, api_key: str) -> None:
        self._api_key = api_key

    def enrich(
        self,
        entity_type: str,
        entity_id: str,
        context: dict[str, Any],
        correlation_id: str,
    ) -> EnrichResult:
        raise NotImplementedError(
            "artist enrichment not yet wired to a prompt"
        )
```

- [ ] **Step 5: Подключить в registry**

В `src/collector/providers/registry.py`:

В импорты `_build_registry` добавить:
```python
from .perplexity.label import PerplexityLabelEnricher
from .perplexity.artist import PerplexityArtistEnricher
from ..settings import get_search_worker_settings
```

В возвращаемый dict добавить:
```python
"perplexity_label": ProviderBundle(
    enrich=PerplexityLabelEnricher(
        api_key=get_search_worker_settings().perplexity_api_key,
    ),
),
"perplexity_artist": ProviderBundle(
    enrich=PerplexityArtistEnricher(
        api_key=get_search_worker_settings().perplexity_api_key,
    ),
),
```

- [ ] **Step 6: Запустить тесты Task 6 — PASS**

```bash
pytest tests/unit/test_providers_perplexity_label.py \
       tests/unit/test_providers_perplexity_artist.py -v
```

- [ ] **Step 7: Снять `@pytest.mark.skip` с `test_get_enricher_for_prompt_known`**

В `tests/unit/test_providers_registry.py` удалить декоратор `@pytest.mark.skip` у `test_get_enricher_for_prompt_known` (тест из Task 2).

- [ ] **Step 8: Перевести `search_handler.py` на registry**

В `src/collector/search_handler.py`:

Удалить строки 18-19:
```python
from .search.perplexity_client import search_label
from .search.prompts import get_prompt
```

Добавить:
```python
from .errors import VendorDisabledError
from .providers import registry
from .providers.base import EnrichResult
```

Заменить `_dispatch_entity_search` (строки 105-122) и `_run_label_search` (строки 125-209) **одной** функцией:

```python
def _dispatch_entity_search(
    message: EntitySearchMessage,
    settings: Any,
    repository: Any,
    correlation_id: str,
) -> bool:
    try:
        enricher = registry.get_enricher_for_prompt(message.prompt_slug)
    except VendorDisabledError:
        log_event(
            "WARNING",
            "search_entity_type_unsupported",
            correlation_id=correlation_id,
            entity_type=message.entity_type,
            entity_id=message.entity_id,
            prompt_slug=message.prompt_slug,
        )
        return False

    log_event(
        "INFO",
        "label_search_started" if message.entity_type == "label" else "entity_search_started",
        correlation_id=correlation_id,
        entity_id=message.entity_id,
        entity_type=message.entity_type,
        prompt_slug=message.prompt_slug,
        prompt_version=message.prompt_version,
    )

    try:
        result: EnrichResult = enricher.enrich(
            entity_type=message.entity_type,
            entity_id=message.entity_id,
            context=dict(message.context),
            correlation_id=correlation_id,
        )
        repository.save_search_result(
            result_id=str(uuid4()),
            entity_type=message.entity_type,
            entity_id=message.entity_id,
            prompt_slug=message.prompt_slug,
            prompt_version=message.prompt_version,
            result=result.payload,
            searched_at=utc_now(),
        )
        # propagate_ai_flag still expects a LabelSearchResult; reconstruct from payload.
        if message.entity_type == "label":
            from .search.schemas import LabelSearchResult
            propagate_ai_flag(
                repository,
                entity_type="label",
                entity_id=message.entity_id,
                result=LabelSearchResult.model_validate(result.payload),
                threshold=settings.ai_flag_confidence_threshold,
            )
        log_event(
            "INFO",
            "label_search_completed" if message.entity_type == "label" else "entity_search_completed",
            correlation_id=correlation_id,
            entity_id=message.entity_id,
            prompt_slug=message.prompt_slug,
            prompt_version=message.prompt_version,
            status_code=200,
        )
        return True
    except Exception as exc:
        is_permanent = isinstance(exc, (ValueError, TypeError, KeyError, NotImplementedError))
        error_code = (
            "search_permanent_failure"
            if is_permanent
            else "search_transient_failure"
        )
        log_event(
            "ERROR",
            "label_search_failed" if message.entity_type == "label" else "entity_search_failed",
            correlation_id=correlation_id,
            entity_id=message.entity_id,
            error_code=error_code,
            error_type=exc.__class__.__name__,
            error_message=str(exc)[:500],
            status_code=500,
        )
        if is_permanent:
            return False
        raise
```

(Старый `_run_label_search` удалить целиком.)

- [ ] **Step 9: Обновить тесты `test_search_handler.py`**

Найти все вхождения старых хуков:
```bash
grep -n "search_label\|get_prompt\|_run_label_search" tests/unit/test_search_handler.py
```

Заменить:
- `monkeypatch.setattr("collector.search_handler.search_label", ...)` →
  `monkeypatch.setattr("collector.providers.perplexity.label.search_label", ...)`
- `monkeypatch.setattr("collector.search_handler.get_prompt", ...)` →
  `monkeypatch.setattr("collector.providers.perplexity.label.get_prompt", ...)`

Перед каждым тестом, использующим registry, должно быть выставлено `VENDORS_ENABLED`:
```python
@pytest.fixture(autouse=True)
def _enable_perplexity(monkeypatch):
    monkeypatch.setenv("VENDORS_ENABLED", "perplexity_label")
    from collector.providers import registry
    registry.reset_cache()
    yield
    registry.reset_cache()
```

- [ ] **Step 10: Прогнать тесты search_handler**

```bash
pytest tests/unit/test_search_handler.py tests/integration/test_search_handler.py -v
```

- [ ] **Step 11: Прогнать полный suite**

```bash
pytest -q
```

- [ ] **Step 12: Коммит**

```bash
git add src/collector/providers/perplexity/__init__.py \
        src/collector/providers/perplexity/label.py \
        src/collector/providers/perplexity/artist.py \
        src/collector/providers/registry.py \
        src/collector/search_handler.py \
        tests/unit/test_providers_perplexity_label.py \
        tests/unit/test_providers_perplexity_artist.py \
        tests/unit/test_providers_registry.py \
        tests/unit/test_search_handler.py
git commit -m "<caveman-commit output>"
```

---

## Task 7: Stub vendors (YT Music / Deezer / Apple / Tidal) + contract tests

Один файл-шаблон, повторяется 4 раза. Реализуем сразу всех.

**Files:**
- Create per vendor (`ytmusic`, `deezer`, `apple`, `tidal`):
  - `src/collector/providers/<vendor>/__init__.py`
  - `src/collector/providers/<vendor>/lookup.py`
  - `src/collector/providers/<vendor>/export.py`
- Modify: `src/collector/providers/registry.py` — добавить bundle для каждого
- Test: `tests/contract/test_vendor_stubs.py`

- [ ] **Step 1: Тесты-контракты**

Создать `tests/contract/__init__.py` (если нет) и `tests/contract/test_vendor_stubs.py`:

```python
"""Contract tests — every stub vendor satisfies LookupProvider/ExportProvider
Protocol and raises VendorDisabledError on use."""
from __future__ import annotations

import pytest

from collector.errors import VendorDisabledError
from collector.providers import registry
from collector.providers.base import ExportProvider, LookupProvider


_STUB_VENDORS = ["ytmusic", "deezer", "apple", "tidal"]


@pytest.fixture(autouse=True)
def _enable_all_stubs(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VENDORS_ENABLED", ",".join(_STUB_VENDORS))
    registry.reset_cache()
    yield
    registry.reset_cache()


@pytest.mark.parametrize("name", _STUB_VENDORS)
def test_stub_lookup_satisfies_protocol(name: str) -> None:
    lookup = registry.get_lookup(name)
    assert isinstance(lookup, LookupProvider)
    assert lookup.vendor_name == name


@pytest.mark.parametrize("name", _STUB_VENDORS)
def test_stub_lookup_raises(name: str) -> None:
    lookup = registry.get_lookup(name)
    with pytest.raises(VendorDisabledError):
        lookup.lookup_batch_by_isrc(
            tracks=[{"clouder_track_id": "x", "isrc": "USRC00000001"}],
            correlation_id="c",
        )


@pytest.mark.parametrize("name", _STUB_VENDORS)
def test_stub_export_satisfies_protocol(name: str) -> None:
    exporter = registry.get_exporter(name)
    assert isinstance(exporter, ExportProvider)
    assert exporter.vendor_name == name


@pytest.mark.parametrize("name", _STUB_VENDORS)
def test_stub_export_raises(name: str) -> None:
    exporter = registry.get_exporter(name)
    with pytest.raises(VendorDisabledError):
        exporter.create_playlist(user_token="t", name="n", track_refs=[])
```

- [ ] **Step 2: Запустить — FAIL**

- [ ] **Step 3: Создать stub-файлы для всех 4 вендоров**

Для каждого `<vendor> in {ytmusic, deezer, apple, tidal}`:

`src/collector/providers/<vendor>/__init__.py`:
```python
"""<Vendor> provider stubs (lookup, export). Not implemented."""
```

`src/collector/providers/<vendor>/lookup.py`:
```python
"""<Vendor> lookup stub — raises VendorDisabledError until implemented."""

from __future__ import annotations

from typing import Any

from ...errors import VendorDisabledError


class <ClassPrefix>Lookup:
    vendor_name = "<vendor>"

    def lookup_batch_by_isrc(
        self,
        tracks: list[dict[str, str]],
        correlation_id: str,
    ) -> list[Any]:
        raise VendorDisabledError(self.vendor_name)
```

`src/collector/providers/<vendor>/export.py`:
```python
"""<Vendor> export stub — raises VendorDisabledError until implemented."""

from __future__ import annotations

from ...errors import VendorDisabledError
from ..base import VendorPlaylistRef, VendorTrackRef


class <ClassPrefix>Exporter:
    vendor_name = "<vendor>"

    def create_playlist(
        self,
        user_token: str,
        name: str,
        track_refs: list[VendorTrackRef],
    ) -> VendorPlaylistRef:
        raise VendorDisabledError(self.vendor_name)
```

Class prefixes: `YTMusic`, `Deezer`, `Apple`, `Tidal`.

- [ ] **Step 4: Подключить в registry**

В `src/collector/providers/registry.py` добавить импорты в `_build_registry`:

```python
from .ytmusic.lookup import YTMusicLookup
from .ytmusic.export import YTMusicExporter
from .deezer.lookup import DeezerLookup
from .deezer.export import DeezerExporter
from .apple.lookup import AppleLookup
from .apple.export import AppleExporter
from .tidal.lookup import TidalLookup
from .tidal.export import TidalExporter
```

Добавить bundles:

```python
"ytmusic": ProviderBundle(lookup=YTMusicLookup(), export=YTMusicExporter()),
"deezer":  ProviderBundle(lookup=DeezerLookup(),  export=DeezerExporter()),
"apple":   ProviderBundle(lookup=AppleLookup(),   export=AppleExporter()),
"tidal":   ProviderBundle(lookup=TidalLookup(),   export=TidalExporter()),
```

- [ ] **Step 5: Снять `@pytest.mark.skip` с `test_list_enabled_exporters_filters`**

В `tests/unit/test_providers_registry.py` удалить декоратор у `test_list_enabled_exporters_filters` (Task 2).

- [ ] **Step 6: Прогнать**

```bash
pytest tests/contract/ -v
pytest tests/unit/test_providers_registry.py -v
pytest -q
```

Все PASS.

- [ ] **Step 7: Коммит**

```bash
git add src/collector/providers/ytmusic/ \
        src/collector/providers/deezer/ \
        src/collector/providers/apple/ \
        src/collector/providers/tidal/ \
        src/collector/providers/registry.py \
        tests/contract/ \
        tests/unit/test_providers_registry.py
git commit -m "<caveman-commit output>"
```

---

## Task 8: Документация — `CLAUDE.md`, `README.md`, env-vars

**Files:**
- Modify: `CLAUDE.md`
- Modify: `README.md`

- [ ] **Step 1: `CLAUDE.md` — обновить раздел Layout**

Добавить в секцию `## Layout` после строки про `search/`:

```markdown
  - `providers/` — vendor abstraction layer
    - `base.py` — Protocols + dataclasses (`VendorTrackRef`, `EnrichResult`, ...)
    - `registry.py` — `get_lookup`/`get_enricher`/`get_exporter` accessors, gated by `VENDORS_ENABLED`
    - `<vendor>/` — adapters wrapping existing clients (`beatport`, `spotify`, `perplexity`) or stubs (`ytmusic`, `deezer`, `apple`, `tidal`)
```

- [ ] **Step 2: `CLAUDE.md` — обновить раздел Env Vars**

В подсекцию `API/Worker Lambda` добавить:

```markdown
**`VENDORS_ENABLED`** — comma-separated list of vendor names allowed at runtime (e.g. `"beatport,spotify,perplexity_label"`). Vendors not listed raise `VendorDisabledError` from registry accessors. Default: empty (all vendors disabled).
```

- [ ] **Step 3: `CLAUDE.md` — добавить gotcha**

В секцию `## Gotchas` добавить:

```markdown
- **Adding a new vendor** = create `providers/<vendor>/<role>.py` with a class implementing the relevant Protocol, register it in `providers/registry.py:_build_registry()`, and add its name to `VENDORS_ENABLED`. Three steps, no handler changes.
- **Provider classes are thin adapters.** Existing clients (`BeatportClient`, `SpotifyClient`, `search_label`) live in their original modules and are wrapped — do not duplicate vendor logic into `providers/`. Adapter signatures match handler call sites (batch + `correlation_id`), not the long-term per-track Protocol ideal.
```

- [ ] **Step 4: `README.md` — добавить секцию о вендорах**

Найти раздел про конфигурацию/env (например, под "Architecture" или "Configuration"). Добавить подраздел:

```markdown
### Vendor providers

The `src/collector/providers/` package abstracts third-party music services
behind role Protocols (`IngestProvider`, `LookupProvider`, `EnrichProvider`,
`ExportProvider`). Currently wrapped: Beatport (ingest), Spotify (lookup,
enrich, export-stub), Perplexity (label enrich). Stubbed: YT Music, Deezer,
Apple Music, Tidal — they satisfy the Protocols but raise `VendorDisabledError`
on use.

Activation is controlled by the `VENDORS_ENABLED` env var:

```
VENDORS_ENABLED=beatport,spotify,perplexity_label
```

Vendors not listed cannot be resolved via `registry.get_*()`.
```

- [ ] **Step 5: Коммит**

```bash
git add CLAUDE.md README.md
git commit -m "<caveman-commit output>"
```

---

## Execution Order Summary

1. Task 1 — Protocols + dataclasses + `VendorDisabledError` (TDD).
2. Task 2 — Registry скелет + `VENDORS_ENABLED` (часть тестов skip до Task 6/7).
3. Task 3 — `BeatportProvider` + rewire `handler.py`.
4. Task 4 — `SpotifyLookup` + rewire `spotify_handler.py`.
5. Task 5 — `SpotifyEnricher` + `SpotifyExporter` (scaffolds, not wired).
6. Task 6 — Perplexity wrappers + rewire `search_handler.py` → registry.
7. Task 7 — 4 stub-вендора + contract tests.
8. Task 8 — Документация.

После плана:
- Plans 4 и 5 могут опираться на `registry.get_exporter("ytmusic")` и т.п.
- Поведение всех существующих хендлеров не меняется.
- Старые модули (`beatport_client.py`, `spotify_client.py`, `search/perplexity_client.py`, `search/prompts.py`) остаются — провайдеры их используют.
- Per-track `LookupProvider.lookup_by_isrc(isrc) -> VendorTrackRef` добавим в Plan 4, когда появится первый потребитель (playlist export).

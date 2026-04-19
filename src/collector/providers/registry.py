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
    from .beatport import BeatportProvider
    from ..settings import get_api_settings

    api_settings = get_api_settings()

    return {
        "beatport": ProviderBundle(
            ingest=BeatportProvider(base_url=api_settings.beatport_api_base_url),
        ),
    }


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


def list_enabled_exporters() -> list[ExportProvider]:
    enabled = _enabled_vendors()
    return [
        bundle.export
        for name, bundle in _registry().items()
        if name in enabled and bundle.export is not None
    ]

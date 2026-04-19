"""Provider registry — single public surface for vendor lookups.

VENDORS_ENABLED env var controls which vendors can be resolved:
  VENDORS_ENABLED="beatport,spotify,perplexity_label"

Vendors not in the list raise VendorDisabledError on access. Provider
instances are constructed lazily — a vendor's bundle is only built when
that vendor is first needed, NOT eagerly at module load. Disabled
vendors are never instantiated, which keeps tests independent of
unrelated vendors' settings (e.g. a registry test that only checks
disabled-vendor handling does not need RAW_BUCKET_NAME to be set).

Use reset_cache() in tests after VENDORS_ENABLED setenv.
"""

from __future__ import annotations

import os
from collections.abc import Callable

from ..errors import VendorDisabledError
from .base import (
    EnrichProvider,
    ExportProvider,
    IngestProvider,
    LookupProvider,
    ProviderBundle,
)


def _build_beatport() -> ProviderBundle:
    """Construct the Beatport bundle. Imports inlined to avoid import cycles."""
    from .beatport import BeatportProvider
    from ..settings import get_api_settings

    return ProviderBundle(
        ingest=BeatportProvider(base_url=get_api_settings().beatport_api_base_url),
    )


def _build_spotify() -> ProviderBundle:
    """Construct the Spotify bundle. Imports inlined to avoid import cycles."""
    from .spotify.enrich import SpotifyEnricher
    from .spotify.export import SpotifyExporter
    from .spotify.lookup import SpotifyLookup
    from ..settings import get_spotify_worker_settings

    sp_settings = get_spotify_worker_settings()
    spotify_lookup = SpotifyLookup(
        client_id=sp_settings.spotify_client_id,
        client_secret=sp_settings.spotify_client_secret,
    )
    return ProviderBundle(
        lookup=spotify_lookup,
        enrich=SpotifyEnricher(lookup=spotify_lookup),
        export=SpotifyExporter(),
    )


def _build_perplexity_label() -> ProviderBundle:
    """Construct the Perplexity label bundle. Imports inlined to avoid import cycles."""
    from .perplexity.label import PerplexityLabelEnricher
    from ..settings import get_search_worker_settings

    return ProviderBundle(
        enrich=PerplexityLabelEnricher(
            api_key=get_search_worker_settings().perplexity_api_key,
        ),
    )


def _build_perplexity_artist() -> ProviderBundle:
    """Construct the Perplexity artist bundle. Imports inlined to avoid import cycles."""
    from .perplexity.artist import PerplexityArtistEnricher
    from ..settings import get_search_worker_settings

    return ProviderBundle(
        enrich=PerplexityArtistEnricher(
            api_key=get_search_worker_settings().perplexity_api_key,
        ),
    )


def _build_ytmusic() -> ProviderBundle:
    from .ytmusic.lookup import YTMusicLookup
    from .ytmusic.export import YTMusicExporter

    return ProviderBundle(lookup=YTMusicLookup(), export=YTMusicExporter())


def _build_deezer() -> ProviderBundle:
    from .deezer.lookup import DeezerLookup
    from .deezer.export import DeezerExporter

    return ProviderBundle(lookup=DeezerLookup(), export=DeezerExporter())


def _build_apple() -> ProviderBundle:
    from .apple.lookup import AppleLookup
    from .apple.export import AppleExporter

    return ProviderBundle(lookup=AppleLookup(), export=AppleExporter())


def _build_tidal() -> ProviderBundle:
    from .tidal.lookup import TidalLookup
    from .tidal.export import TidalExporter

    return ProviderBundle(lookup=TidalLookup(), export=TidalExporter())


_BUILDERS: dict[str, Callable[[], ProviderBundle]] = {
    "beatport": _build_beatport,
    "spotify": _build_spotify,
    "perplexity_label": _build_perplexity_label,
    "perplexity_artist": _build_perplexity_artist,
    "ytmusic": _build_ytmusic,
    "deezer": _build_deezer,
    "apple": _build_apple,
    "tidal": _build_tidal,
}

_BUNDLE_CACHE: dict[str, ProviderBundle] = {}


def reset_cache() -> None:
    _BUNDLE_CACHE.clear()


def _enabled_vendors() -> set[str]:
    raw = os.environ.get("VENDORS_ENABLED", "").strip()
    if not raw:
        return set()
    return {part.strip() for part in raw.split(",") if part.strip()}


def _get_bundle(name: str) -> ProviderBundle | None:
    """Look up the builder for `name`, build (and cache) the bundle on first use.

    Returns None if no builder is registered for `name`.
    """
    if name in _BUNDLE_CACHE:
        return _BUNDLE_CACHE[name]
    builder = _BUILDERS.get(name)
    if builder is None:
        return None
    bundle = builder()
    _BUNDLE_CACHE[name] = bundle
    return bundle


def _require_enabled_bundle(name: str) -> ProviderBundle:
    if name not in _enabled_vendors():
        raise VendorDisabledError(name, reason="disabled")
    bundle = _get_bundle(name)
    if bundle is None:
        raise VendorDisabledError(name, reason="disabled")
    return bundle


def get_ingest(name: str) -> IngestProvider:
    bundle = _require_enabled_bundle(name)
    if bundle.ingest is None:
        raise VendorDisabledError(name, reason="not_implemented")
    return bundle.ingest


def get_lookup(name: str) -> LookupProvider:
    bundle = _require_enabled_bundle(name)
    if bundle.lookup is None:
        raise VendorDisabledError(name, reason="not_implemented")
    return bundle.lookup


def get_enricher(name: str) -> EnrichProvider:
    bundle = _require_enabled_bundle(name)
    if bundle.enrich is None:
        raise VendorDisabledError(name, reason="not_implemented")
    return bundle.enrich


def get_enricher_for_prompt(prompt_slug: str) -> EnrichProvider:
    """Find an enabled enricher that handles the given prompt_slug.

    Only builds bundles for enabled vendors — disabled vendors are skipped
    without instantiation. Iteration order is deterministic (sorted by
    vendor name) so that if two enabled enrichers ever expose the same
    slug, resolution is reproducible across container restarts. Raises
    VendorDisabledError(reason="unrouted") if no enabled vendor exposes
    this slug.
    """
    for name in sorted(_enabled_vendors()):
        bundle = _get_bundle(name)
        if bundle is None or bundle.enrich is None:
            continue
        if bundle.enrich.prompt_slug == prompt_slug:
            return bundle.enrich
    raise VendorDisabledError(prompt_slug, reason="unrouted")


def get_exporter(name: str) -> ExportProvider:
    bundle = _require_enabled_bundle(name)
    if bundle.export is None:
        raise VendorDisabledError(name, reason="not_implemented")
    return bundle.export


def list_enabled_exporters() -> list[ExportProvider]:
    result: list[ExportProvider] = []
    for name in _enabled_vendors():
        bundle = _get_bundle(name)
        if bundle is not None and bundle.export is not None:
            result.append(bundle.export)
    return result

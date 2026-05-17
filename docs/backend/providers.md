# Provider Abstraction Guide

## Overview

All vendor integrations go through a Protocol-based abstraction layer in `src/collector/providers/`. The goal is to isolate vendor-specific code from handlers and allow enabling or disabling vendors at runtime without code changes.

Four Protocol interfaces cover the distinct capabilities a vendor may expose:

| Protocol | Purpose | Known implementors |
|---|---|---|
| `IngestProvider` | Fetch raw releases from the source platform | Beatport |
| `LookupProvider` | Search for tracks by ISRC or metadata | Spotify |
| `EnrichProvider` | AI / external-data enrichment for canonical entities | Perplexity (label, artist stub) |
| `ExportProvider` | Create playlists on the vendor platform | Spotify (stub), YT Music (stub), Deezer (stub), Apple (stub), Tidal (stub) |

All four are defined in `src/collector/providers/base.py` as `runtime_checkable` Protocols. The `ProviderBundle` dataclass (also in `base.py`) groups the four optional roles for a single vendor.

See also: [handlers.md](handlers.md), [ADR-0004](../adr/0004-provider-abstraction.md).

---

## `VENDORS_ENABLED` Gate

**Env var:** `VENDORS_ENABLED` — comma-separated list of vendor names, e.g. `"beatport,spotify,perplexity_label"`.

The registry (`src/collector/providers/registry.py`) reads this on every access call via `_enabled_vendors()`. Vendors whose name is not in the set raise `VendorDisabledError` before the bundle is even constructed.

```
VENDORS_ENABLED="beatport,spotify"
```

### Lazy builders

Each vendor has a `_build_<vendor>()` function registered in `_BUILDERS` (a plain `dict[str, Callable[[], ProviderBundle]]`). The builder is called once on first access; the result is cached in `_BUNDLE_CACHE`. Disabled vendors are never instantiated — their imports never run.

This means:
- A test that only exercises the `beatport` vendor does not need Spotify credentials in the environment.
- Adding a new vendor does not affect existing vendor load times or errors.

After changing `VENDORS_ENABLED` in tests, call `registry.reset_cache()` to clear the bundle cache.

### `VendorDisabledError`

Raised by any registry accessor (`get_ingest`, `get_lookup`, `get_enricher`, `get_exporter`) when:
- The vendor name is not in `VENDORS_ENABLED` (`reason="disabled"`), or
- The vendor is enabled but the requested role (`ingest`/`lookup`/`enrich`/`export`) is `None` in its bundle (`reason="not_implemented"`).

For `get_enricher_for_prompt`, if no enabled vendor's enricher matches `prompt_slug`, the error reason is `"unrouted"`.

### Accessor functions

| Function | Returns | Error if |
|---|---|---|
| `get_ingest(name)` | `IngestProvider` | vendor disabled or `bundle.ingest is None` |
| `get_lookup(name)` | `LookupProvider` | vendor disabled or `bundle.lookup is None` |
| `get_enricher(name)` | `EnrichProvider` | vendor disabled or `bundle.enrich is None` |
| `get_enricher_for_prompt(slug)` | `EnrichProvider` | no enabled enricher exposes this `prompt_slug` |
| `get_exporter(name)` | `ExportProvider` | vendor disabled or `bundle.export is None` |
| `list_enabled_exporters()` | `list[ExportProvider]` | (never raises; returns empty list) |

---

## Wrapped Vendors

These vendors wrap real client implementations. Provider classes are thin adapters — they do not duplicate vendor logic.

### Beatport (`ingest`)

- **Bundle:** `ProviderBundle(ingest=BeatportProvider(...))`
- **Adapter:** `src/collector/providers/beatport.py`
- **Underlying client:** `src/collector/beatport_client.py:BeatportClient`
- **Role:** `IngestProvider` — exposes `fetch_weekly_releases(bp_token, style_id, week_start, week_end, correlation_id)` which pages through the Beatport catalog API and returns `(items, pages_fetched)`.
- **Settings:** `get_api_settings().beatport_api_base_url` (default `https://api.beatport.com/v4/catalog`).

### Spotify (`lookup` + `enrich` + `export` stub)

- **Bundle:** `ProviderBundle(lookup=SpotifyLookup(...), enrich=SpotifyEnricher(...), export=SpotifyExporter())`
- **Adapters:** `src/collector/providers/spotify/{lookup,enrich,export}.py`
- **Underlying client:** `src/collector/spotify_client.py:SpotifyClient`
- **Lookup role:** `LookupProvider` — delegates `lookup_batch_by_isrc` to `SpotifyClient.search_tracks_by_isrc`. OAuth token is cached on the `SpotifyClient` instance for the Lambda lifetime.
- **Enrich role:** `EnrichProvider` — wraps `SpotifyLookup`; current enrichment is track identity (ISRC → Spotify URI), not freeform AI text.
- **Export role:** `ExportProvider` — stub; `create_playlist` raises `VendorDisabledError(reason="not_implemented")` until implemented.
- **Settings:** `get_spotify_worker_settings()` (reads `SPOTIFY_CLIENT_ID`, `SPOTIFY_CLIENT_SECRET` or SSM/SM fallbacks).

### Perplexity (`label enrich`, `artist stub`)

- **Bundles:** `perplexity_label` → `ProviderBundle(enrich=PerplexityLabelEnricher(...))`, `perplexity_artist` → `ProviderBundle(enrich=PerplexityArtistEnricher(...))`
- **Adapters:** `src/collector/providers/perplexity/{label,artist}.py`
- **Role:** `EnrichProvider` — issues a structured prompt to the Perplexity API and returns an `EnrichResult` whose `payload` includes `ai_content`, `confidence`, and supporting evidence.
- **`prompt_slug`:** Used by `get_enricher_for_prompt` to route search messages. The label enricher handles `"label_info"`; the artist enricher is a stub.
- **Settings:** `get_search_worker_settings().perplexity_api_key` (resolved from `PERPLEXITY_API_KEY` / `PERPLEXITY_API_KEY_SSM_PARAMETER` / `PERPLEXITY_API_KEY_SECRET_ARN`).

---

## Stubbed Vendors

The following vendors satisfy the `LookupProvider` and/or `ExportProvider` Protocols structurally but raise `VendorDisabledError(reason="not_implemented")` on every method call. Enabling them via `VENDORS_ENABLED` resolves the bundle without errors; any actual method call then fails at runtime.

| Vendor name | Roles stubbed | Directory |
|---|---|---|
| `ytmusic` | `lookup`, `export` | `src/collector/providers/ytmusic/` |
| `deezer` | `lookup`, `export` | `src/collector/providers/deezer/` |
| `apple` | `lookup`, `export` | `src/collector/providers/apple/` |
| `tidal` | `lookup`, `export` | `src/collector/providers/tidal/` |

---

## Per-Track Lookup Methods

`LookupProvider` gained two per-track methods in addition to the batch `lookup_batch_by_isrc` used by the Spotify worker:

### `lookup_by_isrc(isrc: str) -> VendorTrackRef | None`

Returns a single `VendorTrackRef` on hit, `None` on miss. Used by `vendor_match_handler` for the ISRC fast path.

**Spotify implementation** (`src/collector/providers/spotify/lookup.py:53`): calls `SpotifyClient.search_tracks_by_isrc` with a single-element tracks list and converts the first result to a `VendorTrackRef` via `_track_to_ref`.

**All other vendors:** raise `VendorDisabledError(reason="not_implemented")`.

### `lookup_by_metadata(artist, title, duration_ms, album) -> list[VendorTrackRef]`

Returns up to ~10 candidates ranked by the vendor. Used by `vendor_match_handler` as the fallback after ISRC miss.

**Spotify implementation** (`src/collector/providers/spotify/lookup.py:65`): currently returns `[]` (the batch ISRC path covers real usage; the per-track metadata lookup via `q=` is a separate code path exercised by `vendor_match_worker`).

**All other vendors:** raise `VendorDisabledError(reason="not_implemented")`.

---

## Adding a New Vendor

Three steps, no handler changes required:

1. **Create the adapter.** Add `src/collector/providers/<vendor>/<role>.py` with a class implementing the relevant Protocol(s) from `providers/base.py`. Keep the class a thin adapter over existing client code — do not duplicate vendor logic.

2. **Register a builder.** Add `_build_<vendor>()` to `src/collector/providers/registry.py` and register it in `_BUILDERS`:

   ```python
   def _build_myvendor() -> ProviderBundle:
       from .myvendor.lookup import MyVendorLookup
       return ProviderBundle(lookup=MyVendorLookup())

   _BUILDERS["myvendor"] = _build_myvendor
   ```

3. **Add to `VENDORS_ENABLED`.** Set `VENDORS_ENABLED=...,myvendor` on the relevant Lambda function. The vendor is then live; no redeployment of other Lambdas is needed.

Vendors not in `VENDORS_ENABLED` raise `VendorDisabledError` on first access. Tests can verify disabled behavior without touching environment credentials by leaving the vendor out of `VENDORS_ENABLED`.

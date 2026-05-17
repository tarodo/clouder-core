# ADR-0004: Provider abstraction with `VENDORS_ENABLED` gate
Status: Accepted
Date: 2026-05-17

## Context

CLOUDER integrates with multiple external music services: Beatport for raw data ingestion, Spotify for ISRC lookup and enrichment, Perplexity for AI-based label screening, and stubs for YT Music, Deezer, Apple Music, and Tidal. Initially each Lambda handler imported vendor clients directly, coupling handler logic to vendor-specific SDKs and credential patterns.

This created several problems. First, adding a new vendor required modifying handler code. Second, disabling a vendor (e.g. to cut API costs, or because a key has been revoked) required code changes or environment-specific branching in the handler. Third, testing a handler that used a disabled vendor still required mocking the vendor's client, even when the vendor was irrelevant to the test scenario.

A Protocol-based abstraction layer in `src/collector/providers/` was designed to address all three. Four role Protocols (`IngestProvider`, `LookupProvider`, `EnrichProvider`, `ExportProvider`) define the interface each vendor role must satisfy. Adapters in `providers/<vendor>/` wrap existing clients without duplicating vendor logic. A central registry (`providers/registry.py`) constructs adapters lazily and gates every accessor behind the `VENDORS_ENABLED` environment variable.

The registry's lazy builder pattern (`_BUILDERS: dict[str, Callable[[], ProviderBundle]]`) means a disabled vendor's imports never execute — no import error can propagate from a vendor whose package is absent or misconfigured.

## Decision

Third-party music services are wrapped behind role Protocols (`IngestProvider`, `LookupProvider`, `EnrichProvider`, `ExportProvider`) in `src/collector/providers/`. Adapter instances are constructed lazily via `_BUILDERS` in `providers/registry.py` and only when the vendor name appears in the `VENDORS_ENABLED` env var. Vendors not enabled raise `VendorDisabledError` from registry accessors.

## Consequences

- Adding a new vendor is three steps with no handler changes: create the adapter, register a builder in `_BUILDERS`, add the vendor name to `VENDORS_ENABLED`.
- Disabling a vendor is a single env var change; the handler code path that calls `get_lookup(name)` catches `VendorDisabledError` and skips gracefully.
- Tests that exercise one vendor do not need credentials for other vendors — they simply leave those vendors out of `VENDORS_ENABLED`. After changing `VENDORS_ENABLED` between tests, call `registry.reset_cache()` to clear the bundle cache.
- Provider classes are thin adapters. Existing clients (`BeatportClient`, `SpotifyClient`, `search_label`) live in their original modules and are wrapped — do not duplicate vendor logic inside the adapter.
- The stub vendors (`ytmusic`, `deezer`, `apple`, `tidal`) satisfy the Protocol structurally but raise `VendorDisabledError(reason="not_implemented")` on every method call. Enabling them resolves the bundle without errors; any actual method call then fails at runtime.
- `LookupProvider` per-track methods (`lookup_by_isrc`, `lookup_by_metadata`) were added in a later iteration. Only Spotify implements them; all other vendors raise `not_implemented`. This is a known gap for future vendor work.

**Cross-references:** `../backend/providers.md`.

# Vendor-Sync Readiness — Implementation Roadmap

**Spec:** [docs/superpowers/specs/2026-04-18-vendor-sync-readiness-design.md](../specs/2026-04-18-vendor-sync-readiness-design.md)

**Approach:** Five sequential plans. Each ships independently, has its own tests and (where needed) its own alembic migration. Plans are written one at a time — after each plan lands in main, we revisit the spec and write the next plan with whatever is learned from the previous one.

## Dependency Graph

```
Plan 1 (Foundation)
    │
    ├──► Plan 2 (Ingestion enrichment) ──┐
    │                                     │
    └──► Plan 3 (Provider abstraction) ───┤
                                          ▼
                                      Plan 4 (Vendor match worker)
                                          │
                                          ▼
                                      Plan 5 (Release mirror)
```

Plan 2 and Plan 3 can run in parallel after Plan 1. Plans 4 and 5 must wait for Plan 3.

## The Plans

### Plan 1 — Foundation

**File:** `2026-04-18-vendor-sync-01-foundation.md` ✅ written

**Covers spec §6.4, §8.1, §8.2.**

- Generic search worker: `EntitySearchMessage` replaces `LabelSearchMessage` at the worker boundary; backward-compat alias keeps in-flight SQS messages valid.
- SSM Parameter Store SecureString replaces Secrets Manager for Perplexity / Spotify service creds.
- Aurora IAM auth for migration Lambda; Secrets Manager VPC endpoint deleted (−$7.2/mo).
- No alembic migration in this plan.

**Deliverable:** existing behaviour unchanged, infrastructure costs down, codebase ready for generic enricher dispatch.

### Plan 2 — Ingestion enrichment

**File:** `2026-04-18-vendor-sync-02-ingestion-enrichment.md` ✅ written

**Covers spec §5.2 partial, §6.1, §6.2, §6.3.**

- Alembic migration 09: `clouder_tracks.is_ai_suspected`, `clouder_tracks.release_type`, `clouder_albums.release_type`, `clouder_labels.is_ai_suspected`, `clouder_artists.is_ai_suspected`. (07 = IAM bootstrap, 08 = rds_iam idempotent grant, both landed with Plan 1.)
- `scripts/inspect_raw_sample.py` — pulls one `releases.json.gz` from S3 and prints compilation-marker candidates (Beatport key inventory). Run before coding mapping rules.
- `NormalizedAlbum.release_type` + canonicalize mapping rules (single / ep / album / compilation, with VA heuristic).
- Spotify enrich path extracts `album.album_type`; new `reconcile_release_type` step resolves Beatport × Spotify conflicts.
- `is_ai_suspected` propagation: on `ai_search_results` insert, update flag on canonical row (label today, artist/track readiness).

**Deliverable:** canonical tracks and albums carry `release_type`; labels carry `is_ai_suspected`. Ready for the future user-layer filter UI.

### Plan 3 — Provider abstraction

**File:** `2026-04-18-vendor-sync-03-provider-abstraction.md` ✅ written

**Covers spec §4, §7.4 partial (ExportProvider signature only).**

- `src/collector/providers/base.py` — Protocols (`IngestProvider`, `LookupProvider`, `EnrichProvider`, `ExportProvider`) + `VendorTrackRef` + `ProviderBundle`.
- `src/collector/providers/registry.py` — registry, `get_ingest`, `get_lookup(name)`, `get_enricher(prompt_slug)`, `get_exporter(name)`, `list_enabled_exporters()`.
- Migrate existing clients: `beatport_client.py` → `providers/beatport.py`; `spotify_client.py` → `providers/spotify/lookup.py`; enrich path split to `providers/spotify/enrich.py`; `search/perplexity_client.py` → `providers/perplexity/label.py` (+ stub `providers/perplexity/artist.py`).
- Generic search worker switches from inline dispatch (Plan 1) to `registry.get_enricher(prompt_slug)`.
- Stub vendors (YT Music / Deezer / Apple / Tidal): Protocol-compliant bodies that raise `VendorDisabledError`. Registry entries gated by `VENDORS_ENABLED` env var.
- Contract tests `tests/contract/test_vendor_stubs.py`.
- No alembic migration in this plan.

**Deliverable:** registry dispatches all roles; adding a vendor = one new file + registry line + config toggle.

### Plan 4 — Vendor match worker

**File:** `2026-04-18-vendor-sync-04-vendor-match.md` (to be written after Plans 2 + 3)

**Covers spec §5.1 (vendor_track_map, match_review_queue), §7.1, §8.4 partial.**

- Alembic migration 10: `vendor_track_map` + `match_review_queue` tables.
- Fuzzy scorer: normalized Levenshtein on artist+title, duration tolerance, album bonus, configurable weights.
- `vendor_match_worker` Lambda: SQS-triggered, cache-first, ISRC-first, fuzzy fallback, review-queue routing.
- Error classes: `VendorUnavailableError`, `VendorAuthError`, `VendorQuotaError`, `VendorDisabledError`, `MatchFailedError`, `UserTokenMissingError`.
- `retry_vendor` decorator (analogous to existing `retry_data_api`): full jitter, 3 retries on transient (timeout / 5xx / 429 with `Retry-After`).
- SQS queue + DLQ + CloudWatch alarm.
- Integration test with `FakeVendorProvider`.

**Deliverable:** cache-backed, idempotent vendor matching with review-queue escape hatch. Not yet triggered by anything — ready for Plan 5.

### Plan 5 — Release mirror + KMS + API

**File:** `2026-04-18-vendor-sync-05-release-mirror.md` (to be written after Plan 4)

**Covers spec §5.1 (user_vendor_tokens, release_mirror_runs), §7.2, §7.3, §7.4, §8.3, §8.5 partial.**

- Alembic migration 11: `user_vendor_tokens` + `release_mirror_runs`.
- KMS CMK `alias/clouder-user-tokens` (Terraform).
- `src/collector/crypto.py` — envelope encrypt/decrypt via `kms.generate_data_key` + AES-GCM.
- `scripts/store_user_token.py` — seed tokens for manual testing.
- `release_mirror_worker` Lambda: fetch Spotify playlist, map to clouder tracks, match per-vendor (inline, asyncio, N=10), export via vendors.
- `POST /release_mirror` + `GET /release_mirror/{run_id}` endpoints.
- Refresh-fn plumbing on `ExportProvider` (parameter exists, no-op today).
- SQS queue + DLQ + CloudWatch alarm.
- Integration test: fake Spotify source + fake vendor exporters, end-to-end mirror.
- README + data-model docs update.

**Deliverable:** end-to-end release mirror flow, testable with fake vendors, production-ready architecture. Real vendor bodies are follow-up work outside this roadmap.

## Out of Roadmap

- Real bodies for YT Music / Deezer / Apple / Tidal (each is its own mini-plan later).
- OAuth authorize/callback flow (user-layer).
- `users` table + FK hookup on `user_vendor_tokens.user_id`.
- Spotify as ingestion source.
- Artist-level AI enricher (Perplexity body).
- Read API beyond existing endpoints.

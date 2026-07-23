# Architecture Decision Records

ADRs capture the *why* behind load-bearing architectural choices in CLOUDER. They are short (≤ 2 pages), append-only, and stable: once accepted, an ADR is not edited — a new ADR supersedes it.

## Status flow

`Proposed` → `Accepted` → `Superseded by ADR-NNNN` (or `Deprecated`).

## Numbering

Four-digit, monotonic, never reused. The next free number is `0022`.

## Template

```markdown
# ADR-NNNN: <Short title>
Status: Accepted
Date: YYYY-MM-DD

## Context
What problem, what forces, what alternatives were considered.

## Decision
What we chose.

## Consequences
Trade-offs accepted. What becomes harder. Cross-references to topical docs.
```

## Index

| #    | Title                                                                                   |
|------|-----------------------------------------------------------------------------------------|
| 0001 | [RDS Data API at Lambda runtime (vs psycopg)](0001-data-api-runtime.md)                 |
| 0002 | [Multi-tenant overlay model](0002-multi-tenant-overlay.md)                              |
| 0003 | [Saturday-week as canonical period](0003-saturday-week.md)                              |
| 0004 | [Provider abstraction with `VENDORS_ENABLED` gate](0004-provider-abstraction.md)        |
| 0005 | [RDS IAM auth for migration Lambda](0005-iam-auth-migration.md)                         |
| 0006 | [Spotify metadata fallback with strict / relaxed tiers](0006-spotify-metadata-fallback.md) |
| 0007 | [`release_type` derived from Spotify, propagated to canonical](0007-release-type-propagation.md) |
| 0008 | [`is_ai_suspected` soft propagated flag](0008-ai-suspected-flag.md)                     |
| 0009 | [Frontend stack — React 19 + Mantine 9](0009-frontend-stack.md)                         |
| 0010 | [Tap-to-assign curation UX](0010-tap-to-assign.md)                                      |
| 0011 | [Spotify token bundled with CLOUDER auth refresh](0011-spotify-token-bundling.md)       |
| 0012 | [Optimistic shrink, reducer ADVANCE no-op](0012-optimistic-shrink.md)                   |
| 0013 | [PlaybackProvider in authenticated layout, SDK lazy-loaded](0013-playback-lazy-load.md) |
| 0014 | [Aurora Serverless v2 `min_acu=0`](0014-aurora-min-acu-zero.md)                         |
| 0015 | [Refresh-cookie replay = revoke all sessions](0015-refresh-cookie-replay.md)            |
| 0016 | [Label enrichment subsystem (multi-vendor consensus, async)](0016-label-enrichment.md) |
| 0017 | [Artist enrichment mirrors label enrichment](0017-artist-enrichment.md)                  |
| 0018 | [Triage bucket auditioning + create-time classification](0018-triage-buckets.md)         |
| 0019 | [YouTube Music as a second vendor (match + publish)](0019-youtube-music-vendor.md)       |
| 0020 | [Canonical top-level artist/label routes](0020-canonical-entity-routes.md)               |
| 0021 | [Spotify playlist import as a synchronous mirror playlist](0021-spotify-playlist-mirror-import.md) |

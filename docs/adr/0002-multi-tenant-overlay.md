# ADR-0002: Multi-tenant overlay model
Status: Accepted
Date: 2026-05-17

## Context

CLOUDER serves a small, trusted DJ circle. Every user sees the same underlying music catalogue — the same tracks, artists, labels, and albums sourced from Beatport. What differs between users is their personal curation work: which tracks they triage into which buckets, which categories they maintain, which playlists they export to Spotify.

Three multi-tenancy patterns were considered. A fully shared schema (all data in one schema, one database, row-level access via `user_id` columns) is the simplest to operate and the cheapest. A schema-per-tenant approach offers stronger isolation at the cost of schema management complexity that is disproportionate to the team size and user count. A database-per-tenant approach adds IAM, networking, and backup complexity with no meaningful benefit when users never see each other's data at the application level anyway.

The canonical music catalogue itself (`clouder_*` tables) has no concept of "owner" — it is shared, vendor-neutral, and deduped. Ownership is only meaningful at the curation layer: triage blocks, categories, playlists, and tags are per-user artefacts.

Given the team size, trust model, and desire to keep operational surface minimal, a single Aurora database with per-user overlay tables was chosen. Isolation is enforced at the application layer (repository queries always filter by `user_id` from the JWT context) rather than at the database layer.

## Decision

A single Aurora database hosts a shared canonical music catalogue (`clouder_*` entities) plus per-user overlays for playlists, categories, tags, and curation state. There is no per-tenant database isolation. Ownership is enforced at the column level via `owner_user_id` foreign keys on overlay tables.

## Consequences

- `clouder_labels`, `clouder_styles`, `clouder_artists`, `clouder_albums`, `clouder_tracks`, and `clouder_track_artists` carry no `user_id`. All users share the same canonical rows. Enrichment results (`ai_search_results`, `vendor_track_map`) are also shared.
- `triage_blocks`, `categories`, `playlists`, and `user_tags` each have a `user_id` column with a foreign key to `users`. All queries on these tables must include a `user_id` filter derived from the authenticated request context.
- Row-level security is not used in Aurora. The application repository layer is the enforcement boundary. A bug that omits the `user_id` filter would expose another user's data — this is the main risk of this model.
- Cross-user sharing (e.g. sharing a category with a friend) is out of scope and would require a more complex ACL layer. The current model does not accommodate it without schema changes.
- Adding a new user has zero operational cost: no schema provisioning, no new database, no IAM grants.

**Cross-references:** `../data/data-model.md`.

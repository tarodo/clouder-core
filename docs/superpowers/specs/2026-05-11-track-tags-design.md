# Track Tags — Backend Design

**Date:** 2026-05-11
**Scope:** Backend (Aurora schema + repositories + curation Lambda handlers + OpenAPI). Frontend is out of scope and follows in a separate spec.

## Problem

Once a user finalises a triage block, tracks land in shared "общие категории стиля" (per-user, per-style categories). The user needs to attach free-form labels — **tags** — to those tracks, manage a personal tag vocabulary, and filter the tracks of a category by tag set.

Constraints from product:

- A track can carry multiple tags.
- The user can add or remove tags on a track at any time.
- The user can filter tracks of a category by tags.
- **Only tracks that currently sit in at least one of the user's active categories may carry tags.** Tracks inside a triage block (any bucket — `NEW`/`OLD`/`NOT`/`DISCARD`/`UNCLASSIFIED`/`STAGING`) cannot be tagged.

## Goals / Non-goals

**Goals**

- Per-user tag vocabulary with display name and colour.
- Stable many-to-many between user tags and tracks (user-scoped, not category-scoped).
- Filter `GET /categories/{id}/tracks` by a set of tag ids with AND/OR semantics.
- Tag list on every track row returned by the categories endpoint.
- Cascade-clean track tags when a track leaves the user's last active category.

**Non-goals**

- Shared / public tag vocabularies across users.
- Per-style or per-category tag scoping (a tag is global to the user).
- Tagging tracks that are not in any of the user's categories (e.g. during triage).
- Frontend implementation, UI design, hotkeys.
- Migrating existing data — feature is greenfield.

## Approach

**Vocabulary + junction** with app-level cleanup on category removal.

Two new tables:

1. `user_tags` — the per-user vocabulary entry (name + colour).
2. `track_tags` — many-to-many junction `(user_id, track_id, tag_id)`.

The "track must be in a category" rule is enforced **at write time** by an `EXISTS` check against `category_tracks` / `categories`. The rule is also enforced **on category-side mutations** by an explicit cleanup step inside the same transaction: when a track is removed from its last active category for that user, all of the user's `track_tags` rows for that track are deleted.

Alternative approaches considered:

- **Tag-on-junction** (`category_tracks.tag_ids JSONB`): rejected — product wants tags global to the user, not per-category.
- **DB trigger for cleanup**: rejected — the codebase favours explicit app-level cascades (see `TriageRepository.snapshot_category_into_active_blocks`, `mark_staging_inactive_for_category`). Triggers hide intent and complicate test setup.
- **Tag = freeform text on junction**: rejected — product wants a managed vocabulary with rename/colour.

## Data Model

### `user_tags`

| Column            | Type                       | Notes                                                                 |
| ----------------- | -------------------------- | --------------------------------------------------------------------- |
| `id`              | `varchar(36) PK`           | App-generated UUIDv4, stored as string (project convention).          |
| `user_id`         | `varchar(36) NOT NULL`     | FK `users.id ON DELETE CASCADE`.                                      |
| `name`            | `text NOT NULL`            | Display name (preserves user casing/spacing).                         |
| `normalized_name` | `text NOT NULL`            | `lower(trim(name))`. Used for uniqueness + search.                    |
| `color`           | `text NOT NULL`            | Hex `#RRGGBB` (regex-validated at handler).                           |
| `created_at`      | `timestamptz NOT NULL`     |                                                                       |
| `updated_at`      | `timestamptz NOT NULL`     |                                                                       |

Constraints / indexes:

- `UNIQUE (user_id, normalized_name)` → `uq_user_tags_user_normalized_name`.
- `INDEX (user_id)` → `ix_user_tags_user_id`.

### `track_tags`

| Column       | Type                   | Notes                                                                 |
| ------------ | ---------------------- | --------------------------------------------------------------------- |
| `user_id`    | `varchar(36) NOT NULL` | Denormalised for tenant filter without JOIN. Matches `category_tracks` pattern. |
| `track_id`   | `varchar(36) NOT NULL` | FK `clouder_tracks.id ON DELETE CASCADE`. Project convention (UUID-string).     |
| `tag_id`     | `varchar(36) NOT NULL` | FK `user_tags.id ON DELETE CASCADE`.                                            |
| `created_at` | `timestamptz NOT NULL` |                                                                       |

Constraints / indexes:

- `PRIMARY KEY (user_id, track_id, tag_id)`.
- `INDEX (user_id, tag_id)` → `ix_track_tags_user_tag`. Used by category filter SQL.
- `INDEX (user_id, track_id)` → `ix_track_tags_user_track`. Used by per-track fan-in.

No soft-delete on either table — tags are cheap and reproducible; hard delete keeps queries simple.

### Migration

New Alembic revision file `alembic/versions/<rev>_track_tags.py`, branched off the current head. `db_models.py` gets `UserTag` and `TrackTag` SQLAlchemy classes (for autogen only — runtime uses the Data API, see CLAUDE.md gotcha).

Down migration drops the two tables in reverse order. No backfill.

## API Surface

All routes sit on the existing `beatport-prod-curation` Lambda and use the same authorizer. `user_id` is read from `event.requestContext.authorizer.lambda.user_id` (existing helper `_user_id_or_none`). Error envelope: `{error_code, message, correlation_id}` (existing convention).

### Tag vocabulary

```
POST   /tags                   body: {name, color}         → 201 {id, name, color, created_at, updated_at}
GET    /tags                   ?limit&offset&search        → 200 {items: [...], total}
PATCH  /tags/{tag_id}          body: {name?, color?}       → 200 {id, name, color, ...}
DELETE /tags/{tag_id}                                      → 204
```

Errors:

- `409 tag_name_conflict` — UNIQUE violation on `(user_id, normalized_name)`. Returned for POST and PATCH.
- `404 tag_not_found` — for PATCH / DELETE on a tag the user does not own (404 instead of 403 to avoid leaking existence).
- `400 invalid_color` — colour does not match `^#[0-9A-Fa-f]{6}$`.
- `400 invalid_name` — empty after trim, or length > 64 chars.

`DELETE /tags/{tag_id}` cascades through the `track_tags.tag_id` FK and removes every `(user_id, track_id, tag_id)` row referring to the tag.

### Track tagging

```
GET    /tracks/{track_id}/tags                                → 200 {tags: [{id, name, color}, ...]}
PUT    /tracks/{track_id}/tags        body: {tag_ids: [uuid]} → 200 {tags: [...]}    # replace-all
POST   /tracks/{track_id}/tags        body: {tag_id: uuid}    → 201 {tags: [...]}    # idempotent add
DELETE /tracks/{track_id}/tags/{tag_id}                       → 204
```

Validation (applied on every write):

- The track must satisfy `EXISTS (SELECT 1 FROM category_tracks ct JOIN categories c ON c.id = ct.category_id WHERE c.user_id = :user AND ct.track_id = :track AND c.deleted_at IS NULL)`. If not → `422 track_not_in_any_category`.
- Every `tag_id` in the body must belong to the calling user. If any is foreign → `404 tag_not_found`.
- `PUT` body: `tag_ids` is required, may be empty (`[]` = clear all tags on this track), max 50 entries, no duplicates, all valid UUIDs. Violations → `400 invalid_tag_ids` or `400 too_many_tags`.
- `POST` body: exactly one `tag_id` (single UUID). Missing / malformed → `400 invalid_tag_ids`.
- The category-membership check (422) runs on every write including a `PUT` with empty `tag_ids` — keeps the rule uniform and prevents a backdoor for orphaned writes.

`GET` does not enforce the category-membership rule — it just returns whatever is stored. Stale rows are impossible because writes are gated.

### Filter inside a category

Extend the existing `_handle_list_tracks` for `GET /categories/{id}/tracks`:

```
GET /categories/{id}/tracks
    ?tags=<uuid>,<uuid>
    &match=all|any              # default: all
    &limit&offset&search&sort&order   # existing
```

- `tags`: CSV of UUIDs. Empty / absent → no tag filtering (current behaviour preserved).
- `match=all` (default): AND — every listed tag must be present.
- `match=any`: OR — at least one of the listed tags must be present.
- Tag ids unknown to the user are silently ignored (matches existing `search` leniency) — alternative was a 400, rejected for UX consistency.

Each row of the response gains `tags: [{id, name, color}]`. This field is always present, even with no filter — single-trip UI.

SQL (AND form):

```sql
SELECT t.*, ct.added_at, ...
FROM category_tracks ct
JOIN clouder_tracks t ON t.id = ct.track_id
JOIN categories c     ON c.id = ct.category_id AND c.user_id = :user AND c.deleted_at IS NULL
WHERE ct.category_id = :cat
  AND ct.track_id IN (
      SELECT track_id FROM track_tags
      WHERE user_id = :user AND tag_id = ANY(:tag_ids)
      GROUP BY track_id
      HAVING COUNT(DISTINCT tag_id) = :tag_count
  )
ORDER BY ... LIMIT ... OFFSET ...;
```

For `match=any`, replace the subquery with `SELECT track_id FROM track_tags WHERE user_id = :user AND tag_id = ANY(:tag_ids)` (no GROUP BY).

Tag fan-in for the response is one extra round-trip:

```sql
SELECT tt.track_id, ut.id, ut.name, ut.color
FROM track_tags tt
JOIN user_tags ut ON ut.id = tt.tag_id
WHERE tt.user_id = :user AND tt.track_id = ANY(:track_ids);
```

Result is grouped by `track_id` in Python and stitched into the page.

### OpenAPI

`scripts/generate_openapi.py:ROUTES` is updated with all new endpoints. Postman import depends on this file (see CLAUDE.md gotcha) — regenerate `docs/openapi.yaml` as part of the implementation plan.

## Repository Layer

New file `src/collector/curation/tags_repository.py`.

### Dataclasses

```python
@dataclass(frozen=True)
class TagRow:
    id: str             # UUID string
    name: str
    color: str
    created_at: str     # ISO-8601 from Data API
    updated_at: str

@dataclass(frozen=True)
class TrackTagRow:
    track_id: str
    tag_id: str
    name: str
    color: str
```

### `TagsRepository`

Public methods:

- `create_tag(user_id, name, color, now) -> TagRow` — INSERT; UNIQUE violation surfaced as a typed error mapped by the handler to `409 tag_name_conflict`.
- `list_tags(user_id, limit, offset, search) -> PaginatedResult[TagRow]` — paginated; `search` matches `normalized_name LIKE :q || '%'`.
- `get_tag(user_id, tag_id) -> TagRow | None`.
- `rename_tag(user_id, tag_id, name=None, color=None, now) -> TagRow` — partial UPDATE. Recomputes `normalized_name` when `name` changes. UNIQUE violation → 409.
- `delete_tag(user_id, tag_id) -> bool` — DELETE; FK CASCADE clears all `track_tags` rows.
- `list_tags_for_tracks(user_id, track_ids) -> dict[int, list[TrackTagRow]]` — fan-in helper used by the categories list endpoint.
- `set_track_tags(user_id, track_id, tag_ids, now, transaction_id=None) -> list[TagRow]` — replace-all. `tag_ids` may be empty (clear all). Inside a transaction: (1) verify track-in-category, (2) verify all tag ids belong to the user (skipped when empty), (3) DELETE existing rows for `(user_id, track_id)`, (4) INSERT the new set if any, (5) return the full current set.
- `add_track_tag(user_id, track_id, tag_id, now, transaction_id=None) -> list[TagRow]` — same validations; `INSERT ... ON CONFLICT DO NOTHING`. Returns the full current set.
- `remove_track_tag(user_id, track_id, tag_id) -> bool` — DELETE; returns whether a row was actually deleted.
- `cleanup_orphaned_track_tags(user_id, track_id, transaction_id) -> int` — invoked by `CategoriesRepository`. SQL: `DELETE FROM track_tags WHERE user_id = :u AND track_id = :t AND NOT EXISTS (SELECT 1 FROM category_tracks ct JOIN categories c ON c.id = ct.category_id WHERE ct.track_id = :t AND c.user_id = :u AND c.deleted_at IS NULL)`. Returns affected row count.

Factory: `create_default_tags_repository()` next to `create_default_categories_repository()` — same settings-driven `DataAPIClient` wiring.

### Changes to existing repositories

`CategoriesRepository`:

- `remove_track(user_id, category_id, track_id)` — wrap existing DELETE in a transaction; after the DELETE call `tags_repo.cleanup_orphaned_track_tags(user_id, track_id, transaction_id)`. Pass the `tags_repo` as a method argument (same pattern as `TriageRepository.finalize_block` passing `categories_repository`) to avoid circular DI between modules.
- `soft_delete(user_id, category_id, now, tags_repo, ...)` — already runs a multi-statement flow. Inside the existing transaction: select the affected `track_ids` for the category being deleted, then iterate and call `tags_repo.cleanup_orphaned_track_tags(user_id, track_id, transaction_id)` for each (or run a single batched delete — see Implementation Notes below).
- `list_tracks(...)` — extended signature `list_tracks(user_id, category_id, limit, offset, search, sort, order, tag_ids: list[str] | None = None, tag_match: Literal["all", "any"] = "all")`. Builds the tag subquery from `tag_ids` and appends it to the existing WHERE clause. After the main page query, calls `tags_repo.list_tags_for_tracks(user_id, [row.id for row in page])` and merges `tags` into each row dataclass.

The existing `TrackInCategoryRow` dataclass gains a `tags: list[TrackTagRow]` field.

`TriageRepository`: **no changes**. Triage tracks never carry tags by construction; the rule is enforced at the categories handler boundary.

### Implementation notes

- Batched cleanup option: instead of looping per track on `soft_delete`, a single SQL `DELETE FROM track_tags WHERE user_id = :u AND track_id IN (...) AND NOT EXISTS (...)` is equivalent and fewer round-trips. Plan to use the batched form.
- All cleanup runs inside the same `data_api.transaction()` block as the category mutation. If the cleanup fails, the category mutation rolls back.
- `find_identity`-style read-your-writes is not needed here because the cleanup reads `category_tracks` AFTER the DELETE within the same transaction, and the Data API client honours `transaction_id` (see CLAUDE.md gotcha).

## Authorization & multi-tenancy

Every SQL statement filters by `user_id` in the WHERE clause — the existing soft multi-tenancy pattern (see `categories_repository.py`). Cross-user access returns zero rows → 404 at the handler. No additional ACL.

`user_tags.user_id` is bound to the row; `tag_id` from another user fed into any endpoint resolves to 0 rows and surfaces as `404 tag_not_found`.

## Error contract summary

| Code | `error_code`                | When                                                          |
| ---- | --------------------------- | ------------------------------------------------------------- |
| 400  | `invalid_color`             | Colour fails hex regex.                                       |
| 400  | `invalid_name`              | Empty / overlong tag name.                                    |
| 400  | `invalid_tag_ids`           | Empty array, duplicates, malformed UUID on PUT/POST.          |
| 400  | `too_many_tags`             | `len(tag_ids) > 50` on PUT.                                   |
| 404  | `tag_not_found`             | Tag id unknown to the user.                                   |
| 404  | `track_not_found`           | Track id does not exist (per existing convention).            |
| 404  | `category_not_found`        | Pre-existing — unchanged by this work.                        |
| 409  | `tag_name_conflict`         | Duplicate `normalized_name` for the user.                     |
| 422  | `track_not_in_any_category` | Tagging attempted while track is in zero active categories.   |

## Logging

Structured events emitted from the repository (`structlog`):

- `tag_created`, `tag_renamed`, `tag_deleted` with `tag_id`, `user_id`, redacted `name`.
- `track_tags_set` with `track_id`, `added_count`, `removed_count`.
- `track_tag_added`, `track_tag_removed`.
- `track_tags_orphan_cleanup` with `track_id`, `removed_count`, `cause` (`category_track_removed` | `category_soft_deleted`).

## Testing strategy

### Unit (`tests/unit/`, `RDSDataAPIClient` mocked)

`test_tags_repository.py`:

- `create_tag` happy path.
- `create_tag` duplicate `normalized_name` → typed error.
- `rename_tag` case-insensitive collision detection.
- `delete_tag` triggers FK cascade (verified through following SELECT on `track_tags`).
- `set_track_tags` rejects track that has zero active `category_tracks` for the user (422 path).
- `set_track_tags` rejects foreign `tag_id` (404 path).
- `add_track_tag` idempotent on repeat call (no duplicate row, returned set unchanged).
- `cleanup_orphaned_track_tags` deletes only when no active category remains.
- `cleanup_orphaned_track_tags` is a no-op when at least one active category exists.

`test_categories_repository_tags.py` (extends the existing suite):

- `remove_track` clears tags when the removed category was the user's last category for that track.
- `remove_track` keeps tags when the track is still in another active category.
- `soft_delete` of a category cascades `cleanup_orphaned_track_tags` for every contained track.
- `list_tracks` with `tags=[a,b], match=all` returns only tracks carrying both.
- `list_tracks` with `tags=[a,b], match=any` returns the union.
- `list_tracks` with `tags=[<unknown>]` silently returns no rows (no error).
- `list_tracks` response rows expose `tags` populated by `list_tags_for_tracks`.

### Integration (`tests/integration/`, ephemeral Postgres)

`test_tags_e2e.py`: end-to-end via handler entry points.

1. Create a tag.
2. Create a second tag.
3. Attempt to tag a track not in any category → 422.
4. Add the track to a category via `categories.add_track`.
5. PUT tags on the track → 200, both tags returned.
6. `GET /categories/{id}/tracks?tags=<id1>&match=all` returns the row, with `tags` populated.
7. Remove the track from the category → subsequent `GET /tracks/{id}/tags` returns empty.
8. Re-add the track → tags do **not** resurrect (cleanup is irreversible per product decision).
9. Delete a tag → cascades to remaining `track_tags`.

## Non-functional

- **Transactionality.** All multi-statement mutations (`set_track_tags`, `remove_track + cleanup`, `soft_delete + cleanup`) run inside a single `DataAPIClient.transaction()` block. The pre-execution retry decorator (`retry_data_api_pre_execution` on `commit_transaction`) keeps the partial-commit behaviour safe (see CLAUDE.md gotcha).
- **Performance.** Filter SQL hits `ix_track_tags_user_tag`. Expected `track_tags` table size: thousands per user × users → millions globally — well within index range. Fan-in adds one query per page, bounded by `limit`.
- **Idempotency.** `POST /tracks/{id}/tags` is idempotent via `ON CONFLICT DO NOTHING`. `DELETE /tracks/{id}/tags/{tag_id}` is idempotent (`bool` return; 204 either way).
- **Cleanup decision.** Removing a track from its last active category permanently deletes the user's tag assignments on that track. This is the product-chosen behaviour ("чистим тэги"). Documented here so the implementation does not silently second-guess it.

## Out of scope (for follow-up)

- Frontend implementation: tag chip UI on track rows, multiselect filter, vocabulary management page, colour picker.
- Bulk tag operations (apply tag to N tracks in one request).
- Suggested / auto tags from Spotify / Beatport metadata.
- Tag analytics / counts per tag.
- Per-style or per-category tag scoping.

## Files touched

- `alembic/versions/<rev>_track_tags.py` — new migration.
- `src/collector/db_models.py` — `UserTag`, `TrackTag` for autogen.
- `src/collector/curation/tags_repository.py` — new repository.
- `src/collector/curation/categories_repository.py` — extend `remove_track`, `soft_delete`, `list_tracks`; extend `TrackInCategoryRow`.
- `src/collector/curation_handler.py` — new route handlers + entries in `_ROUTES`.
- `scripts/generate_openapi.py` — `ROUTES` additions; regenerate `docs/openapi.yaml`.
- `tests/unit/test_tags_repository.py` — new.
- `tests/unit/test_categories_repository_tags.py` — new (or extend an existing categories test file).
- `tests/integration/test_tags_e2e.py` — new.

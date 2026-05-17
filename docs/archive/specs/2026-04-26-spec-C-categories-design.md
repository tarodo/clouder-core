# spec-C — Categories (Layer 1)

**Date:** 2026-04-26
**Status:** brainstorm stage
**Author:** @tarodo (via brainstorming session)
**Parent:** [`2026-04-25-old-version-feature-parity-design.md`](./2026-04-25-old-version-feature-parity-design.md) — this spec implements §6 spec-C (C1–C7) and resolves the §7.6 mini-questions tagged "Decide in spec-C".
**Predecessor:** [`2026-04-25-spec-A-user-auth-design.md`](./2026-04-25-spec-A-user-auth-design.md) — spec-A is a hard prerequisite (already merged). This spec depends on its `users` table and Lambda Authorizer context (`user_id`, `is_admin`).
**Successor blockers:** spec-D (Triage) — depends on `categories` existing and on `categories_repository.add_tracks_bulk(...)` for the finalize-promotion path.

## 1. Context and Goal

After spec-A, the backend has authenticated users but no curation surface — every endpoint either reads canonical core or runs admin ingest. The parent spec (§4.4, §7.4) requires a permanent, per-user, per-style track library that lives **only in Aurora** (no Spotify playlists for this layer). Triage (spec-D) then promotes tracks into these categories, and release-playlists (spec-E) source from them.

This spec adds Layer 1. After it ships:

- A logged-in user can create, list, rename, soft-delete, and reorder categories scoped to a `clouder_styles` row.
- A user can add and remove tracks in a category directly (outside any triage session). Adds are idempotent.
- Spec-D obtains the `add_tracks_bulk(...)` repository method it needs for finalize-time promotion, with a stable cross-spec contract.
- Categories surface integrates with the existing JWT Lambda Authorizer; tenancy is enforced at the repository layer (`user_id` always in `WHERE`).

## 2. Scope

**In scope:**

- New tables: `categories`, `category_tracks`.
- New Lambda: `curation_handler.py` — owns spec-C routes; spec-D and spec-E will add their routes here too.
- New package: `collector/curation/` (`categories_repository.py`, `categories_service.py`, `schemas.py`, `__init__.py`).
- 9 HTTP routes (8 category-scoped + 1 reorder).
- Alembic migration `20260427_14_categories.py`.
- Terraform additions: new Lambda function, integration, 9 routes, IAM, JWT-authorizer reuse.
- Unit + integration tests covering tenancy, idempotency, reorder, soft-delete, name uniqueness, and the spec-D contract surface.

**Out of scope:**

- Triage flow (R1–R8) — spec-D.
- Release-playlists (P1–P7) — spec-E.
- Cron / batch hard-purge of soft-deleted rows — deferred until volume warrants it (`FUTURE-C4`).
- Restore endpoint for soft-deleted categories — `FUTURE-C1`, not needed at MVP.
- Atomic move-track-between-categories endpoint — frontend chains DELETE+POST.
- Moving a category between styles (`style_id` is immutable post-create).
- Auto-snapshotting newly created categories into already-active triage blocks — that side-effect lives in spec-D.
- Bulk add tracks via HTTP — `FUTURE-C3`. Bulk method exists at the repository layer for spec-D's internal use only.
- ETag / If-Match optimistic concurrency.
- Frontend code.

## 3. Architectural Decisions

| # | Decision | Rationale |
|---|----------|-----------|
| D1 | Uniqueness of category name scoped per `(user_id, style_id)` via partial UNIQUE on `normalized_name WHERE deleted_at IS NULL`. | Names must collide inside a style; cross-style namesakes are normal. Soft-deleted rows must not block recreate. |
| D2 | Normalize for uniqueness: `lower + trim + collapse-whitespace`. Stored separately as `normalized_name`. | `Tech House` / `tech house` / `  Tech  House  ` are the same to a user. Original casing preserved in `name` for display. |
| D3 | Drop batch-create. One POST = one category. | Old code batched only because Spotify playlist creation was per-category. Aurora INSERTs are trivial; batch adds error-mode complexity (partial vs all-or-nothing) for no value. |
| D4 | Add-track is idempotent via `ON CONFLICT (category_id, track_id) DO NOTHING`; HTTP returns `201 added` or `200 already_present`. First-write-wins on `added_at` and `source_triage_block_id`. | Double-click resilience; triage-promotion + manual-add convergence; no UNIQUE-violation 409 spam in normal UX. |
| D5 | Cross-style permissive: a track from any style (or with NULL `style_id`) can be added to any category. | Mis-classified ingest, NULL styles, and DJ judgement all argue against enforcement. The repo only validates ownership and existence. |
| D6 | Soft-delete only on `categories` (one column `deleted_at`). `category_tracks` is filtered via `JOIN categories WHERE deleted_at IS NULL`. C7 (remove track) hard-deletes the `category_tracks` row. | Minimal schema; restore = clear `deleted_at`; explicit per-track removal needs no audit row. |
| D7 | No cleanup cron in spec-C. Soft-deleted rows accumulate indefinitely. | Volume is tiny (categories per user ≪ 100, `category_tracks` per user ≪ 10⁵). Cleanup is `FUTURE-C4`. |
| D8 | New Lambda `curation_handler.py` (not extending `handler.py`). spec-C/D/E all live in it. | `handler.py` is already 800+ LOC mixing canonical-core read and admin ingest. Curation has different auth shape (100% user-overlay) and benefits from independent deploy/blast-radius. |
| D9 | Per-spec modules under `collector/curation/`: `categories_repository.py`, `categories_service.py`, `schemas.py`. spec-D adds `triage_repository.py` etc. alongside. | Avoids the `repositories.py` 1.2k-LOC monolith pattern; each spec owns its own module. |
| D10 | Shallow nested URL design. Nested on `create` and `list-by-style`; flat (UUID-based) on detail/update/delete and tracks. | Nested URL conveys scope where useful (`POST /styles/{id}/categories`); flat on UUID-only ops avoids redundant `style_id` validation on every detail/update/track endpoint. |
| D11 | `PATCH /categories/{id}` accepts only `{name}`. `style_id` is immutable. Restore is not supported. | Moving a category between styles would invalidate triage staging buckets in spec-D. Restore is `FUTURE-C1`. |
| D12 | User-controlled order: `categories.position INTEGER NOT NULL DEFAULT 0`, scoped per `(user_id, style_id)` among non-deleted rows. New categories appended at `MAX(position) + 1`. | DJs need stable ordering for UI. Integer + full-array reorder is simplest for ≪ 100 categories per scope. |
| D13 | Reorder via `PUT /styles/{style_id}/categories/order` with full id-array. Server validates the array equals the current set of non-deleted categories. Single TX assigns positions `0..N-1`. | Atomic, idempotent, no race between per-row PATCHes. Strict full-list semantics catches stale clients (`order_mismatch` 422). |
| D14 | Sort defaults: list-by-style `position ASC, created_at DESC, id ASC`; cross-style `created_at DESC, id ASC`. No `?sort=` query param. | Position is the user-meaningful order inside a style; cross-style list has no position scope so falls back to recency. Sort param is `FUTURE-C2`. |
| D15 | Tenancy enforced at repository layer: every method takes `user_id` and includes it in `WHERE`. Cross-user access returns 0 rows → 404 (does not leak existence). | Defence-in-depth: handler can never accidentally skip the filter. |
| D16 | `category_tracks.source_triage_block_id` is created **without** an FK in spec-C. spec-D adds the FK (`ON DELETE SET NULL`) when its `triage_blocks` table appears. | Avoids a dangling FK in the spec-C migration; column is nullable and meaningful even without the constraint. |
| D17 | `add_tracks_bulk(user_id, category_id, items, transaction_id)` is a public repository method. Direct-add HTTP path uses the same engine with one item and `source_triage_block_id=None`. | Single source of truth for the insert path; spec-D reuses it inside its finalize transaction (per CLAUDE.md note on `transaction_id` for in-flight reads). |
| D18 | All 9 routes JWT-gated via the existing Lambda Authorizer from spec-A. No admin routes; no public routes. | Categories are user-overlay only. |

## 4. Data Model

### 4.1 `categories`

| Column | Type | Constraints |
|---|---|---|
| id | String(36) | PK (UUID) |
| user_id | String(36) | NOT NULL, FK → `users.id` |
| style_id | String(36) | NOT NULL, FK → `clouder_styles.id` |
| name | Text | NOT NULL |
| normalized_name | Text | NOT NULL |
| position | Integer | NOT NULL, default 0 |
| created_at | DateTime(tz) | NOT NULL |
| updated_at | DateTime(tz) | NOT NULL |
| deleted_at | DateTime(tz) | nullable |

**Indexes:**

- `uq_categories_user_style_normname` UNIQUE `(user_id, style_id, normalized_name)` `WHERE deleted_at IS NULL` — partial unique permits recreating a name after soft-delete.
- `idx_categories_user_style_position` `(user_id, style_id, position)` `WHERE deleted_at IS NULL` — sorted fetch within a style.
- `idx_categories_user_created` `(user_id, created_at DESC)` `WHERE deleted_at IS NULL` — cross-style list.

**Normalization function (Python, in service layer):**

```python
def normalize_category_name(s: str) -> str:
    return " ".join(s.strip().lower().split())
```

### 4.2 `category_tracks`

| Column | Type | Constraints |
|---|---|---|
| category_id | String(36) | PK (composite), FK → `categories.id` |
| track_id | String(36) | PK (composite), FK → `clouder_tracks.id` |
| added_at | DateTime(tz) | NOT NULL |
| source_triage_block_id | String(36) | nullable; FK added by spec-D (`ON DELETE SET NULL`) |

**PK:** `(category_id, track_id)` — UNIQUE makes add idempotent.

**Indexes:**

- `idx_category_tracks_category_added` `(category_id, added_at DESC, track_id)` — pagination of `GET /categories/{id}/tracks`.

### 4.3 Rationale notes

- `position` carries no UNIQUE constraint. Reorder transactionally rewrites positions; uniqueness is enforced by the array-replace contract, not the column.
- Soft-delete on `categories` does not cascade to `category_tracks`. List/detail queries always JOIN `categories ON ... WHERE deleted_at IS NULL`. Restore (if ever added) recovers track membership for free.
- C7 hard-deletes `category_tracks` because it is user-explicit removal, not aggregate lifecycle. `source_triage_block_id` (audit hint) is preserved only as long as the row lives.

## 5. API Surface

All routes JWT-gated. `user_id` is read from `event.requestContext.authorizer.lambda.user_id`; never from body or path. Cross-user access returns `404` (existence not leaked).

Error envelope (existing pattern): `{error_code, message, correlation_id}`. Common codes: `validation_error` (422), `name_conflict` (409), `not_found` family (404), `unauthorized` (401), `order_mismatch` (422).

A `Category` response shape:

```json
{
  "id": "uuid",
  "style_id": "uuid",
  "style_name": "House",
  "name": "Tech House",
  "position": 0,
  "track_count": 0,
  "created_at": "2026-04-26T12:00:00Z",
  "updated_at": "2026-04-26T12:00:00Z"
}
```

`style_name` is fetched via JOIN on `clouder_styles`. `track_count` is computed via `LEFT JOIN category_tracks GROUP BY` in the same query (categories per user are dozens — trivial cost).

### 5.1 `POST /styles/{style_id}/categories` — create

**Body:** `{name: string}`
**Response 201:** `Category` + `correlation_id`.
**Errors:**

- 422 `validation_error` — name empty / whitespace-only / longer than 64 after trim / contains control chars.
- 404 `style_not_found` — `clouder_styles.id` does not exist.
- 409 `name_conflict` — `(user_id, style_id, normalized_name)` already alive.

**Position assignment:** within a TX:

```
SELECT COALESCE(MAX(position), -1) + 1
FROM categories
WHERE user_id = ? AND style_id = ? AND deleted_at IS NULL
```

then INSERT.

### 5.2 `GET /styles/{style_id}/categories` — list by style

**Query:** `limit` (default 50, max 200), `offset` (default 0).
**Response 200:** `{items: [Category], total, limit, offset, correlation_id}`.
**Sort:** `position ASC, created_at DESC, id ASC`.
**Errors:** 404 `style_not_found`.

### 5.3 `GET /categories` — cross-style list

**Query:** `limit`, `offset`.
**Response 200:** same shape; sort `created_at DESC, id ASC`.

### 5.4 `GET /categories/{id}` — detail

**Response 200:** `Category` + `correlation_id`.
**Errors:** 404 `category_not_found` (not exists / soft-deleted / belongs to another user).

### 5.5 `PATCH /categories/{id}` — rename

**Body:** `{name: string}`
**Response 200:** updated `Category`.
**Errors:** 422 `validation_error`, 404 `category_not_found`, 409 `name_conflict`.

`normalized_name` and `updated_at` recomputed; `position` and `style_id` untouched.

### 5.6 `DELETE /categories/{id}` — soft-delete

**Response 204** (empty body).
**Errors:** 404 `category_not_found`.

Sets `deleted_at = NOW()`. `category_tracks` rows are not touched — they become invisible via the `WHERE deleted_at IS NULL` filter applied by every read path. A leftover position hole is acceptable; the user can call reorder to compact if desired.

Repeating DELETE on an already-soft-deleted row returns 404 (the row is invisible to the API).

### 5.7 `PUT /styles/{style_id}/categories/order` — reorder

**Body:** `{category_ids: [uuid, uuid, ...]}`
**Response 200:** `{items: [Category], correlation_id}` — categories in the new order.
**Errors:**

- 404 `style_not_found`.
- 422 `order_mismatch` — array members do not equal the current set of non-deleted categories of this user in this style (extra ids, missing ids, foreign-user ids, soft-deleted ids — all caught here).

In one TX: validate set equality, then `UPDATE categories SET position = idx, updated_at = NOW() WHERE id = ?` for each id in array order.

### 5.8 `GET /categories/{id}/tracks` — list tracks

**Query:** `limit` (default 50, max 200), `offset`, optional `search`. The search term is lowercased + trimmed before matching against `clouder_tracks.normalized_title` via `ILIKE %term%`.
**Response 200:** `{items: [TrackRow + added_at + source_triage_block_id], total, limit, offset, correlation_id}`.
**Sort:** `added_at DESC, track_id ASC`.
**Errors:** 404 `category_not_found`.

`TrackRow` matches the existing `GET /tracks` shape (id, title, mix_name, isrc, bpm, length_ms, publish_date, spotify_id, release_type, is_ai_suspected, artists list, etc.).

### 5.9 `POST /categories/{id}/tracks` — add track

**Body:** `{track_id: uuid}`
**Response 201:** `{result: "added", added_at, source_triage_block_id: null, correlation_id}`.
**Response 200:** `{result: "already_present", added_at: <existing>, source_triage_block_id: <existing>, correlation_id}`.
**Errors:** 422 `validation_error`, 404 `category_not_found`, 404 `track_not_found`.

SQL: `INSERT ... ON CONFLICT (category_id, track_id) DO NOTHING RETURNING ...`. Empty `RETURNING` → already-present; service then `SELECT`s the existing row to populate the response.

`source_triage_block_id` is always `NULL` for direct adds. For triage-driven adds (spec-D), the field is set by `add_tracks_bulk`.

### 5.10 `DELETE /categories/{id}/tracks/{track_id}` — remove track

**Response 204.**
**Errors:** 404 `category_not_found`, 404 `track_not_in_category`.

Hard-deletes the `category_tracks` row.

## 6. Code Layout

### 6.1 Lambda layout

```
src/collector/
├── curation/
│   ├── __init__.py              # shared types: PaginatedResult, error mapping
│   ├── categories_repository.py # spec-C
│   ├── categories_service.py    # name normalization, validation, position assignment, idempotent add
│   └── schemas.py               # Pydantic request/response models for spec-C
├── curation_handler.py          # Lambda entry: routing + 9 handlers
└── ...
```

### 6.2 Repository surface

`CategoriesRepository` (Aurora Data API client, same pattern as existing `repositories.py`):

| Method | Notes |
|---|---|
| `create(user_id, style_id, name, normalized_name) -> CategoryRow` | TX: `MAX(position) + 1`, INSERT. Maps UNIQUE violation to `NameConflictError`. |
| `get(user_id, category_id) -> CategoryRow \| None` | Filters `deleted_at IS NULL`. Returns `None` for cross-user / missing. |
| `list_by_style(user_id, style_id, limit, offset) -> tuple[list[CategoryRow], int]` | Includes `track_count` via JOIN; total via separate count query. |
| `list_all(user_id, limit, offset) -> tuple[list[CategoryRow], int]` | Same shape, no `style_id` filter. |
| `rename(user_id, category_id, name, normalized_name) -> CategoryRow` | UPDATE; maps UNIQUE violation. |
| `soft_delete(user_id, category_id) -> bool` | UPDATE `deleted_at` if NULL; returns whether a row was affected. |
| `reorder(user_id, style_id, ordered_ids) -> list[CategoryRow]` | TX: SELECT current set, validate set equality, UPDATE each. Raises `OrderMismatchError` on mismatch. |
| `list_tracks(user_id, category_id, limit, offset, search) -> tuple[list[TrackRow], int]` | Validates category ownership; JOINs `clouder_tracks` and `clouder_track_artists`; sorts by `added_at DESC`. |
| `add_track(user_id, category_id, track_id, source_triage_block_id=None) -> tuple[Row, bool]` | Wraps `add_tracks_bulk` for the single-track HTTP path. `bool` = True if newly added, False if already-present. |
| `remove_track(user_id, category_id, track_id) -> bool` | Hard DELETE; returns whether a row was deleted. |
| `add_tracks_bulk(user_id, category_id, items, transaction_id=None) -> int` | Public, used by spec-D. Validates category ownership; runs multi-row INSERT ON CONFLICT DO NOTHING. Accepts `transaction_id` so spec-D can call it inside its finalize TX (per CLAUDE.md note on `find_identity` requiring `transaction_id` for in-flight reads). Returns the count of rows actually inserted. |

### 6.3 Service surface (`categories_service.py`)

- `normalize_category_name(s)` — see 4.1.
- `validate_category_name(s)` — empty/whitespace/length/control-chars; raises `ValidationError`.
- `assign_position(repo, user_id, style_id, *, transaction)` — wrapped MAX+1.
- `validate_reorder_set(actual_ids, requested_ids)` — set equality; raises `OrderMismatchError` on mismatch.

The service layer is thin; bulk of complexity lives in repository SQL.

### 6.4 Handler routing

`curation_handler.lambda_handler` dispatches on `(method, route)`. Route constants pulled from `event.routeKey` (HTTP API v2 format). Each route handler:

1. Reads `user_id` from `requestContext.authorizer.lambda.user_id`. Missing → 401 `unauthorized`.
2. Parses path / body via `schemas.py` (Pydantic). Validation errors → 422.
3. Calls the relevant repository / service method.
4. Maps domain exceptions to HTTP error envelope with `correlation_id`.
5. Emits `structlog` event.

### 6.5 Tenancy guard

The `user_id` parameter is mandatory in every repository method. Handler never queries the DB directly. The service never bypasses the repository. Cross-user access produces `None` from `get(...)` and 0 affected rows from writes — handler then maps to 404.

### 6.6 Transactions and retry

Multi-statement operations (`create`, `reorder`, `add_tracks_bulk`) use `repository.transaction()` context. `data_api_retry` decorators are applied in line with existing patterns: `retry_data_api` on read/write statements, `retry_data_api_pre_execution` on `commit_transaction` / `rollback_transaction`.

### 6.7 Logging

Structlog events emitted by handlers (each carries `correlation_id`, `user_id`):

- `category_created`, `category_renamed`, `category_soft_deleted`, `category_order_updated`
- `category_track_added` (with `result: added | already_present`), `category_track_removed`
- `category_list_completed`, `category_tracks_list_completed`

## 7. Migration & Infrastructure

### 7.1 Alembic migration `20260427_14_categories.py`

- CREATE TABLE `categories` (4.1) with all indexes.
- CREATE TABLE `category_tracks` (4.2) — `source_triage_block_id` column **without** an FK constraint (D16). spec-D's migration will add the FK.
- GRANT on both tables to `clouder_app` role (matches existing migration pattern).
- Symmetric downgrade.

CI `alembic-check` (ephemeral postgres) validates the migration.

### 7.2 Terraform additions (`infra/`)

- `aws_lambda_function.curation` — entry `collector.curation_handler.lambda_handler`; same code zip (`dist/collector.zip`) as other Lambdas; env vars `AURORA_CLUSTER_ARN`, `AURORA_SECRET_ARN`, `AURORA_DATABASE`, `LOG_LEVEL`.
- `aws_apigatewayv2_integration.curation` — Lambda proxy.
- 9 × `aws_apigatewayv2_route` — see §5; all attached to the existing JWT authorizer from spec-A.
- `aws_lambda_permission.curation_invoke` — apigw → lambda.
- IAM: `rds-data:ExecuteStatement`, `secretsmanager:GetSecretValue` on the master cluster secret, CloudWatch Logs basic. No KMS, no SQS.

### 7.3 Packaging

`scripts/package_lambda.sh` already copies all of `src/collector/` into the zip — new files are picked up automatically. No script change.

### 7.4 CI / deploy

`.github/workflows/pr.yml`: unchanged. `alembic-check` runs the new migration; `tests` runs new pytest files; `terraform` plan shows new resources.

`.github/workflows/deploy.yml`: unchanged. Package → terraform apply → invoke migration Lambda runs the new migration in prod.

### 7.5 Env vars

No new env vars. `curation` Lambda uses the same set as other Lambdas. `VENDORS_ENABLED` is not consulted from this Lambda.

## 8. Testing

### 8.1 Unit

`tests/unit/test_categories_service.py`:

- `normalize_category_name` — case folding, trim, whitespace collapse, Unicode, emoji, lone-whitespace input.
- `validate_category_name` — empty, whitespace-only, > 64 chars, control characters → `ValidationError`.
- Position math: empty style yields 0; `MAX + 1` semantics.
- `validate_reorder_set` — extra / missing / foreign / soft-deleted ids each yield `OrderMismatchError`.

`tests/unit/test_categories_repository.py`:

- SQL shape per method (mock `DataAPIClient`, assert SQL string + parameter map).
- Tenancy: every method places `user_id` in WHERE.
- `add_track` round-trip: `RETURNING` empty → service follows up with SELECT and reports `already_present`.
- `add_tracks_bulk` accepts and forwards `transaction_id`.

`tests/unit/test_curation_schemas.py`:

- Pydantic round-trip for `CreateCategoryIn`, `RenameCategoryIn`, `ReorderCategoriesIn`, `AddTrackIn`.

### 8.2 Integration

`tests/integration/test_curation_handler.py` (ephemeral postgres + Lambda invoke, matching `tests/integration/test_handler.py` pattern):

1. **Happy path:** create → list-by-style → detail → rename → soft-delete; verify visibility and shape.
2. **Position lifecycle:** create three categories; verify positions 0/1/2; reorder to `[2,0,1]`; verify list order.
3. **Tenancy isolation:** user A creates category; user B sees 404 on detail / list-by-style does not include it / rename and delete from B return 404.
4. **Idempotent add + remove:** POST tracks twice → second call yields `200 already_present` with the same `added_at`. DELETE → 204. DELETE again → 404 `track_not_in_category`.
5. **Promotion contract (smoke):** call `categories_repository.add_tracks_bulk(...)` directly with placeholder `source_triage_block_id` UUIDs. Verify rows are inserted and `source_triage_block_id` round-trips. (Even without the FK — spec-C migration intentionally omits it.)
6. **Name conflict + recreate after soft-delete:** create `Tech` → POST again → 409. Soft-delete → POST `Tech` → 201. Verify the second category has `track_count=0` and a fresh UUID.
7. **Cross-style namesakes:** category `Deep` in style A and category `Deep` in style B coexist.
8. **Auth:** missing JWT → 401 (authorizer rejects); JWT for user B on user A's category → 404.
9. **Reorder validation:** array with extra / missing / foreign / soft-deleted ids each yields 422 `order_mismatch`.
10. **Tracks pagination:** seed 120 tracks; limit/offset/total work; `search` narrows by `normalized_title`.
11. **track_count rollup:** add N tracks; list-by-style and detail both report `track_count = N`. Soft-delete a track (via remove) → count decrements.

### 8.3 No load tests

Sizes are tiny by construction (categories per user ≪ 100, tracks per category ≪ 10⁴). Aurora Data API serves all queries in single-digit ms. If spec-D promotion produces large batches (5k+ tracks), benchmarks belong there.

### 8.4 Coverage

No numeric gate. Every repository / service method has at least one unit test; all 9 routes have at least one happy-path and one error-path integration test.

## 9. Open Items, Edge Cases, Future Flags

### 9.1 Edge cases worth noting in code comments

- **Soft-delete + recreate.** The partial UNIQUE `WHERE deleted_at IS NULL` allows a name to be reclaimed. The old soft-deleted row stays for history; it does not contribute to `track_count` of the new row.
- **Position holes after soft-delete.** Positions `0,1,2` minus the middle one yields `0,2`. UI can ignore the gap (sorting still works) or call reorder to compact.
- **Optimistic concurrency.** Two clients PATCH the same category — last-write-wins. Acceptable: a single user is unlikely to race themselves; ETags are unjustified ceremony.
- **Restore semantics.** Not in scope. A future restore endpoint must reassign `position = MAX + 1` to avoid colliding with existing positions, and re-validate name uniqueness against the current alive set.
- **`source_triage_block_id` orphaning.** Once spec-D adds the FK with `ON DELETE SET NULL`, deleting a `triage_blocks` row will null out the audit hint on `category_tracks` — by design.

### 9.2 Future flags

- **`FUTURE-C1`** — restore from soft-delete. `POST /categories/{id}/restore`. Requires position-reassignment and name-conflict re-check.
- **`FUTURE-C2`** — `?sort=` parameter on list endpoints. Add when frontend asks.
- **`FUTURE-C3`** — bulk add via HTTP. `POST /categories/{id}/tracks/bulk`. Internal `add_tracks_bulk` already exists for spec-D; expose only when frontend has multi-select UX.
- **`FUTURE-C4`** — hard-purge cron for soft-deleted categories. EventBridge → Lambda; retention window TBD when row volume warrants.
- **`FUTURE-C5`** — extra metadata on category (description, color, cover image). Currently `name` only.

### 9.3 Cross-spec dependencies

- **spec-D consumes** `categories_repository.add_tracks_bulk(user_id, category_id, items, transaction_id)`. Contract is fixed: `items: list[tuple[track_id: str, source_triage_block_id: str | None]]`. Method must run inside the caller's transaction when `transaction_id` is provided.
- **spec-D adds** the FK `category_tracks.source_triage_block_id → triage_blocks.id ON DELETE SET NULL`.
- **spec-D handles** auto-snapshotting of late-added categories into active triage blocks — spec-C does not emit any event or hook for this; spec-D simply queries the current category list when it needs to.

## 10. Acceptance Criteria

- All 9 routes return the documented status codes and response shapes (§5).
- Migration `20260427_14_categories.py` applies on the CI ephemeral postgres and on prod Aurora.
- Integration tests #1–#11 (§8.2) all green.
- Tenancy: integration test #3 confirms cross-user 404.
- Idempotency: integration test #4 confirms double-add behaviour.
- Reorder atomicity: integration test #2 confirms position update.
- spec-D contract: integration test #5 confirms `add_tracks_bulk` shape.

## 11. References

- Parent: [`2026-04-25-old-version-feature-parity-design.md`](./2026-04-25-old-version-feature-parity-design.md)
- spec-A (predecessor): [`2026-04-25-spec-A-user-auth-design.md`](./2026-04-25-spec-A-user-auth-design.md)
- Vendor-sync readiness (sibling): [`2026-04-18-vendor-sync-readiness-design.md`](./2026-04-18-vendor-sync-readiness-design.md)
- Data model: `docs/data-model.md`
- Project gotchas: root `CLAUDE.md`
- Tenancy memory: `project_clouder_tenancy.md`

# Track audio analysis API — implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:executing-plans (inline). Steps use checkbox (`- [ ]`) syntax.

**Goal:** clouder-core side of the external audio analyzer. It covers:
- the `/v1/analysis/claim` and `/v1/analysis/results` routes behind a service-token authorizer;
- the `track_analyses` table;
- the admin status card and the requeue route;
- `ai_detected` in the track lists, shown as an "AI" badge in rows, the Curate card and the players.

**Architecture:**
- **Repository.** A new `AnalysisMixin` on `ClouderRepository`, using the Data API only.
- **Routes.** New routes in `api/routes_analysis.py`, dispatched by `handler.py`.
- **Authorizer.** The existing `auth_authorizer` Lambda gains a service branch, selected by `routeKey`. A second API Gateway authorizer resource, with its own verdict cache, guards only the service routes.
- **Track lists.** They read the badge through an `EXISTS` on a partial index.

**Tech stack:** Python 3.12 / pydantic / Data API, Alembic, Terraform, React 19 + Mantine + TanStack Query + MSW.

**Spec:** `docs/superpowers/specs/2026-10-15-track-analysis-api-design.md`

## Global constraints

- **Routes and payloads.** The service routes are `POST /v1/analysis/claim` and `POST /v1/analysis/results`; the admin routes are `GET /admin/analysis/status` and `POST /admin/analysis/requeue`. Body shapes and limits are exactly the spec's.
- **Errors.** They use the existing envelope `{error_code, message, correlation_id, …}` (`AppError`). The spec's `{"error": …}` example is loose, and the envelope wins: the worker only reads status codes.
- **Service token storage.**
  - The hash lives in the SSM parameter `/clouder/auth/analysis_service_token_sha256`: lowercase hex SHA-256 of the full `svc_…` token.
  - Terraform does not create the parameter. ADR-0028 keeps secrets out of state, and the pull-request role is already denied `/clouder/auth/*`.
  - A missing parameter means every service call gets 401.
  - The authorizer caches the hash for `JWT_KEY_TTL_SECONDS`, and caches a miss too, so a missing parameter does not hammer SSM.
- **Never log the token or its hash.**
- **Lease length:** 30 minutes. **Status values:** `leased | ok | failed | unusable_source`.
- **Candidate tracks:** those with a `vendor_track_map` row whose `vendor = 'ytmusic'`. The `video_id` is that row's `vendor_track_id`.
- **Process.** Commits go through `caveman:caveman-commit` and use Conventional Commits. README counts, the OpenAPI spec and `schema.d.ts` are regenerated and committed.

## Review focus

1. **Service token on a user route.** It must be denied by the JWT authorizer, and a user JWT on an analysis route by the analysis authorizer. Each authorizer resource caches its own verdicts, and the Lambda branches on `routeKey`. (Task 5 tests both directions.)
2. **Concurrent claims.** They never lease the same `(track, analyzer)` twice. The `ON CONFLICT … WHERE leased_until < now()` guard plus `RETURNING`. (Task 2 has a pg test with a live lease.)
3. **Result for a re-leased pair.** It must be rejected (`lease_lost`) without touching the new lease. (Task 2.)
4. **`ai_detect` ok result without `ai_detected` or `score`, or a NaN or out-of-range score.** It is rejected with 400 and never stored. (Task 3.)
5. **Requeue.** It must never delete live leases, and must not delete `failed` without `include_failed`. (Task 2.)

---

### Task 1: Migration 38 and models

**Files:**
- create `alembic/versions/20261015_38_track_analyses.py`;
- modify `src/collector/db_models.py`.

- [ ] **Migration** (`down_revision` is migration 37's revision id). It creates `track_analyses` and `analysis_service_state` exactly as in the spec. The partial index is `ix_track_analyses_ai_detected`. Add a second index for status counts, `ix_track_analyses_analyzer_status (analyzer, status)`. `downgrade` drops both tables.
- [ ] **Models.** Add `TrackAnalysis` and `AnalysisServiceState` to `db_models.py`, mirroring the migration (the alembic-check CI compares them).
- [ ] **Check.** Run it on a throwaway postgres:16 (port 55440): `alembic upgrade head`, then `alembic downgrade -1`, then `upgrade head`. Run `alembic check` if the repo uses it (see the CI alembic-check job).
- [ ] Commit: `feat(db): add track_analyses table`.

### Task 2: `AnalysisMixin` (repository)

**Files:**
- create `src/collector/repositories/analysis.py`;
- modify `repositories/__init__.py`;
- modify `tests/unit/test_repositories_layout.py` (the API list and AGGREGATES);
- create `tests/db/test_analysis_pg.py`.

**Interfaces.** Produces:

```python
class AnalysisMixin(RepositoryBase):
    def claim_analysis(self, *, limit: int, analyzers: list[str], lease_id: str,
                       now: datetime, lease_seconds: int = 1800) -> list[dict]
        # -> [{"track_id", "video_id", "length_ms", "analyzers": [..]}] newest first
    def record_analysis_results(self, *, lease_id: str, items: list[dict], now: datetime
                                ) -> list[dict]   # rejected: [{"track_id","analyzer","reason":"lease_lost"}]
    def analysis_status(self, *, now: datetime) -> dict
    def requeue_analysis(self, *, analyzer: str, scope: str, days: int | None,
                         include_failed: bool, now: datetime) -> int
```

**Claim SQL** (one statement):

```sql
WITH wanted AS (SELECT unnest(CAST(:analyzers AS text[])) AS analyzer),
picked AS MATERIALIZED (
    SELECT t.id, t.length_ms, t.created_at, v.vendor_track_id AS video_id
    FROM vendor_track_map v JOIN clouder_tracks t ON t.id = v.clouder_track_id
    WHERE v.vendor = 'ytmusic'
      AND EXISTS (SELECT 1 FROM wanted w WHERE NOT EXISTS (
            SELECT 1 FROM track_analyses a
            WHERE a.track_id = t.id AND a.analyzer = w.analyzer
              AND NOT (a.status = 'leased' AND a.leased_until < :now)))
    ORDER BY t.created_at DESC, t.id
    LIMIT :limit
),
leased AS (
    INSERT INTO track_analyses (track_id, analyzer, status, lease_id, leased_until, created_at, updated_at)
    SELECT p.id, w.analyzer, 'leased', CAST(:lease_id AS uuid), :leased_until, :now, :now
    FROM picked p CROSS JOIN wanted w
    WHERE NOT EXISTS (SELECT 1 FROM track_analyses a WHERE a.track_id = p.id AND a.analyzer = w.analyzer
                      AND NOT (a.status = 'leased' AND a.leased_until < :now))
    ON CONFLICT (track_id, analyzer) DO UPDATE
        SET lease_id = EXCLUDED.lease_id, leased_until = EXCLUDED.leased_until, updated_at = EXCLUDED.updated_at
        WHERE track_analyses.status = 'leased' AND track_analyses.leased_until < :now
    RETURNING track_id, analyzer
)
SELECT p.id AS track_id, p.video_id, p.length_ms, array_agg(l.analyzer ORDER BY l.analyzer) AS analyzers
FROM leased l JOIN picked p ON p.id = l.track_id
GROUP BY p.id, p.video_id, p.length_ms, p.created_at
ORDER BY p.created_at DESC, p.id
```

`text[]` comes back from the Data API as a string such as `{ai_detect,embed}`. Parse it the way the repo already parses `text[]` columns (grep `_parse_pg_array` / `primary_styles`), or `string_agg` it with a comma and split. Also upsert `analysis_service_state ('analyzer')` with `last_claim_at = :now` and `claim_analyzers`. That is a second statement, which is fine: the heartbeat is best-effort.

**Results.** One `UPDATE … WHERE track_id = :t AND analyzer = :a AND status = 'leased' AND lease_id = CAST(:lease AS uuid) RETURNING 1` per item. The Data API has no executemany-with-returning, and a batch is at most 100 items. A miss means `lease_lost`. `result` is passed as jsonb, the same way vendor_match passes payloads. When at least one item is accepted, upsert `last_result_at`.

**Status.** Read the `analysis_service_state` row. Read `analyzer, status, count(*)` grouped, plus the `ai_detected` count for `ai_detect` ok rows. For each known analyzer, `due` is the number of ytmusic tracks with no non-expired row for that analyzer. The known analyzers are `claim_analyzers` plus the distinct analyzers in the table.

**Requeue.**
- `DELETE FROM track_analyses WHERE analyzer = :a AND status IN ('ok','unusable_source'[, 'failed']) AND <scope>`.
- Scopes:
  - `all` — no extra condition;
  - `categories` — `track_id IN (SELECT ct.track_id FROM category_tracks ct JOIN categories c ON c.id = ct.category_id WHERE c.deleted_at IS NULL)`;
  - `recent` — `track_id IN (SELECT id FROM clouder_tracks WHERE created_at >= :now - make_interval(days => :days))`.
- Return the deleted count (`RETURNING 1`, then `len`).

- [ ] **pg tests** (real Postgres; seed like `test_youtube_search_pg.py`: style, tracks, `vendor_track_map` rows):
  - a claim leases only ytmusic tracks, newest first, and honours `limit`;
  - the returned rows carry `video_id` and `length_ms`;
  - **(RF 2)** a second claim with a different lease while the first is live returns nothing; after `now + 31 min` it returns the track again;
  - partial analyzers: an `ai_detect` ok row exists, so a claim for `["ai_detect","embed"]` returns the track with `["embed"]` only;
  - a `failed` row is never re-claimed;
  - results: the leased row is accepted and its fields stored; **(RF 3)** after a re-lease, the old `lease_id` is rejected with `lease_lost` and the new lease stays intact;
  - status counts, `due`, and `last_claim_at` / `last_result_at`;
  - **(RF 5)** requeue: `all` deletes ok and unusable but keeps `failed` and live leases; `include_failed` also deletes `failed`; `categories` and `recent` scopes.
- [ ] Watch them fail, implement, watch them pass. Add the 4 methods to the layout test's API list, plus `collector.repositories.analysis` to AGGREGATES.
- [ ] Commit: `feat(analysis): add analysis repository`.

### Task 3: Request schemas

**Files:**
- modify `src/collector/schemas.py`;
- create `tests/unit/test_analysis_schemas.py`.

**Interfaces.** Produces pydantic models, with `extra="forbid"`:

```python
ANALYZER_NAME = r"^[a-z][a-z0-9_]{1,31}$"
class AnalysisClaimRequest(BaseModel):  limit: int = 20 (1..50); analyzers: list[Annotated[str, pattern]] (1..8, unique)
class AnalysisResultItem(BaseModel):
    track_id: str (1..36); analyzer: name; version: str (1..64, printable)
    status: Literal["ok","failed","unusable_source"]
    result: dict | None; error: str | None (<=500); audio_sha256: str | None (^[0-9a-f]{64}$); video_id: str | None (<=32)
    # model_validator: ok -> result required, error may be null; non-ok -> error required, result must be null
    # result JSON (json.dumps(allow_nan=False)) <= 32768 bytes
    # analyzer == "ai_detect" and ok -> result["ai_detected"] is bool, result["score"] finite number in [0,1]
class AnalysisResultsRequest(BaseModel):  lease_id: UUID-string; results: list[AnalysisResultItem] (1..100)
class AnalysisRequeueRequest(BaseModel): analyzer: name; scope: Literal["all","categories","recent"]
    days: int | None (1..365, required iff scope == "recent"); include_failed: bool = False
```

- [ ] **Tests:**
  - the boundaries of every field;
  - duplicate analyzers are rejected;
  - an `ok` without `result` is rejected;
  - a `failed` without `error` is rejected;
  - **(RF 4)** for `ai_detect` ok, each of these is rejected: missing `ai_detected`; a non-bool `ai_detected`; a `score` of 1.5; a NaN `score` (the JSON body cannot carry NaN, but check the model with `float('nan')`);
  - a result over 32 KB is rejected;
  - `recent` without `days` is rejected.
- [ ] Fail, implement, pass. Commit: `feat(analysis): add request schemas`.

### Task 4: Routes

**Files:**
- create `src/collector/api/routes_analysis.py`;
- modify `src/collector/handler.py` (imports, `_ROUTE_TABLE`; the two admin routes go into `_ADMIN_ROUTES`);
- modify `src/collector/api/http.py` (add `_require_service`);
- create `tests/integration/test_analysis_endpoints.py`.

**Interfaces.**
- `_require_service(event)` raises `AppError(status_code=401, error_code="service_required", …)` unless `requestContext.authorizer.lambda.service == "analyzer"`. Add `ServiceRequiredError` to `errors.py`.
- `_handle_analysis_claim`:
  1. `_require_service`, then parse with `AnalysisClaimRequest` (a pydantic error becomes `ValidationError(validation_error_message(e))`);
  2. `lease_id = uuid4()`, `now = deps.utc_now()`, then `repo.claim_analysis`;
  3. return 200 `{lease_id, lease_expires_at, tracks}`.
- `_handle_analysis_results`: `_require_service`, parse, `rejected = repo.record_analysis_results(...)`, return 200 `{accepted: n - len(rejected), rejected}`.
- `_handle_analysis_status` (admin): return 200 with `repo.analysis_status(now)`.
- `_handle_analysis_requeue` (admin): parse, then return 200 `{requeued: n}`.
- A missing DB returns 503 `db_not_configured`, like `routes_youtube`.

- [ ] **Integration tests** through `handler.lambda_handler`, with an authorizer context dict and the repo factory monkeypatched (see `tests/integration/test_youtube_search_status_endpoint.py`):
  - service context with claim gives 200 and the shape;
  - a user context (`user_id`, no `service`) on claim gives 401 `service_required`;
  - a bad body gives 400;
  - results gives the accepted and rejected counts;
  - admin status and requeue need `is_admin` (403 otherwise).
- [ ] Fail, implement, pass. Commit: `feat(analysis): add analysis routes`.

### Task 5: Authorizer service branch

**Files:**
- modify `src/collector/auth_authorizer.py`;
- modify `src/collector/auth/auth_settings.py` (add `resolve_analysis_token_sha256() -> str | None`);
- create `tests/unit/test_auth_authorizer_service.py`.

**Behaviour:**
- `route_key = event.get("routeKey") or requestContext.routeKey`.
- If `route_key.split(" ", 1)[-1].startswith("/v1/analysis/")`:
  - the token must start with `svc_`;
  - `expected = resolve_analysis_token_sha256()`;
  - deny if `expected` is None, or if `hmac.compare_digest(sha256(token).hexdigest(), expected)` is false;
  - on success return `{"isAuthorized": True, "context": {"service": "analyzer"}}`;
  - a JWT on these routes is denied.
- Otherwise the path is unchanged, and a `svc_` token fails JWT verification.
- `resolve_analysis_token_sha256`:
  - reads env `ANALYSIS_TOKEN_SHA256_SSM_PARAMETER`;
  - TTL-caches the value with `JWT_KEY_TTL_SECONDS`;
  - on `ParameterNotFound` (or any error) caches `None` for the TTL and logs `analysis_token_unavailable` with `error_type` only;
  - strips the value and lowercases it.

- [ ] **Tests:**
  - a good token on `POST /v1/analysis/claim` is allowed with context `{"service":"analyzer"}`;
  - a wrong token is denied;
  - **(RF 1)** a valid user JWT on an analysis route is denied;
  - **(RF 1)** a `svc_` token on `GET /me` is denied;
  - a missing parameter denies, and SSM is fetched once within the TTL;
  - `capsys` / a log capture holds neither the token nor the hash.
- [ ] Fail, implement, pass. Commit: `feat(auth): add analysis service token authorizer`.

### Task 6: Infra

**Files:**
- create `infra/analysis.tf`;
- modify `infra/auth.tf` (authorizer env and IAM statement);
- modify `infra/variables.tf`;
- create `tests/unit/test_analysis_infra.py`.

- [ ] **Variable.** `analysis_token_sha256_ssm_parameter`, default `/clouder/auth/analysis_service_token_sha256`.
- [ ] **`auth.tf`.** Add the env `ANALYSIS_TOKEN_SHA256_SSM_PARAMETER` to the authorizer Lambda. Add to the authorizer policy a statement `ReadAnalysisTokenHash` (`ssm:GetParameter`) on that one parameter ARN.
- [ ] **`analysis.tf`.**
  - `aws_apigatewayv2_authorizer.analysis_service`: same Lambda alias, REQUEST, `enable_simple_responses = true`, identity source `$request.header.Authorization`, TTL `var.auth_authorizer_cache_ttl_seconds`, name `${local.name_prefix}-analysis-authorizer`, `depends_on` the same as `jwt`.
  - Routes `POST /v1/analysis/claim` and `POST /v1/analysis/results` → `collector_lambda` integration, CUSTOM, `authorizer_id = …analysis_service.id`.
  - Routes `GET /admin/analysis/status` and `POST /admin/analysis/requeue` on the `jwt` authorizer.
- [ ] **Tests:**
  - the two service routes use `analysis_service`;
  - no route other than `/v1/analysis/*` uses `analysis_service`;
  - the admin routes use `jwt`;
  - the authorizer env and IAM statement exist;
  - the parameter is not a Terraform resource.
- [ ] Run `terraform fmt` and `terraform validate` (with init `-backend=false`).
- [ ] Commit: `feat(infra): add analysis routes and authorizer`.

### Task 7: OpenAPI

**Files:**
- modify `scripts/generate_openapi.py`;
- regenerate `docs/api/openapi.yaml` and `frontend/src/api/schema.d.ts`.

- [ ] **Generator changes.**
  - Add `SERVICE = "service"` auth, a `ServiceToken` security scheme (`http bearer`, `bearerFormat: "svc token"`) and a `service` tag.
  - Make `_security_for(SERVICE)` return `[{"ServiceToken": []}]`.
  - Add the pydantic models (`AnalysisClaimRequest`, `AnalysisResultsRequest`, `AnalysisRequeueRequest`) to `_collect_pydantic_schemas`.
  - Add dict schemas `AnalysisClaimResponse`, `AnalysisResultsResponse`, `AnalysisStatus` and `AnalysisRequeueResponse`.
  - Add 4 route entries, each with `requestBody` `$ref`s and 400/401 errors.
- [ ] Regenerate, run the OpenAPI tests, then `cd frontend && pnpm api:types`.
- [ ] Commit: `docs(api): add analysis routes to OpenAPI`.

### Task 8: `ai_detected` in the track lists

**Files:**
- `curation/categories_repository.py`, `triage_repository.py`, `routes_triage.py`;
- `playlists_repository.py`, `routes_playlists.py`;
- OpenAPI track schemas (3 places);
- their unit tests;
- `tests/db/test_analysis_pg.py`.

- [ ] **Each SELECT** gets:

  ```sql
  EXISTS (SELECT 1 FROM track_analyses ta WHERE ta.track_id = t.id AND ta.analyzer = 'ai_detect'
          AND ta.status = 'ok' AND (ta.result->>'ai_detected')::boolean) AS ai_detected
  ```

  Add it to GROUP BY where needed, or leave it as an expression: Postgres accepts an `EXISTS` over `t.id` inside a `GROUP BY t.id`.
- [ ] **Dataclasses** get `ai_detected: bool = False`. The serializers emit `"ai_detected": bool(...)`. OpenAPI marks it required (boolean) in the 3 schemas.
- [ ] **Tests:**
  - the unit tests assert the key is present;
  - a pg test runs each list query on a seeded track with an ok `ai_detected=true` row, and checks `ai_detected` is true for it and false for its neighbour.
- [ ] Commit: `feat(analysis): expose ai_detected on track lists`.

### Task 9: Frontend

Filled in from the frontend map; see the section appended below.

### Task 10: Docs and guards

- [ ] **Docs.**
  - `docs/architecture.md`: a short "Audio analysis" paragraph plus a link to the spec.
  - `docs/ops/runbook.md`: an "Analysis service token" section (generate on the PC, put the hash, rotate, revoke = delete the parameter) and "Requeue".
  - `docs/data/data-model.md`: the `track_analyses` and `analysis_service_state` rows.
  - README counts: operations, Terraform resources.
- [ ] **Full run.** `pytest -q` (plus the db tests against local PG), ruff, `pnpm typecheck`, `pnpm lint`, `pnpm test`.
- [ ] Commit: `docs(analysis): document analysis API and token`.

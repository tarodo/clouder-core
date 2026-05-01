# Beatport Weekly Releases Collector

Serverless Python pipeline: API Lambda → S3 raw → SQS → Worker Lambda → Aurora Postgres (via RDS Data API).
See [README.md](README.md) for full architecture + API contracts.

## Commands

```bash
# Install dev deps
python -m pip install -r requirements-dev.txt

# Run tests (pytest auto-adds src/ to pythonpath via pytest.ini)
pytest -q
pytest tests/unit/test_canonicalize.py -q   # single file

# Migrations (local postgres)
export PYTHONPATH=src
export ALEMBIC_DATABASE_URL='postgresql+psycopg://postgres:postgres@localhost:5432/postgres'
alembic upgrade head

# Package Lambda zip → dist/collector.zip
scripts/package_lambda.sh

# Regenerate docs/openapi.yaml after editing scripts/generate_openapi.py:ROUTES
PYTHONPATH=src .venv/bin/python scripts/generate_openapi.py

# Terraform
cd infra && terraform init && terraform apply
```

## Layout

- `src/collector/` — single package, all Lambda code
  - `handler.py` — API Lambda (POST /collect_bp_releases, GET /runs/{run_id})
  - `worker_handler.py` — SQS-triggered canonicalization worker
  - `migration_handler.py` — invoked post-deploy to run alembic
  - `search_handler.py`, `spotify_handler.py`, `vendor_match_handler.py` — separate Lambdas
  - `vendor_match/` — `retry_vendor` decorator + fuzzy scorer used by the vendor_match Lambda
  - `data_api.py` — RDS Data API client (not psycopg at runtime)
  - `db_models.py` — SQLAlchemy models (used for alembic autogen only)
  - `normalize.py` / `canonicalize.py` — raw → canonical entity transform
  - `search/` — search subpackage
  - `providers/` — vendor abstraction layer
    - `base.py` — Protocols (`IngestProvider`, `LookupProvider`, `EnrichProvider`, `ExportProvider`) + dataclasses (`VendorTrackRef`, `EnrichResult`, `ProviderBundle`, ...)
    - `registry.py` — `get_lookup`/`get_enricher_for_prompt`/`get_exporter`/`list_enabled_exporters` accessors gated by `VENDORS_ENABLED`. Lazy per-vendor builders in `_BUILDERS` — disabled vendors are never instantiated.
    - `<vendor>/` — adapters wrapping existing clients (`beatport`, `spotify`, `perplexity`) or stubs (`ytmusic`, `deezer`, `apple`, `tidal`)
- `alembic/versions/` — migrations (packaged as `db_migrations/` in zip)
- `infra/` — Terraform (HTTP API Gateway, Lambdas, SQS+DLQ, Aurora v2 Serverless, VPC endpoints)
- `tests/unit/` + `tests/integration/`

## Gotchas

- **Runtime DB = Data API, not psycopg.** `data_api.py` used in Lambdas. `psycopg` only for local alembic. Don't import `psycopg` inside `collector/*` handler paths — breaks Lambda (not in `requirements-lambda.txt`).
- **`pythonpath = src`** is set in `pytest.ini`. For scripts outside pytest, export `PYTHONPATH=src`.
- **Packaging rename:** `package_lambda.sh` copies `alembic/` → `db_migrations/` in the zip. Code referencing migrations must use `db_migrations` path at Lambda runtime, `alembic` path locally.
- **`GET /runs/{run_id}` returns 503 `db_not_configured`** if `AURORA_*` env vars are missing — not a bug.
- **Queue visibility vs worker timeout:** keep `canonicalization_queue_visibility_timeout_seconds >= canonicalization_worker_lambda_timeout_seconds`, else duplicate processing.
- **`bp_token` must never be logged or stored in S3.** Sanitize before structlog.
- **Aurora auto-pause** after 300s — only when `aurora_serverless_min_acu = 0` (current default, chosen for cost: ~$43/mo saved vs. always-warm 0.5 ACU). First request after pause may 503 through API Gateway 29s timeout — bump to `0.5` in tfvars if first-request latency matters more than cost. `data_api.DataAPIClient` uses two retry decorators: `retry_data_api` (all transient codes) on read/write statements, and `retry_data_api_pre_execution` (only pre-execution codes) on `commit_transaction` / `rollback_transaction` to avoid retrying after partial commit. Non-idempotent writes must be inside a transaction or use UPSERT.
- **`find_identity` must receive `transaction_id`** when called inside a `repository.transaction()` block, otherwise reads miss in-flight writes.
- **Secrets cached per container.** `settings._fetch_secret_string` uses `lru_cache` — rotated Perplexity/Spotify keys require Lambda recycle to pick up.
- **AWS resource prefix = `beatport-prod-`** (from `var.project = "beatport"` + `var.environment = "prod"`). Lambda names: `beatport-prod-collector-api`, `beatport-prod-ai-search-worker`, etc. Repository dir name `clouder-core` ≠ AWS prefix.
- **Master RDS secret `rds!cluster-...` is required at runtime.** Runtime Lambdas pass it to Data API (`rds-data:ExecuteStatement`). Do NOT delete even after Aurora IAM auth cutover — only migration Lambda stopped using it.
- **Aurora IAM auth flag may not stick via Terraform.** If `aws rds describe-db-clusters --query '[0].IAMDatabaseAuthenticationEnabled'` returns `false` after `terraform apply` set it true, force via `aws rds modify-db-cluster --db-cluster-identifier <id> --enable-iam-database-authentication --apply-immediately`. Known AWS quirk on Serverless v2.
- **`clouder_migrator` DB role cannot self-grant `rds_iam` in IAM mode.** Must run GRANT as master user (RDS Query Editor → Connect with Secrets Manager ARN, or Data API `rds-data:ExecuteStatement`).
- **`release_type` is Spotify-only.** Beatport payload does not expose a release-type field — only nested `release.{id,name,label,slug}`. Values (`album`/`single`/`compilation`) come from Spotify `album.album_type` during ISRC enrichment and are then propagated from `clouder_tracks` onto the parent `clouder_albums` via `propagate_release_type_to_albums`. A track's `release_type` is therefore NULL until its ISRC lookup succeeds.
- **`is_ai_suspected` is propagated, not stored standalone.** After `save_search_result`, `propagate_ai_flag` sets/clears the flag on `clouder_labels/artists/tracks` only when `confidence >= AI_FLAG_CONFIDENCE_THRESHOLD` (default 0.6). `ai_content=unknown` is a no-op; `none_detected` explicitly clears. The flag is a soft filter — the authoritative finding lives in `ai_search_results`.
- **Adding a new vendor** = create `providers/<vendor>/<role>.py` with a class implementing the relevant Protocol, register a `_build_<vendor>` builder in `providers/registry.py:_BUILDERS`, and add the vendor name to `VENDORS_ENABLED`. Three steps, no handler changes. Vendor names not listed in `VENDORS_ENABLED` raise `VendorDisabledError` from registry accessors.
- **Provider classes are thin adapters.** Existing clients (`BeatportClient`, `SpotifyClient`, `search_label`) live in their original modules and are wrapped — do not duplicate vendor logic into `providers/`. Adapter signatures match handler call sites (batch + `correlation_id`), not the long-term per-track Protocol ideal.
- **`LookupProvider` gained per-track methods in Plan 4.** `lookup_by_isrc(isrc) -> VendorTrackRef | None` and `lookup_by_metadata(artist, title, duration_ms, album) -> list[VendorTrackRef]`. Spotify implements ISRC; metadata search returns `[]` until a follow-up fills it in (Beatport always carries ISRC so fuzzy fallback is rare). All other vendors still raise `VendorDisabledError(reason="not_implemented")`.
- **Vendor match cache is PK `(clouder_track_id, vendor)` — idempotent on retry.** `vendor_match_handler` upserts on hit; low-confidence candidates go to `match_review_queue` with a partial unique index on `status='pending'` so repeated sends do not duplicate review rows.
- **API Gateway has a 29s hard timeout.** Long-running calls (e.g. bulk `/collect_bp_releases`) exceed it: client gets `{"message":"Service Unavailable"}` (API GW format with capital S/U, NOT our `{error_code, message, correlation_id}` envelope) but the Lambda usually completes the work in background. With Aurora `min_acu=0` Aurora cold-start (after 300s idle) can be the dominant cause for the first request; otherwise the risk is long Beatport API calls. Retry the request after a few seconds.
- **Lambda reserved concurrency gated by `var.enable_lambda_reserved_concurrency` (default `false`).** AWS new-account `ConcurrentExecutions` quota is `10`, and `UnreservedConcurrentExecution` has a hard floor of `10`, so any positive `reserved_concurrent_executions` on `ai_search_worker` (2) + `spotify_search_worker` (3) + `vendor_match_worker` (2) trips `InvalidParameterValueException`. Raise the account quota via Service Quotas `L-B99A9384` to ≥ 17, then flip the flag to `true` to actually cap Perplexity / Spotify parallelism. Until then the workers run unreserved and Perplexity 429s flow back through SQS retry → DLQ.
- **`ai_search_results.result` is JSONB, not flat columns.** Columns are `id, entity_type, entity_id, prompt_slug, prompt_version, result, searched_at`. Query inner fields via `result->>'ai_content'`, `(result->>'confidence')::float`.
- **`/labels` API does not project `is_ai_suspected`.** The column exists on `clouder_labels` and is set by `propagate_ai_flag`, but `list_labels` SQL doesn't `SELECT` it. To verify the flag, query Aurora Data API directly: `SELECT COUNT(*) FROM clouder_labels WHERE is_ai_suspected = true`. Same gap likely on `/artists` and `/tracks`.
- **`scripts/generate_openapi.py:ROUTES` is a manual table.** Update it whenever API Gateway routes change (`infra/api_gateway.tf`, `infra/auth.tf`, `infra/curation.tf`). Without sync, `docs/openapi.yaml` (used as Postman import) goes stale silently.
- **macOS `python` is unavailable.** Use `python3` for stdlib-only scripts; for project scripts that import `yaml`/`pydantic`/etc., use `.venv/bin/python` (Homebrew `python3.14` lacks repo deps).

## Env Vars (runtime)

API/Worker Lambda: `RAW_BUCKET_NAME`, `RAW_PREFIX`, `BEATPORT_API_BASE_URL`, `CANONICALIZATION_ENABLED`, `CANONICALIZATION_QUEUE_URL`, `AURORA_CLUSTER_ARN`, `AURORA_SECRET_ARN`, `AURORA_DATABASE`, `LOG_LEVEL`.

`VENDORS_ENABLED`: comma-separated list of vendor names allowed at runtime (e.g. `"beatport,spotify,perplexity_label"`). Vendors not listed raise `VendorDisabledError` from `providers.registry` accessors. Default: empty (all vendors disabled). Known names: `beatport`, `spotify`, `perplexity_label`, `perplexity_artist`, `ytmusic`, `deezer`, `apple`, `tidal`. The artist + non-spotify vendors are stubs today — enabling them resolves the bundle but every method raises `VendorDisabledError` on use.

AI Search Worker: credential resolution precedence — `PERPLEXITY_API_KEY` (direct) > `PERPLEXITY_API_KEY_SSM_PARAMETER` (SSM SecureString name) > `PERPLEXITY_API_KEY_SECRET_ARN` (legacy Secrets Manager). Tuning: `AI_FLAG_CONFIDENCE_THRESHOLD` (float 0..1, default `0.6`) — minimum `confidence` from a label search below which the `is_ai_suspected` flag will not be set or cleared.

Spotify Worker: credential resolution precedence — `SPOTIFY_CLIENT_ID`+`SPOTIFY_CLIENT_SECRET` (direct) > `SPOTIFY_CLIENT_ID_SSM_PARAMETER`+`SPOTIFY_CLIENT_SECRET_SSM_PARAMETER` (both must be set, else falls through) > `SPOTIFY_CREDENTIALS_SECRET_ARN` (legacy SM JSON `{client_id, client_secret}`).

Vendor Match Worker: `VENDORS_ENABLED` (comma-separated list, e.g. `"spotify"`), plus the Spotify credential envs above. Tuning: `FUZZY_MATCH_THRESHOLD` (float 0..1, default `0.92`) — minimum fuzzy score to cache a match, anything below routes to `match_review_queue`; `FUZZY_DURATION_TOLERANCE_MS` (int, default `3000`) — duration match window for the `duration_ok` scoring component.

Migration Lambda: `AURORA_WRITER_ENDPOINT`, `AURORA_PORT`, `AURORA_DATABASE`. Plus auth: `AURORA_AUTH_MODE=password` (default, requires `AURORA_SECRET_ARN`) or `AURORA_AUTH_MODE=iam` (requires `AURORA_DB_USER`, no secret needed — uses RDS IAM token).

## CI

`.github/workflows/pr.yml` — `alembic-check` (ephemeral pg), `terraform` (fmt/validate/plan), `tests` (`pytest -q`).
`.github/workflows/deploy.yml` — package → `terraform apply` (prod: `canonicalization_enabled=true`) → invoke migration Lambda.

Workflow consumes GitHub Secrets from **environment `production`** (not repo-root Secrets): `PERPLEXITY_API_KEY`, `SPOTIFY_CLIENT_ID`, `SPOTIFY_CLIENT_SECRET`. Only `AWS_GITHUB_ROLE_ARN` lives at repo root.

## Commit Policy

All commit messages MUST be generated by the `caveman:caveman-commit` skill (Conventional Commits, terse). Workflow: invoke skill → take its output → `git commit -m "<skill output>"`. Never hand-write commit messages. A PreToolUse hook blocks `git commit` whose subject does not match `^(feat|fix|chore|docs|refactor|test|perf|build|ci|style|revert)(\(.+\))?!?: `.

## PR Policy

PR titles AND bodies MUST be generated by the `caveman:caveman-commit` skill before `gh pr create` (title = Conventional Commits subject, body = caveman-style summary + test plan, no AI attribution). A project-level PreToolUse hook in `.claude/settings.json` blocks `gh pr create` whose `--title` does not match `^(feat|fix|chore|docs|refactor|test|perf|build|ci|style|revert)(\(.+\))?!?: `.

## Branch Naming

Branches MUST NOT carry user or agent prefixes (no `tarodo/`, no `claude/`). Use `feat/<topic>`, `fix/<topic>`, `chore/<topic>`, `ci/<topic>`, `docs/<topic>`. Example: `feat/vendor-sync-foundation`, `fix/iam-auth-cutover`.

## Logs

```bash
aws logs tail "/aws/lambda/$(cd infra && terraform output -raw lambda_function_name)" --follow
```

Structlog events: `request_received`, `beatport_request/response`, `collection_completed`, `canonicalization_completed/failed`, `migration_started/completed`.

Aurora PostgreSQL server-side logs are NOT exported by default. To debug auth failures / query errors, enable once: `aws rds modify-db-cluster --db-cluster-identifier beatport-prod-aurora --cloudwatch-logs-export-configuration '{"EnableLogTypes":["postgresql"]}' --apply-immediately`. Then tail `/aws/rds/cluster/beatport-prod-aurora/postgresql`.

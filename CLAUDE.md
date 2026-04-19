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

# Terraform
cd infra && terraform init && terraform apply
```

## Layout

- `src/collector/` — single package, all Lambda code
  - `handler.py` — API Lambda (POST /collect_bp_releases, GET /runs/{run_id})
  - `worker_handler.py` — SQS-triggered canonicalization worker
  - `migration_handler.py` — invoked post-deploy to run alembic
  - `search_handler.py`, `spotify_handler.py` — separate Lambdas
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
- **Aurora auto-pause** after 300s (`min_acu=0`) — first request after idle is slow. `data_api.DataAPIClient` uses two retry decorators: `retry_data_api` (all transient codes) on read/write statements, and `retry_data_api_pre_execution` (only pre-execution codes) on `commit_transaction` / `rollback_transaction` to avoid retrying after partial commit. Non-idempotent writes must be inside a transaction or use UPSERT.
- **`find_identity` must receive `transaction_id`** when called inside a `repository.transaction()` block, otherwise reads miss in-flight writes.
- **Secrets cached per container.** `settings._fetch_secret_string` uses `lru_cache` — rotated Perplexity/Spotify keys require Lambda recycle to pick up.
- **AWS resource prefix = `beatport-prod-`** (from `var.project = "beatport"` + `var.environment = "prod"`). Lambda names: `beatport-prod-collector-api`, `beatport-prod-ai-search-worker`, etc. Repository dir name `clouder-core` ≠ AWS prefix.
- **Master RDS secret `rds!cluster-...` is required at runtime.** Runtime Lambdas pass it to Data API (`rds-data:ExecuteStatement`). Do NOT delete even after Aurora IAM auth cutover — only migration Lambda stopped using it.
- **Aurora IAM auth flag may not stick via Terraform.** If `aws rds describe-db-clusters --query '[0].IAMDatabaseAuthenticationEnabled'` returns `false` after `terraform apply` set it true, force via `aws rds modify-db-cluster --db-cluster-identifier <id> --enable-iam-database-authentication --apply-immediately`. Known AWS quirk on Serverless v2.
- **`clouder_migrator` DB role cannot self-grant `rds_iam` in IAM mode.** Must run GRANT as master user (RDS Query Editor → Connect with Secrets Manager ARN, or Data API `rds-data:ExecuteStatement`).
- **`release_type` is Spotify-only.** Beatport payload does not expose a release-type field — only nested `release.{id,name,label,slug}`. Values (`album`/`single`/`compilation`) come from Spotify `album.album_type` during ISRC enrichment and are then propagated from `clouder_tracks` onto the parent `clouder_albums` via `propagate_release_type_to_albums`. A track's `release_type` is therefore NULL until its ISRC lookup succeeds.
- **`is_ai_suspected` is propagated, not stored standalone.** After `save_search_result`, `propagate_ai_flag` sets/clears the flag on `clouder_labels/artists/tracks` only when `confidence >= AI_FLAG_CONFIDENCE_THRESHOLD` (default 0.6). `ai_content=unknown` is a no-op; `none_detected` explicitly clears. The flag is a soft filter — the authoritative finding lives in `ai_search_results`.
- **Adding a new vendor** = create `providers/<vendor>/<role>.py` with a class implementing the relevant Protocol, register a `_build_<vendor>` builder in `providers/registry.py:_BUILDERS`, and add the vendor name to `VENDORS_ENABLED`. Three steps, no handler changes. Vendor names not listed in `VENDORS_ENABLED` raise `VendorDisabledError` from registry accessors.
- **Provider classes are thin adapters.** Existing clients (`BeatportClient`, `SpotifyClient`, `search_label`) live in their original modules and are wrapped — do not duplicate vendor logic into `providers/`. Adapter signatures match handler call sites (batch + `correlation_id`), not the long-term per-track Protocol ideal. Per-track lookup methods will be added when first consumed (e.g. playlist export in Plan 4).

## Env Vars (runtime)

API/Worker Lambda: `RAW_BUCKET_NAME`, `RAW_PREFIX`, `BEATPORT_API_BASE_URL`, `CANONICALIZATION_ENABLED`, `CANONICALIZATION_QUEUE_URL`, `AURORA_CLUSTER_ARN`, `AURORA_SECRET_ARN`, `AURORA_DATABASE`, `LOG_LEVEL`.

`VENDORS_ENABLED`: comma-separated list of vendor names allowed at runtime (e.g. `"beatport,spotify,perplexity_label"`). Vendors not listed raise `VendorDisabledError` from `providers.registry` accessors. Default: empty (all vendors disabled). Known names: `beatport`, `spotify`, `perplexity_label`, `perplexity_artist`, `ytmusic`, `deezer`, `apple`, `tidal`. The artist + non-spotify vendors are stubs today — enabling them resolves the bundle but every method raises `VendorDisabledError` on use.

AI Search Worker: credential resolution precedence — `PERPLEXITY_API_KEY` (direct) > `PERPLEXITY_API_KEY_SSM_PARAMETER` (SSM SecureString name) > `PERPLEXITY_API_KEY_SECRET_ARN` (legacy Secrets Manager). Tuning: `AI_FLAG_CONFIDENCE_THRESHOLD` (float 0..1, default `0.6`) — minimum `confidence` from a label search below which the `is_ai_suspected` flag will not be set or cleared.

Spotify Worker: credential resolution precedence — `SPOTIFY_CLIENT_ID`+`SPOTIFY_CLIENT_SECRET` (direct) > `SPOTIFY_CLIENT_ID_SSM_PARAMETER`+`SPOTIFY_CLIENT_SECRET_SSM_PARAMETER` (both must be set, else falls through) > `SPOTIFY_CREDENTIALS_SECRET_ARN` (legacy SM JSON `{client_id, client_secret}`).

Migration Lambda: `AURORA_WRITER_ENDPOINT`, `AURORA_PORT`, `AURORA_DATABASE`. Plus auth: `AURORA_AUTH_MODE=password` (default, requires `AURORA_SECRET_ARN`) or `AURORA_AUTH_MODE=iam` (requires `AURORA_DB_USER`, no secret needed — uses RDS IAM token).

## CI

`.github/workflows/pr.yml` — `alembic-check` (ephemeral pg), `terraform` (fmt/validate/plan), `tests` (`pytest -q`).
`.github/workflows/deploy.yml` — package → `terraform apply` (prod: `canonicalization_enabled=true`) → invoke migration Lambda.

Workflow consumes GitHub Secrets from **environment `production`** (not repo-root Secrets): `PERPLEXITY_API_KEY`, `SPOTIFY_CLIENT_ID`, `SPOTIFY_CLIENT_SECRET`. Only `AWS_GITHUB_ROLE_ARN` lives at repo root.

## Commit Policy

All commit messages MUST be generated by the `caveman:caveman-commit` skill (Conventional Commits, terse). Workflow: invoke skill → take its output → `git commit -m "<skill output>"`. Never hand-write commit messages. A PreToolUse hook blocks `git commit` whose subject does not match `^(feat|fix|chore|docs|refactor|test|perf|build|ci|style|revert)(\(.+\))?!?: `.

## Branch Naming

Branches MUST NOT carry user or agent prefixes (no `tarodo/`, no `claude/`). Use `feat/<topic>`, `fix/<topic>`, `chore/<topic>`, `ci/<topic>`, `docs/<topic>`. Example: `feat/vendor-sync-foundation`, `fix/iam-auth-cutover`.

## Logs

```bash
aws logs tail "/aws/lambda/$(cd infra && terraform output -raw lambda_function_name)" --follow
```

Structlog events: `request_received`, `beatport_request/response`, `collection_completed`, `canonicalization_completed/failed`, `migration_started/completed`.

Aurora PostgreSQL server-side logs are NOT exported by default. To debug auth failures / query errors, enable once: `aws rds modify-db-cluster --db-cluster-identifier beatport-prod-aurora --cloudwatch-logs-export-configuration '{"EnableLogTypes":["postgresql"]}' --apply-immediately`. Then tail `/aws/rds/cluster/beatport-prod-aurora/postgresql`.

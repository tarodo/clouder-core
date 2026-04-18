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

## Env Vars (runtime)

API/Worker Lambda: `RAW_BUCKET_NAME`, `RAW_PREFIX`, `BEATPORT_API_BASE_URL`, `CANONICALIZATION_ENABLED`, `CANONICALIZATION_QUEUE_URL`, `AURORA_CLUSTER_ARN`, `AURORA_SECRET_ARN`, `AURORA_DATABASE`, `LOG_LEVEL`.

AI Search Worker: credential resolution precedence — `PERPLEXITY_API_KEY` (direct) > `PERPLEXITY_API_KEY_SSM_PARAMETER` (SSM SecureString name) > `PERPLEXITY_API_KEY_SECRET_ARN` (legacy Secrets Manager).

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

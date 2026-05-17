# Runtime Gotchas

Known sharp edges that have caused real bugs or confusion. Each entry has what happened, why it happens, and how to avoid or mitigate it.

---

## Runtime and Packaging

### Data API at runtime, psycopg only for migrations

**What:** Lambda functions use `src/collector/data_api.py:DataAPIClient` (HTTP-based RDS Data API). `psycopg` is not in `requirements-lambda.txt` and must not be imported in any handler or collector module.

**Why:** Data API requires no persistent TCP connection and works with Aurora Serverless v2 pause/resume. `psycopg` requires a connection pool, native C extension, and an always-on socket — none of which work reliably in Lambda with Aurora auto-pause.

**Mitigation:** Keep all `psycopg` imports inside `migration_handler.py` and local Alembic scripts. If you see `ModuleNotFoundError: No module named 'psycopg'` in a Lambda log, a handler module imported `psycopg` transitively. Grep for the import and move it behind a guard or into the migration path only.

See also: [data-api.md](data-api.md), [ADR-0001](../adr/0001-data-api-runtime.md).

---

### `PYTHONPATH=src` required outside pytest

**What:** `pytest.ini` sets `pythonpath = src`. Any script run directly with `python3` or `.venv/bin/python` does not get this automatically.

**Why:** `src/` is not a package root in the standard sense. Without it on `PYTHONPATH`, `import collector` fails with `ModuleNotFoundError`.

**Mitigation:** Export before running scripts:

```bash
export PYTHONPATH=src
python3 scripts/generate_openapi.py
```

For scripts that import `yaml`, `pydantic`, etc. (which are in `.venv` but not in the system Homebrew Python on macOS), use `.venv/bin/python` instead of `python3`.

---

### Lambda zip renames `alembic/` → `db_migrations/`

**What:** `scripts/package_lambda.sh` copies `alembic/` to `db_migrations/` inside `dist/collector.zip`. At Lambda runtime, the script location is `db_migrations/`, not `alembic/`.

**Why:** The Alembic ini path is set dynamically in `migration_handler.py` via `root_dir / "db_migrations"`. Using `alembic/` would fail at runtime because the zip does not contain that path.

**Mitigation:** Any code that references the migrations directory must use `alembic/` locally and `db_migrations/` in Lambda context. The migration handler resolves this automatically. Do not hardcode either path in shared modules.

---

### AWS resource prefix is `beatport-prod-*`

**What:** All AWS resources are named with prefix `beatport-prod-` regardless of the repository directory name (`clouder-core`).

**Why:** Terraform derives the prefix from `var.project = "beatport"` + `var.environment = "prod"`. The repository name has no effect.

**Mitigation:** When looking up Lambda logs, SQS queues, or Aurora clusters in the AWS Console or CLI, use `beatport-prod-` as the prefix. Example:

```bash
aws logs tail "/aws/lambda/beatport-prod-collector-api" --follow
```

---

### macOS `python` is unavailable

**What:** On macOS with Homebrew Python 3.14, `python` is not in `PATH`. Only `python3` and `.venv/bin/python` are available.

**Why:** Homebrew does not create the `python` symlink to avoid shadowing system Python.

**Mitigation:** Use `python3` for stdlib-only scripts. For scripts that import project dependencies, use `.venv/bin/python` (the virtualenv created from `requirements-dev.txt`).

---

## Secrets and Authentication

### `bp_token` must never be logged or stored

**What:** The Beatport API token (`bp_token`) from the ingest request body is a user credential. It must not appear in any log line or be written to S3.

**Why:** Structlog events in `handler.py` are sent to CloudWatch. S3 raw objects are stored for audit purposes. Leaking the token into either would expose user credentials.

**Mitigation:** The `_run_beatport_ingest` function deliberately excludes `bp_token` from all `log_event` calls. When adding new log statements in handler code, verify that `bp_token` (and other secrets) are not included. Code review should flag any `log_event(..., bp_token=...)` pattern.

---

### Master RDS secret (`rds!cluster-...`) must not be deleted

**What:** The Aurora cluster has a master secret managed by AWS (`rds!cluster-...`). Runtime Lambdas pass it to the Data API via `rds-data:ExecuteStatement`.

**Why:** The Data API requires a Secrets Manager ARN with DB credentials. Even after an Aurora IAM auth cutover for the Migration Lambda, the Data API path for runtime Lambdas still uses this secret.

**Mitigation:** Do not delete the master secret after an IAM auth migration. Only the Migration Lambda stopped using it; all runtime `DataAPIClient` instances still require it.

---

### Aurora IAM auth flag may not stick via Terraform

**What:** After `terraform apply` sets `enable_iam_database_authentication = true`, `aws rds describe-db-clusters --query '[0].IAMDatabaseAuthenticationEnabled'` may still return `false`.

**Why:** Known AWS quirk on Aurora Serverless v2: Terraform's update is accepted without error but not applied.

**Mitigation:** Force the change via the AWS CLI directly:

```bash
aws rds modify-db-cluster \
  --db-cluster-identifier beatport-prod-aurora \
  --enable-iam-database-authentication \
  --apply-immediately
```

Also verify that the `clouder_migrator` DB role has the `rds_iam` privilege granted by the master user (not self-granted — Aurora IAM roles cannot be self-granted).

See also: [ADR-0005](../adr/0005-iam-auth-migration.md).

---

### Secrets cached per container; rotation requires Lambda recycle

**What:** `settings._fetch_secret_string` (`src/collector/settings.py:14`) is decorated with `@functools.lru_cache`. SSM parameters are similarly cached in `secrets._fetch_ssm_parameter` (`src/collector/secrets.py:22`).

**Why:** Fetching secrets on every invocation would add latency and cost. The cache is bounded to the container lifetime, which is acceptable for long-lived API keys.

**Mitigation:** After rotating a Perplexity or Spotify API key, force a container recycle (deploy a no-op env var change to the Lambda). The new key will be picked up on the next cold start. There is no in-process way to invalidate the cache without a restart.

---

## Concurrency and SQS

### Queue visibility timeout must be >= worker timeout

**What:** `CANONICALIZATION_QUEUE_VISIBILITY_TIMEOUT_SECONDS` must be set to at least `CANONICALIZATION_WORKER_LAMBDA_TIMEOUT_SECONDS` in Terraform (`infra/`).

**Why:** If the Lambda runs longer than the visibility timeout, SQS makes the message visible again and another Lambda instance picks it up — causing two workers to process the same run concurrently. Canonicalization upserts are idempotent, but the concurrent execution wastes resources and produces confusing double-log events.

**Mitigation:** In `infra/`, keep the SQS visibility timeout value strictly greater than the Lambda timeout. A 10–20% buffer (e.g., `900s` visibility for a `600s` Lambda timeout) is recommended.

---

### Lambda reserved concurrency is off by default

**What:** `var.enable_lambda_reserved_concurrency` defaults to `false`. When `true`, the AI search worker gets 2, Spotify search worker gets 3, and vendor match worker gets 2 reserved concurrent executions.

**Why:** AWS new accounts have a `ConcurrentExecutions` quota of 10, and `UnreservedConcurrentExecution` has a hard floor of 10. Assigning any reserved concurrency to these three workers (total 7) would consume the entire budget, tripping `InvalidParameterValueException` on `terraform apply`.

**Mitigation:** Raise the account quota (`L-B99A9384`) to at least 17 via AWS Service Quotas, then set `enable_lambda_reserved_concurrency = true` in `infra/terraform.tfvars`. Until then, workers run unreserved and Perplexity 429s flow through SQS retry → DLQ.

---

## Behavioural Surprises

### `GET /runs/{run_id}` returns 503 `db_not_configured`

**What:** The endpoint returns HTTP 503 with `error_code: db_not_configured` when `AURORA_CLUSTER_ARN` or `AURORA_SECRET_ARN` are absent from the Lambda environment.

**Why:** `create_clouder_repository_from_env()` returns `None` when Aurora env vars are missing. The handler checks for `None` and short-circuits with a 503 rather than crashing.

**Mitigation:** This is intentional for environments where Aurora is not configured. In production, both vars are set and the endpoint works normally. If you see this 503 in production, check the Lambda environment variables for `beatport-prod-collector-api`.

---

### API Gateway 29-second hard timeout

**What:** API Gateway has a 29-second maximum integration timeout. Long-running Lambda calls (bulk ingest, Aurora cold-start after 5+ minutes idle with `min_acu=0`) cause API Gateway to return `{"message":"Service Unavailable"}` with capital S/U — this is NOT the application's error envelope.

**Why:** API Gateway enforces the timeout before the Lambda invocation completes. The Lambda usually finishes the work in background; the client just doesn't see the response.

**Mitigation options:**
- Retry the same request after a few seconds; the run was likely already created.
- To eliminate Aurora cold-start latency: set `aurora_serverless_min_acu = 0.5` in `infra/terraform.tfvars` (adds ~$43/month to keep the cluster warm, but eliminates the 503 on first request after idle).
- Distinguish the API Gateway timeout from application errors: the application always returns `{"error_code": ..., "message": ..., "correlation_id": ...}` (camelCase statusCode in Lambda response); API Gateway's own timeout uses `{"message": "Service Unavailable"}` without `error_code`.

See also: [ADR-0014](../adr/0014-aurora-min-acu-zero.md).

---

### List endpoints do not project `is_ai_suspected`

**What:** `GET /labels`, `GET /artists`, and `GET /tracks` do not include the `is_ai_suspected` field in their response items, even though `clouder_labels.is_ai_suspected` is set by `propagate_ai_flag`.

**Why:** The SQL in `ClouderRepository.list_labels` (and equivalents) does not `SELECT is_ai_suspected`. This was an oversight when the column was added.

**Mitigation:** To verify the flag, query Aurora directly via the RDS Query Editor or the Data API:

```sql
SELECT COUNT(*) FROM clouder_labels WHERE is_ai_suspected = true;
```

Adding the column to the list responses requires updating the SQL in the repository and the OpenAPI spec (`docs/api/openapi.yaml`), then regenerating `frontend/src/api/schema.d.ts` via `pnpm api:types`.

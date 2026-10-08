# Deploy

CLOUDER uses two GitHub Actions workflows: `pr.yml` for pre-merge validation and `deploy.yml` for production deployment. Both authenticate to AWS via OIDC.

## Pull request checks

`.github/workflows/pr.yml` — triggered on every PR targeting `main`. Jobs are path-filtered (dorny/paths-filter) so only the affected subset runs.

| Job | Trigger path | Steps |
|-----|-------------|-------|
| `alembic-check` | `src/**`, `alembic/**`, `requirements*.txt` | Spin ephemeral Postgres 16, run `alembic upgrade head` twice (idempotency check), then the real-Postgres tests (`tests/db`, `TEST_DATABASE_URL`) |
| `dbt` | `dbt/**` | `dbt seed` / `run --empty` / `build` on DuckDB with fixtures (unit + data tests), then `dbt parse --target prod` |
| `terraform` | `infra/**` | `terraform fmt -check`, `terraform init` (remote S3 backend), `terraform validate`, `scripts/package_lambda.sh`, `terraform plan -var="environment=prod" -var="canonicalization_enabled=true"` |
| `lint` | backend paths | `ruff check src tests scripts` and `mypy` (config in `pyproject.toml`) |
| `tests` | `src/**`, `tests/**` | `pytest -q --cov` with `PYTHONPATH=src`; fails under 80 % line coverage; TOTAL goes to the job summary |
| `deps` | always | `uv pip compile` re-run must not change `requirements-*.txt`; `pip-audit` on both locks; `pnpm audit --prod --audit-level high` |
| `frontend` | `frontend/**`, `docs/api/openapi.yaml` | `pnpm api:types` + diff-check `src/api/schema.d.ts` against `docs/api/openapi.yaml` (fails if out of sync), `pnpm typecheck`, `pnpm lint`, `pnpm test`, `pnpm build` |

OpenAPI types check: if `docs/api/openapi.yaml` is updated without regenerating `frontend/src/api/schema.d.ts`, the `frontend` job fails. Run `pnpm api:types` from `frontend/` and commit the result.

Terraform backend: state bucket and lock table names come from GitHub Actions repo variables `TF_STATE_BUCKET` and `TF_LOCK_TABLE`. Backend key: `clouder-core/prod/terraform.tfstate`.

## Dependencies

Declared in `requirements-lambda.in` (Lambda runtime; boto3 comes with the runtime) and `requirements-dev.in` (adds test and CI tools), locked into the matching `.txt` files with `uv pip compile --universal --python-version 3.12 <file>.in -o <file>.txt`. uv keeps existing pins, so recompiling only changes what an edited `.in` asks for; `--upgrade-package <name>` bumps one dependency. Dependabot opens weekly grouped PRs for pip, npm, GitHub Actions and Terraform.

## Deploy pipeline

`.github/workflows/deploy.yml` — triggered on push to `main`, or by hand (`workflow_dispatch`, `main` only — e.g. to re-sync a changed secret). Runs in the `production` environment.

Order of steps:

1. **Package Lambda** — `scripts/package_lambda.sh`
   - Installs `requirements-lambda.txt` (locked from `requirements-lambda.in` with `uv pip compile --universal --python-version 3.12`) into `dist/lambda_build/`
   - Copies `src/collector/` → `dist/lambda_build/collector/`
   - Copies `alembic/` → `dist/lambda_build/db_migrations/` (packaging rename; code references `db_migrations` at Lambda runtime)
   - Produces `dist/collector.zip`

2. **Sync secrets to SSM Parameter Store** — pushes GitHub Secrets as SSM SecureStrings before Terraform runs, so Lambda env vars reference stable SSM paths:
   - `/clouder/gemini/api_key`, `/clouder/openai/api_key`, `/clouder/tavily/api_key`, `/clouder/deepseek/api_key`
   - `/clouder/spotify/client_id`, `/clouder/spotify/client_secret`
   - `/clouder/ytmusic/client_id`, `/clouder/ytmusic/client_secret`, `/clouder/youtube/api_key`
   - `/clouder/beatport/username`, `/clouder/beatport/password` (auto-ingest; skipped while unset)

3. **Terraform apply, two phases** — first `-target=aws_lambda_function.db_migration` (so the migration Lambda carries the new Alembic revisions), then step 4, then the full apply. A single apply once updated the API before the schema and produced 2 min 40 s of HTTP 500s (2026-09-20). The `-var` list lives in `deploy.yml`; `TF_VAR_beatport_client_id` and `TF_VAR_alarm_email` come from secrets on the full apply.

4. **Run DB migrations** — invokes the migration Lambda synchronously:
   ```bash
   aws lambda invoke \
     --function-name "$(terraform output -raw migration_lambda_function_name)" \
     --payload '{"action":"upgrade","revision":"head"}' \
     --cli-binary-format raw-in-base64-out \
     /tmp/migration-response.json
   ```
   Checks `FunctionError` in meta and `status != "ok"` in response body; fails the workflow if either is set.

5. **Full Terraform apply** — the rest of the stack, including the API Lambdas.

6. **Frontend deploy** — `scripts/deploy_frontend.sh` (see [Frontend deploy](#frontend-deploy) below).

## Frontend deploy

`scripts/deploy_frontend.sh`:

1. `pnpm install --frozen-lockfile && pnpm build` from `frontend/`
2. Reads `BUCKET` and `DIST_ID` from `terraform output` (`frontend_bucket`, `frontend_distribution_id`)
3. `aws s3 sync dist/ s3://$BUCKET/ --delete` for hashed assets with `Cache-Control: public,max-age=31536000,immutable`, excluding `index.html`
4. `aws s3 cp dist/index.html` with `Cache-Control: no-cache,no-store,must-revalidate`
5. `aws cloudfront create-invalidation --paths "/index.html"` — forces CDN to serve the fresh shell on next viewer request

CloudFront distribution and S3 bucket are managed in `infra/frontend.tf`.

## GitHub Secrets

Secrets are scoped to the **`production` environment** (not repo-root) in GitHub Actions settings. The deploy workflow references them as `${{ secrets.* }}` only within the `environment: production` job context.

| Secret | Scope | Used by |
|--------|-------|---------|
| `GEMINI_API_KEY`, `OPENAI_API_KEY`, `TAVILY_API_KEY`, `DEEPSEEK_API_KEY` | `production` environment | Synced to `/clouder/<vendor>/api_key` SSM (label/artist enrichment) |
| `SPOTIFY_CLIENT_ID` | `production` environment | Synced to `/clouder/spotify/client_id` SSM |
| `SPOTIFY_CLIENT_SECRET` | `production` environment | Synced to `/clouder/spotify/client_secret` SSM |
| `YTMUSIC_CLIENT_ID`, `YTMUSIC_CLIENT_SECRET` | `production` environment | Synced to `/clouder/ytmusic/client_{id,secret}` SSM (YouTube Music OAuth) |
| `YOUTUBE_API_KEY` | `production` environment | Synced to `/clouder/youtube/api_key` SSM (YouTube Data API, comments) |
| `BEATPORT_USERNAME` | `production` environment | Synced to `/clouder/beatport/username` SSM (auto-ingest login; step skipped while unset) |
| `BEATPORT_PASSWORD` | `production` environment | Synced to `/clouder/beatport/password` SSM (auto-ingest login; step skipped while unset) |
| `BEATPORT_CLIENT_ID` | `production` environment | `TF_VAR_beatport_client_id` → auto-ingest Lambda env `BEATPORT_CLIENT_ID` (public OAuth id from the JS of `api.beatport.com/v4/docs/`; not in code). Unset: deploy passes, the login fails at step `client_id`. Change it and run Deploy by hand if Beatport rotates the id |
| `ALARM_EMAIL` | `production` environment | `TF_VAR_alarm_email` → SNS topic `clouder-prod-alarms` with an email subscription; every CloudWatch alarm (and its OK) goes there. AWS first mails a confirmation link — nothing is delivered until it is clicked. Unset: no topic, alarms stay console-only |
| `BUDGET_MONTHLY_LIMIT` | `production` environment | `TF_VAR_budget_monthly_limit` → AWS Budgets `clouder-prod-monthly` (a plain number of USD), emailing `ALARM_EMAIL` at 80 % of actual and 100 % of forecast spend. Unset (or no `ALARM_EMAIL`): no budget. The amount is a secret only because the repo is public |
| `AWS_GITHUB_ROLE_ARN` | Repo root | OIDC role assumption in both workflows |

GitHub Actions repo variables (not secrets): `TF_STATE_BUCKET`, `TF_LOCK_TABLE`, `SPOTIFY_OAUTH_REDIRECT_URI`, `ADMIN_SPOTIFY_IDS`, `ALLOWED_FRONTEND_REDIRECTS`.

## Manual operations

**Toggle IAM authentication on Aurora** (needed if Terraform apply does not persist the flag — known AWS Serverless v2 quirk; see `docs/ops/aurora.md`):

```bash
aws rds modify-db-cluster \
  --db-cluster-identifier clouder-prod-aurora \
  --enable-iam-database-authentication \
  --apply-immediately
```

**Force-update a Lambda env var** without a full Terraform cycle:

```bash
aws lambda update-function-configuration \
  --function-name clouder-prod-label-enricher-worker \
  --environment "Variables={AI_FLAG_CONFIDENCE_THRESHOLD=0.7}"
```

> **`--environment` replaces the whole variables map — it does not merge.** Running the command above as-is drops every other variable on that Lambda (Aurora ARNs, queue URLs, SSM parameter names) and breaks it. Read the current map first and pass it back in full:
>
> ```bash
> aws lambda get-function-configuration \
>   --function-name clouder-prod-label-enricher-worker \
>   --query "Environment.Variables"
> ```
>
> Terraform is the source of truth; a manual override is undone by the next `terraform apply`.

Note: secrets cached per container via `lru_cache` in `src/collector/settings.py`. Rotated credentials require a Lambda recycle (deploy a new version, or update configuration to force cold start).

**Manual migration** (break-glass — prefer the Lambda invoke path):

```bash
export PYTHONPATH=src
export ALEMBIC_DATABASE_URL='postgresql+psycopg://postgres:postgres@<host>:5432/<db>'
alembic upgrade head
```

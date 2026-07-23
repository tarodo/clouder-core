# Deploy

CLOUDER uses two GitHub Actions workflows: `pr.yml` for pre-merge validation and `deploy.yml` for production deployment. Both authenticate to AWS via OIDC.

## Pull request checks

`.github/workflows/pr.yml` — triggered on every PR targeting `main`. Jobs are path-filtered (dorny/paths-filter) so only the affected subset runs.

| Job | Trigger path | Steps |
|-----|-------------|-------|
| `alembic-check` | `src/**`, `alembic/**`, `requirements*.txt` | Spin ephemeral Postgres 16, run `alembic upgrade head` twice (idempotency check) |
| `terraform` | `infra/**` | `terraform fmt -check`, `terraform init` (remote S3 backend), `terraform validate`, `scripts/package_lambda.sh`, `terraform plan -var="environment=prod" -var="canonicalization_enabled=true"` |
| `tests` | `src/**`, `tests/**` | `pytest -q` with `PYTHONPATH=src` |
| `frontend` | `frontend/**`, `docs/api/openapi.yaml` | `pnpm api:types` + diff-check `src/api/schema.d.ts` against `docs/api/openapi.yaml` (fails if out of sync), `pnpm typecheck`, `pnpm lint`, `pnpm test`, `pnpm build` |

OpenAPI types check: if `docs/api/openapi.yaml` is updated without regenerating `frontend/src/api/schema.d.ts`, the `frontend` job fails. Run `pnpm api:types` from `frontend/` and commit the result.

Terraform backend: state bucket and lock table names come from GitHub Actions repo variables `TF_STATE_BUCKET` and `TF_LOCK_TABLE`. Backend key: `clouder-core/prod/terraform.tfstate`.

## Deploy pipeline

`.github/workflows/deploy.yml` — triggered on push to `main`. Runs in the `production` environment.

Order of steps:

1. **Package Lambda** — `scripts/package_lambda.sh`
   - Installs `requirements-lambda.txt` into `dist/lambda_build/`
   - Copies `src/collector/` → `dist/lambda_build/collector/`
   - Copies `alembic/` → `dist/lambda_build/db_migrations/` (packaging rename; code references `db_migrations` at Lambda runtime)
   - Produces `dist/collector.zip`

2. **Sync secrets to SSM Parameter Store** — pushes GitHub Secrets as SSM SecureStrings before Terraform runs so Lambda env vars reference stable SSM paths:
   - `/clouder/perplexity/api_key`
   - `/clouder/spotify/client_id`
   - `/clouder/spotify/client_secret`

3. **Terraform apply** — `terraform apply -auto-approve` with prod vars:
   ```
   -var="environment=prod"
   -var="canonicalization_enabled=true"
   -var="ai_search_enabled=true"
   -var="spotify_search_enabled=true"
   -var="perplexity_api_key_ssm_parameter=/clouder/perplexity/api_key"
   -var="spotify_client_id_ssm_parameter=/clouder/spotify/client_id"
   -var="spotify_client_secret_ssm_parameter=/clouder/spotify/client_secret"
   -var="migration_aurora_auth_mode=iam"
   ```

4. **Run DB migrations** — invokes the migration Lambda synchronously:
   ```bash
   aws lambda invoke \
     --function-name "$(terraform output -raw migration_lambda_function_name)" \
     --payload '{"action":"upgrade","revision":"head"}' \
     --cli-binary-format raw-in-base64-out \
     /tmp/migration-response.json
   ```
   Checks `FunctionError` in meta and `status != "ok"` in response body; fails the workflow if either is set.

5. **Frontend deploy** — `scripts/deploy_frontend.sh` (see [Frontend deploy](#frontend-deploy) below).

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
| `PERPLEXITY_API_KEY` | `production` environment | Synced to `/clouder/perplexity/api_key` SSM |
| `SPOTIFY_CLIENT_ID` | `production` environment | Synced to `/clouder/spotify/client_id` SSM |
| `SPOTIFY_CLIENT_SECRET` | `production` environment | Synced to `/clouder/spotify/client_secret` SSM |
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

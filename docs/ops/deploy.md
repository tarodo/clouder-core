# Deploy

CLOUDER uses two GitHub Actions workflows: `pr.yml` for pre-merge validation and `deploy.yml` for production deployment. Both authenticate to AWS via OIDC.

## Pull request checks

`.github/workflows/pr.yml` — triggered on every PR targeting `main`. Jobs are path-filtered (dorny/paths-filter) so only the affected subset runs.

| Job | Trigger path | Steps |
|-----|-------------|-------|
| `alembic-check` | `src/**`, `alembic/**`, `requirements*.txt` | Spin ephemeral Postgres 16, run `alembic upgrade head` twice (idempotency check), then the real-Postgres tests (`tests/db`, `TEST_DATABASE_URL`) |
| `dbt` | `dbt/**` | `dbt seed` / `run --empty` / `build` on DuckDB with fixtures (unit + data tests), then `dbt parse --target prod` |
| `terraform` | `infra/**` | `scripts/package_lambda.sh`, `terraform fmt -check`, then under the read-only role `clouder-prod-gha-plan`: `terraform init` (remote S3 backend), `terraform validate`, `terraform plan -var-file=prod.tfvars` with the deploy's `TF_VAR_*` inputs — the plan is what the deploy would apply ([ADR-0028](../adr/0028-ci-roles.md)). Dependabot PRs (no secrets) run `init -backend=false` + `validate` only |
| `lint` | backend paths | `ruff check` and `ruff format --check` on `src tests scripts`, and `mypy` (untyped bodies checked; the core ingest/DQ modules strictly) — config in `pyproject.toml` |
| `tests` | `src/**`, `tests/**` | `pytest -q --cov` with `PYTHONPATH=src`; fails under 80 % line coverage; TOTAL goes to the job summary |
| `deps` | always | `uv pip compile` re-run must not change `requirements-*.txt`; `pip-audit` on both locks; `pnpm audit --prod --audit-level high` |
| `frontend` | `frontend/**`, `docs/api/openapi.yaml` | `pnpm api:types` + diff-check `src/api/schema.d.ts` against `docs/api/openapi.yaml` (fails if out of sync), `pnpm typecheck`, `pnpm lint`, `pnpm test`, `pnpm build` |

OpenAPI types check: if `docs/api/openapi.yaml` is updated without regenerating `frontend/src/api/schema.d.ts`, the `frontend` job fails. Run `pnpm api:types` from `frontend/` and commit the result.

Terraform backend: state bucket and lock table names come from GitHub Actions repo variables `TF_STATE_BUCKET` and `TF_LOCK_TABLE`. Backend key: `clouder-core/prod/terraform.tfstate`.

## Dependencies

Declared in `requirements-lambda.in` (Lambda runtime; boto3 comes with the runtime) and `requirements-dev.in` (adds test and CI tools), locked into the matching `.txt` files with `uv pip compile --universal --python-version 3.12 <file>.in -o <file>.txt`. uv keeps existing pins, so recompiling only changes what an edited `.in` asks for; `--upgrade-package <name>` bumps one dependency. Dependabot opens weekly PRs for npm, GitHub Actions, Terraform and the dbt requirements; root Python locks are upgraded with `make upgrade` (Dependabot's own compile would fail the lock-drift check), and its pip security PRs need `make lock` on their branch.

## Deploy pipeline

`.github/workflows/deploy.yml` — triggered on push to `main`, or by hand (`workflow_dispatch`, `main` only — e.g. to re-sync a changed secret). Runs in the `production` environment.

Deploys never overlap: job-level `concurrency: deploy-production` queues a second merge behind the first.

Order of steps:

1. **Package Lambda** — `scripts/package_lambda.sh`
   - Installs `requirements-lambda.txt` (locked from `requirements-lambda.in` with `uv pip compile --universal --python-version 3.12`) into `dist/lambda_build/`
   - Copies `src/collector/` → `dist/lambda_build/collector/`
   - Copies `alembic/` → `dist/lambda_build/db_migrations/` (packaging rename; code references `db_migrations` at Lambda runtime)
   - Produces `dist/collector.zip`
   - Runs, with the frontend build (`scripts/deploy_frontend.sh build`), before AWS credentials are configured: pip and pnpm run third-party install code.

2. **Sync secrets to SSM Parameter Store** — pushes GitHub Secrets as SSM SecureStrings before Terraform runs, so Lambda env vars reference stable SSM paths:
   - `/clouder/gemini/api_key`, `/clouder/openai/api_key`, `/clouder/tavily/api_key`, `/clouder/deepseek/api_key`
   - `/clouder/spotify/client_id`, `/clouder/spotify/client_secret`
   - `/clouder/ytmusic/client_id`, `/clouder/ytmusic/client_secret`, `/clouder/youtube/api_key`
   - `/clouder/beatport/username`, `/clouder/beatport/password` (auto-ingest; skipped while unset)

3. **Terraform apply, two phases** — first `-target=aws_lambda_function.db_migration` (so the migration Lambda carries the new Alembic revisions), then step 4, then the full apply. A single apply once updated the API before the schema and produced 2 min 40 s of HTTP 500s (2026-09-20). Both phases read `infra/prod.tfvars` and the job-level `TF_VAR_*` inputs; `pr.yml` passes the same ones to the PR plan.

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

6. **Frontend** — `scripts/deploy_frontend.sh publish` (built before AWS credentials existed; see [Frontend deploy](#frontend-deploy)).

7. **Smoke test** — `scripts/smoke.py` invokes each API Lambda's `live` alias with a request it answers before any I/O and fetches `/auth/login` (302 to Spotify), `/styles` without a token (401) and the site (200). Nothing is written and Aurora is not touched.

## How a change reaches production

Pull request → 8 required checks (the Terraform plan runs under the read-only role with the deploy's inputs, so it shows what will be applied) → merge → this pipeline: package and build, snapshot of the API aliases, SSM sync, migration Lambda, migrations, full apply, frontend, smoke test. Deploys never overlap.

## Rollback

**Automatic.** If any step after the snapshot fails — the smoke test included — the deploy points each API function's `live` alias back to the version it had before this deploy (`scripts/api_aliases.py restore`) and the job fails. A function whose alias did not exist yet (the first deploy that creates it) is left alone. The snapshot is printed in the job log; if the restore fails for one function it still restores the others and the step lists what failed. Cancelling a deploy by hand skips the automatic rollback (`failure()` is false on cancel) — restore from the printed snapshot.

**Manual.** `aws lambda update-alias --function-name clouder-prod-<fn> --name live --function-version <N>` (list versions with `aws lambda list-versions-by-function`), or `python scripts/api_aliases.py restore <saved snapshot>`.

**Drilled 2026-10-11** after the first deploy that published version 2 of the six API functions: `api_aliases.py restore` to version 1 took 3 s, `scripts/smoke.py` against version 1 passed 9/9, the restore back to version 2 took 2 s and the smoke passed again. Requests in flight finish on the version they started on; new ones see the switch at once.

**After a rollback** the next `terraform apply` moves the aliases forward again, so the fix is a revert PR or a new commit. Not rolled back: the frontend, the SQS workers, DB migrations (written to be backward compatible), SSM values.

## Delivery metrics

`python3 scripts/dora.py [--days 90]` (or `make dora`; needs a full clone and `gh` logged in) computes the four DORA metrics with the DORA 2023 definitions from this repository's own history: deployment frequency (successful `Deploy` runs on `main` per week), lead time for changes (a pull request's first commit → the end of the first successful deploy that started after its merge), change failure rate (failed / finished deploy runs, cancelled ones excluded) and failed-deployment recovery time (the first failed deploy of a streak → the next successful one). The README quotes its output.

## Frontend deploy

`scripts/deploy_frontend.sh` (no argument: both modes; the deploy runs `build` before AWS credentials exist and `publish` after the apply):

1. `build`: `pnpm install --frozen-lockfile && pnpm build` from `frontend/`
2. `publish`: reads `BUCKET` and `DIST_ID` from `terraform output` (`frontend_bucket`, `frontend_distribution_id`)
3. `aws s3 sync dist/ s3://$BUCKET/ --delete` for hashed assets with `Cache-Control: public,max-age=31536000,immutable`, excluding `index.html`
4. `aws s3 cp dist/index.html` with `Cache-Control: no-cache,no-store,must-revalidate`
5. `aws cloudfront create-invalidation --paths "/index.html"` — forces CDN to serve the fresh shell on next viewer request

CloudFront distribution and S3 bucket are managed in `infra/frontend.tf`.

## GitHub Secrets

Credentials — the vendor keys, the Beatport login and the deploy role — are scoped to the **`production` environment**. Terraform inputs that are not credentials are repo-root secrets, because the pull-request plan must see the same values as the deploy; Terraform marks the email and the budget `sensitive`, so no plan prints them. Workflows pass secrets to shell steps only through `env`.

| Secret | Scope | Used by |
|--------|-------|---------|
| `GEMINI_API_KEY`, `OPENAI_API_KEY`, `TAVILY_API_KEY`, `DEEPSEEK_API_KEY` | `production` environment | Synced to `/clouder/<vendor>/api_key` SSM (label/artist enrichment) |
| `SPOTIFY_CLIENT_ID` | `production` environment | Synced to `/clouder/spotify/client_id` SSM |
| `SPOTIFY_CLIENT_SECRET` | `production` environment | Synced to `/clouder/spotify/client_secret` SSM |
| `YTMUSIC_CLIENT_ID`, `YTMUSIC_CLIENT_SECRET` | `production` environment | Synced to `/clouder/ytmusic/client_{id,secret}` SSM (YouTube Music OAuth) |
| `YOUTUBE_API_KEY` | `production` environment | Synced to `/clouder/youtube/api_key` SSM (YouTube Data API, comments) |
| `BEATPORT_USERNAME` | `production` environment | Synced to `/clouder/beatport/username` SSM (auto-ingest login; step skipped while unset) |
| `BEATPORT_PASSWORD` | `production` environment | Synced to `/clouder/beatport/password` SSM (auto-ingest login; step skipped while unset) |
| `BEATPORT_CLIENT_ID` | Repo root | `TF_VAR_beatport_client_id` → auto-ingest Lambda env `BEATPORT_CLIENT_ID` (public OAuth id from the JS of `api.beatport.com/v4/docs/`; not in code). Unset: deploy passes, the login fails at step `client_id`. Change it and run Deploy by hand if Beatport rotates the id |
| `ALARM_EMAIL` | Repo root | `TF_VAR_alarm_email` → SNS topic `clouder-prod-alarms` with an email subscription; every CloudWatch alarm (and its OK) goes there. AWS first mails a confirmation link — nothing is delivered until it is clicked. Unset: no topic, alarms stay console-only |
| `BUDGET_MONTHLY_LIMIT` | Repo root | `TF_VAR_budget_monthly_limit` → AWS Budgets `clouder-prod-monthly` (a plain number of USD), emailing `ALARM_EMAIL` at 80 % of actual and 100 % of forecast spend. Unset (or no `ALARM_EMAIL`): no budget. The amount is a secret only because the repo is public |
| `AWS_GITHUB_ROLE_ARN` | `production` environment | Deploy role (OIDC), trusted only by this environment ([ADR-0028](../adr/0028-ci-roles.md)) |
| `AWS_PLAN_ROLE_ARN` | Repo root | Read-only plan role `clouder-prod-gha-plan` for PR checks (`terraform output gha_plan_role_arn`) |

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

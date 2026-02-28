# Beatport Weekly Releases Collector (MVP)

Serverless AWS collector that ingests Beatport releases for one `(style_id, iso_year, iso_week)` request and stores raw artifacts in S3.

## Architecture

- API Gateway HTTP API (`AWS_IAM`) with route `POST /collect_bp_releases`
- Lambda (`python3.12`) performs validation, Beatport fetch, and S3 writes
- S3 raw layer stores deterministic latest snapshot + append-only run archives
- Terraform manages infrastructure
- GitHub Actions deploys via OIDC + manual production approval

## Request Contract

Endpoint:

- `POST /collect_bp_releases`
- Auth: IAM SigV4

Request JSON:

```json
{
  "bp_token": "string",
  "style_id": 5,
  "iso_year": 2026,
  "iso_week": 9
}
```

Optional header:

- `x-correlation-id`

Response JSON includes:

- `run_id`, `correlation_id`, `api_request_id`, `lambda_request_id`
- `iso_year`, `iso_week`, `s3_object_key`, `item_count`, `duration_ms`

## S3 Layout

```text
raw/bp/releases/
  style_id=<style_id>/
    year=<YYYY>/
      week=<WW>/
        releases.json.gz
        meta.json
        runs/
          run_id=<uuid>.json.gz
```

## Week Boundaries

Week boundaries are stored as date-only strings in UTC context:

- `week_start`: Monday `YYYY-MM-DD`
- `week_end`: Sunday `YYYY-MM-DD`

## Local Run (manual)

Prereqs:

- AWS credentials allowed to invoke API (`execute-api:Invoke`)
- [`awscurl`](https://github.com/okigan/awscurl)
- short-lived Beatport `bp_token`

Command:

```bash
scripts/invoke_collect.sh \
  --api-url https://<api-id>.execute-api.us-east-1.amazonaws.com \
  --style-id 5 \
  --iso-year 2026 \
  --iso-week 9
```

## Terraform

```bash
cd infra
terraform init
terraform apply
```

### Remote state (recommended)

Use `backend.example.hcl` values with your own state bucket/table and run:

```bash
terraform init -backend-config=backend.hcl
```

## CI/CD

- PR workflow:
  - `terraform fmt -check`
  - `terraform validate`
  - `terraform plan`
  - `pytest`
- Main deploy workflow:
  - package Lambda ZIP
  - `terraform apply`
  - protected `production` environment approval

Both workflows use GitHub OIDC role `secrets.AWS_GITHUB_ROLE_ARN`.

## Security

- `bp_token` is request-only, never persisted and never logged
- Logs are structured and allowlist-based
- Errors are sanitized and include only trace ids

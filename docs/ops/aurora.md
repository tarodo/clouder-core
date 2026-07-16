# Aurora

CLOUDER uses Amazon Aurora PostgreSQL Serverless v2 (`engine_version = "16.11"`, single writer instance `db.serverless`). All Lambda runtime DB access goes through the RDS Data API (`src/collector/data_api.py`), not psycopg. psycopg is used only by the migration Lambda and local Alembic runs.

Cluster identifier: `clouder-prod-aurora` (from `infra/main.tf` `local.db_cluster_identifier` = `${local.name_prefix}-aurora`). Defined in `infra/rds.tf`. Verified live 2026-07-16 — the subnet group is `clouder-prod-aurora-subnets`, the master secret is RDS-managed (`rds!cluster-…`).

---

## Serverless v2 scaling

Controlled by three Terraform variables (`infra/variables.tf`):

| Variable | Default | Meaning |
|----------|---------|---------|
| `aurora_serverless_min_acu` | `0` | Minimum ACU. `0` enables auto-pause after idle timeout. `0.5` keeps the instance always warm. |
| `aurora_serverless_max_acu` | `2` | Maximum ACU — cap for burst scaling. |
| `aurora_auto_pause_seconds` | `300` | Seconds of inactivity before Aurora pauses. **Only effective when `min_acu = 0`.** Ignored when `min_acu >= 0.5`. |

Current production configuration: `min_acu=0`, `aurora_auto_pause_seconds=300`.

Trade-off: `min_acu=0` saves approximately **$43/month** compared to always-warm `min_acu=0.5`. The cost is a cold-start latency risk: the first request after 300 s of inactivity may time out through API Gateway's 29 s hard limit (see [Cold-start behaviour](#cold-start-behaviour) below).

To eliminate cold-start 503s at the cost of the above savings:

```hcl
# infra/terraform.tfvars (or -var flag)
aurora_serverless_min_acu = 0.5
```

See ADR-0014 for the cost/latency trade-off analysis.

---

## IAM authentication

`infra/rds.tf` sets `iam_database_authentication_enabled = true` on the cluster. However, the flag does not reliably persist via Terraform apply on Aurora Serverless v2 — a known AWS quirk.

**Verify the flag is actually set:**

```bash
aws rds describe-db-clusters \
  --db-cluster-identifier clouder-prod-aurora \
  --query 'DBClusters[0].IAMDatabaseAuthenticationEnabled'
```

If the result is `false` after `terraform apply`, force it manually:

```bash
aws rds modify-db-cluster \
  --db-cluster-identifier clouder-prod-aurora \
  --enable-iam-database-authentication \
  --apply-immediately
```

IAM auth is required by the migration Lambda in `iam` mode (`AURORA_AUTH_MODE=iam`). The migration Lambda calls `rds.generate_db_auth_token()` for the `clouder_migrator` role and uses the token as a password in the psycopg connection string. See `src/collector/migration_handler.py`.

See ADR-0005 for the decision to use IAM auth for the migration Lambda.

---

## Migrator role IAM grant

The `clouder_migrator` PostgreSQL role cannot self-grant the `rds_iam` permission — it must be granted by the master user (`clouder_admin`).

Run this **once** after cluster creation, as master user:

```sql
GRANT rds_iam TO clouder_migrator;
```

Execute via one of:

- **RDS Query Editor** in the AWS Console: connect using the `rds!cluster-...` Secrets Manager ARN, then run the `GRANT` statement.
- **Data API directly**:
  ```bash
  aws rds-data execute-statement \
    --resource-arn "$(cd infra && terraform output -raw aurora_cluster_arn)" \
    --secret-arn "$(cd infra && terraform output -raw aurora_secret_arn)" \
    --database clouder \
    --sql "GRANT rds_iam TO clouder_migrator;"
  ```

This step is not managed by Terraform and must be re-run if the cluster is rebuilt from scratch.

---

## Master RDS secret retention

The auto-generated secret `rds!cluster-...` (managed by Secrets Manager via `manage_master_user_password = true` in `infra/rds.tf`) is **required at runtime** by all non-migration Lambdas. They pass it to the RDS Data API (`rds-data:ExecuteStatement`) as the `secretArn` parameter in every call.

**Do NOT delete this secret after an IAM auth cutover.** The IAM cutover only changes how the migration Lambda authenticates — the runtime Lambdas (collector, canonicalization worker, search workers, vendor match) always use the Data API with the master secret.

Retrieve the current secret ARN:

```bash
cd infra && terraform output -raw aurora_secret_arn
```

---

## Cold-start behaviour

When `aurora_serverless_min_acu = 0` and no requests have arrived in the past 300 s, Aurora enters a paused state. The first inbound request triggers a resume that typically takes 15–25 s.

API Gateway has a **hard 29 s timeout**. A request that arrives during an Aurora cold start may exceed this limit. The response received by the client is:

```json
{"message": "Service Unavailable"}
```

This envelope is API Gateway's format (capital S, capital U) — it is **not** CLOUDER's error envelope (`{"error_code": "...", "message": "...", "correlation_id": "..."}`).

The Lambda usually completes the work in the background even after API GW times out. Retry the same request after a few seconds.

Distinguishing Aurora cold-start from other 503 causes:

- Aurora cold-start: happens on the first request after an idle period. The Lambda's CloudWatch log group shows no log lines for the request (Lambda was not invoked at all, or Aurora connection timed out before handler body ran).
- API GW timeout on a long Beatport crawl: Lambda log shows `request_received` but no `collection_completed`.

**Fix**: set `aurora_serverless_min_acu = 0.5` in `infra/terraform.tfvars` if first-request latency matters more than the ~$43/month cost.

# ADR-0005: RDS IAM auth for migration Lambda
Status: Accepted
Date: 2026-05-17

## Context

Schema migrations in CLOUDER are run by a dedicated Lambda (`migration_handler.py`) invoked post-deploy. This Lambda uses `psycopg` + Alembic to apply pending migrations to Aurora. It needs a DB credential.

The simplest path is password auth using the master RDS secret (`rds!cluster-...` managed by Secrets Manager). The master secret is already available for the runtime Lambdas (they pass it to the Data API). Reusing it for migrations would work, but it couples the migration Lambda to a secret that was designed for the AWS Data API path, not for direct psycopg connections.

RDS IAM database authentication is a better fit for the migration Lambda. With IAM auth, the Lambda generates a short-lived (15-minute) auth token via `boto3.client("rds").generate_db_auth_token` using the Lambda's IAM execution role. No secret is stored or rotated manually — the token is derived from the IAM identity. This follows the principle of least privilege: the migrator role (`clouder_migrator`) has only DDL access, and its credential is ephemeral.

Two constraints emerged during implementation. First, the `IAMDatabaseAuthenticationEnabled` flag on Aurora Serverless v2 does not reliably persist through `terraform apply` — it must sometimes be forced via `aws rds modify-db-cluster --apply-immediately`. Second, the `rds_iam` PostgreSQL privilege cannot be self-granted by `clouder_migrator`; it must be granted by the master user (`clouder_admin`) once after cluster creation.

The master RDS secret is retained after the IAM cutover because all runtime Lambdas still use it via the Data API path (`rds-data:ExecuteStatement` requires a `secretArn`).

## Decision

The migration Lambda authenticates to Aurora using an RDS IAM token (`AURORA_AUTH_MODE=iam`, `AURORA_DB_USER=clouder_migrator`). Runtime Lambdas continue to use the master secret via the Data API; the master secret is retained, not deleted, after the migration Lambda cutover.

## Consequences

- `migration_handler.py` supports two auth modes controlled by `AURORA_AUTH_MODE`: `password` (uses `AURORA_SECRET_ARN`) and `iam` (uses `AURORA_DB_USER` + IAM token generation). The default is `password` to avoid breaking existing deployments.
- After enabling IAM auth, the `rds_iam` privilege must be granted to `clouder_migrator` by the master user. This is a one-time manual step not managed by Terraform.
- The IAM auth flag on the Aurora cluster may silently revert after `terraform apply`. Verify with `aws rds describe-db-clusters --query 'DBClusters[0].IAMDatabaseAuthenticationEnabled'` after each apply and force-enable via CLI if needed.
- The master secret (`rds!cluster-...`) must not be deleted. Deleting it would break all runtime Lambda DB access even though the migration Lambda no longer uses it.
- Rotating the master secret in Secrets Manager is handled automatically by AWS rotation. The `DataAPIClient` in runtime Lambdas picks up the new secret on the next invocation (the Data API resolves the secret ARN at call time, not at container init).

**Cross-references:** `../ops/aurora.md`, `../data/migrations.md`.

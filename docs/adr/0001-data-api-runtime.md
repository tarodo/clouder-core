# ADR-0001: RDS Data API at Lambda runtime (vs psycopg)
Status: Accepted
Date: 2026-05-17

## Context

CLOUDER's Lambda functions need to read from and write to an Aurora PostgreSQL database. The canonical Python PostgreSQL driver, `psycopg`, opens a long-lived TCP connection and requires a native C extension compiled against the target platform. This creates two problems in the Lambda + Aurora Serverless v2 context.

First, Aurora Serverless v2 with `min_acu=0` pauses the cluster after 300 seconds of inactivity. On the first inbound request, the cluster resumes — a process that takes 15–25 seconds. `psycopg` cannot survive this resume cycle; a connection established before the pause would be killed, and re-establishing it inside a Lambda handler that has a 29-second API Gateway deadline is fragile.

Second, `psycopg` is not available as a standard Lambda layer. Including it requires either a native build layer (compiled for Amazon Linux 2) or a Lambda container image — both add packaging complexity and cold-start weight.

The alternative is the **AWS RDS Data API** (`rds-data:ExecuteStatement`), an HTTP-based, connection-less interface to Aurora. Every call is stateless: the caller passes the cluster ARN and a Secrets Manager ARN; Aurora opens the connection, executes the SQL, and closes it. There is no persistent socket to manage. The trade-off is higher per-call overhead (~100–200 ms) and a 1 MB payload limit per statement — acceptable for this workload.

`psycopg` remains the right tool for Alembic schema migrations run locally and from the migration Lambda, which execute in a controlled, non-latency-sensitive context.

## Decision

Lambda runtime code uses the RDS Data API exclusively. `psycopg` is permitted only for the local `alembic` workflow, never inside `src/collector/` handler paths. The Lambda runtime never imports `psycopg`.

## Consequences

- All runtime DB access goes through `src/collector/data_api.py:DataAPIClient`. The wrapper handles type mapping, retry with exponential backoff, and the `transaction()` context manager.
- `psycopg` is in `requirements-dev.txt` (for local Alembic) but intentionally absent from `requirements-lambda.txt`. A transitive import of `psycopg` inside any handler module causes a `ModuleNotFoundError` Lambda cold-start failure.
- The 1 MB Data API payload limit means bulk upserts must be chunked. `Canonicalizer` processes tracks in batches of 200.
- `commit_transaction` and `rollback_transaction` use a narrower retry policy (`retry_data_api_pre_execution`) than plain `execute` calls, because commit is not idempotent at the Data API protocol level. See `../backend/data-api.md` for the full retry policy rationale.
- `find_identity` inside a `repository.transaction()` block must always receive `transaction_id`; without it the read goes to a separate Data API connection and misses in-flight writes.

**Cross-references:** `../backend/data-api.md`, `../backend/gotchas.md`.

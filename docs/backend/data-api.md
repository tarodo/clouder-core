# Data API Client Reference

## Why Data API at Runtime

Lambda functions cannot use `psycopg` (a native PostgreSQL driver) because:

- `psycopg` requires a long-lived TCP connection, which conflicts with the Aurora Serverless v2 pause/resume lifecycle and the ephemeral nature of Lambda execution.
- `psycopg` is not in `requirements-lambda.txt`; including it would require a native build layer and complicates cold-start size.

Instead, all runtime DB access goes through the **AWS RDS Data API** (`rds-data:ExecuteStatement`), which is an HTTP-based, connection-less interface to Aurora. The application-layer wrapper is `src/collector/data_api.py:DataAPIClient`.

`psycopg` is used **only** in the Migration Lambda and local Alembic runs. Import it inside migration-only code paths; importing it in any handler module breaks Lambda cold-start.

See also: [ADR-0001](../adr/0001-data-api-runtime.md), [handlers.md](handlers.md#migration-lambda-collectormigration_handler).

---

## `DataAPIClient` Interface

**Source:** `src/collector/data_api.py:DataAPIClient`

Constructor parameters:

| Parameter | Type | Description |
|---|---|---|
| `client` | `Any` | `boto3.client("rds-data")` |
| `resource_arn` | `str` | Aurora cluster ARN (`AURORA_CLUSTER_ARN`) |
| `secret_arn` | `str` | Secrets Manager ARN with DB credentials (`AURORA_SECRET_ARN`) |
| `database` | `str` | Database name (`AURORA_DATABASE`, default `postgres`) |

### Methods

#### `execute(sql, params=None, transaction_id=None) -> list[dict]`

Single SQL statement. `params` is `Mapping[str, Any]`; each value is type-hinted and serialized according to its Python type:

| Python type | Data API type hint | Serialization |
|---|---|---|
| `datetime` | `TIMESTAMP` | UTC, stripped timezone, `%Y-%m-%d %H:%M:%S.%f` |
| `date` | `DATE` | ISO format string |
| `dict` / `list` | `JSON` | `json.dumps` |
| `Decimal` | `DECIMAL` | string representation |
| `bool` | — | `booleanValue` |
| `int` | — | `longValue` |
| `float` | — | `doubleValue` |
| `None` | — | `isNull: true` |
| anything else | — | `str(value)` |

Returns a `list[dict]` where each dict maps column name → Python value (reconstructed from Data API field types via `_from_field`).

#### `batch_execute(sql, parameter_sets, transaction_id=None) -> None`

Calls `rds-data:BatchExecuteStatement`. Useful for bulk inserts/upserts. Does not return rows.

#### `begin_transaction() -> str`

Returns a `transactionId` string from `rds-data:BeginTransaction`.

#### `commit_transaction(transaction_id) -> None`

Commits the transaction. Decorated with `@retry_data_api_pre_execution`.

#### `rollback_transaction(transaction_id) -> None`

Rolls back the transaction. Decorated with `@retry_data_api_pre_execution`.

#### `transaction() -> contextmanager[str]`

Context manager wrapping begin/commit/rollback:

```python
with db.transaction() as txn_id:
    db.execute("INSERT ...", params, transaction_id=txn_id)
    # commit on exit, rollback on exception
```

The `yield` value is the `transaction_id` string; pass it to `execute` calls inside the block.

#### Factory

```python
from collector.data_api import create_default_data_api_client

client = create_default_data_api_client(
    resource_arn=resource_arn,
    secret_arn=secret_arn,
    database=database,
)
```

---

## Retry Policies

**Source:** `src/collector/data_api_retry.py`

Two decorators are defined. Both use exponential backoff with full jitter (AWS recommendation) — `sleep = uniform(0, min(max_delay, base_delay * 2^(attempt-1)))` — and log each retry attempt as `data_api_retry`.

Default parameters: `max_attempts=5`, `base_delay=1.0s`, `max_delay=30.0s`.

### `retry_data_api`

Applied to: `execute`, `batch_execute`, `begin_transaction`.

Retries on any code in `TRANSIENT_ERROR_CODES`:

```
DatabaseResumingException
StatementTimeoutException
InternalServerErrorException
ServiceUnavailableError
ThrottlingException
```

**Idempotency contract:** `StatementTimeoutException` and `InternalServerErrorException` may fire after the server has partially applied the statement. Callers must ensure retried operations are idempotent — either wrap in an explicit transaction (so a retry replays within the same transactional boundary) or use `ON CONFLICT DO UPDATE` / `INSERT ... ON CONFLICT IGNORE` semantics.

### `retry_data_api_pre_execution`

Applied to: `commit_transaction`, `rollback_transaction`.

Retries only on `PRE_EXECUTION_ERROR_CODES`:

```
DatabaseResumingException
ServiceUnavailableError
ThrottlingException
```

These codes reliably indicate the request never reached the Aurora engine. `StatementTimeoutException` and `InternalServerErrorException` are intentionally excluded: if `commit_transaction` already succeeded server-side and we retry it, the transaction would be committed twice (or the second attempt would see an unknown transaction ID). The narrower retry set avoids this corruption.

### Why the split matters

Commit and rollback are not idempotent at the protocol level. Using the wide `retry_data_api` policy on `commit_transaction` risks committing a transaction that was already committed on the first attempt (which Aurora would treat as an error, hiding the fact that the commit succeeded). The narrow `retry_data_api_pre_execution` policy only retries when Aurora is provably not ready — the statement never ran.

---

## Transactions and `find_identity`

When using `db.transaction() as txn_id`, all `execute` calls inside the block must pass `transaction_id=txn_id`. Failing to do so causes the statement to execute outside the transaction, which means it cannot see uncommitted writes made within the transaction.

This is especially relevant for `find_identity` (called inside `repository.transaction()` blocks to look up canonical entity IDs for newly inserted rows). If `transaction_id` is not forwarded, the lookup will miss the in-flight `INSERT` and return `None`, causing a spurious "entity not found" error or duplicate insert.

Pattern:

```python
with repository.transaction() as txn_id:
    repository.insert_entity(..., transaction_id=txn_id)
    entity_id = repository.find_identity(..., transaction_id=txn_id)  # must pass txn_id
```

---

## Secrets Caching

**Source:** `src/collector/settings.py:_fetch_secret_string`

The function is decorated with `@functools.lru_cache(maxsize=32)`. The first call for a given `secret_arn` fetches from AWS Secrets Manager and caches the result for the lifetime of the Lambda container.

Consequence: if a Perplexity or Spotify API key is rotated in Secrets Manager, the running container continues using the old value until it is recycled (Lambda updates a function's env var, cold-starts, or the platform recycles the sandbox). To force a pick-up of a rotated key:

1. Update the secret value in Secrets Manager.
2. Force a container recycle: deploy a no-op config change to the Lambda function, or wait for the platform to recycle the container naturally (typically within 15 minutes of last invocation).

SSM parameters follow the same pattern via `src/collector/secrets.py:_fetch_ssm_parameter` (also `lru_cache`).

---

## Pitfalls

### Correlated `EXISTS` after `GROUP BY`

Postgres rejects correlated subqueries that reference a column not in the `GROUP BY` list, even when the correlation is logically equivalent to a grouped column through a JOIN. Example that fails:

```sql
-- WRONG: ct.track_id is not in GROUP BY
SELECT t.id, COUNT(pt.id)
FROM clouder_tracks t
JOIN clouder_track_artists ct ON ct.track_id = t.id
GROUP BY t.id
HAVING EXISTS (
    SELECT 1 FROM playlist_tracks pt WHERE pt.track_id = ct.track_id  -- SQLState 42803
);
```

Postgres does not infer that `ct.track_id = t.id` via the JOIN, so `ct.track_id` is "ungrouped". Fix by correlating on the column you actually grouped on:

```sql
-- CORRECT: correlate via t.id, which IS in GROUP BY
HAVING EXISTS (
    SELECT 1 FROM playlist_tracks pt WHERE pt.track_id = t.id
)
```

`FakeDataAPI` (used in unit tests) does string-match SQL fragments and will not catch this error. It surfaces only in integration tests against real PostgreSQL or in production.

### Idempotency on non-idempotent writes

The `retry_data_api` decorator may retry a write after `StatementTimeoutException` or `InternalServerErrorException`. If the write is not idempotent (e.g., a plain `INSERT` without `ON CONFLICT`), the retry may produce a duplicate row or a unique constraint violation. Mitigations:

- Use `INSERT ... ON CONFLICT DO UPDATE` (upsert).
- Use `INSERT ... ON CONFLICT DO NOTHING` when duplicates are acceptable.
- Wrap in an explicit transaction: a timeout inside a transaction causes rollback, so the retry replays cleanly.

Non-idempotent writes outside transactions are a correctness risk when Aurora Serverless is resuming or under transient load.

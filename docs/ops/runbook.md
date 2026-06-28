# Runbook

Incident playbooks for common CLOUDER operational issues. Each entry follows: **Symptom / Diagnosis / Fix**.

---

## Cold-start 503

**Symptom**

Client receives:

```json
{"message": "Service Unavailable"}
```

This is the API Gateway envelope (capital S, capital U). It is not CLOUDER's error envelope (`{"error_code": "...", "message": "...", "correlation_id": "..."}`). HTTP status is 503.

**Diagnosis**

Two root causes produce this symptom:

1. **Aurora cold-start** — `aurora_serverless_min_acu = 0` (current default). After 300 s of inactivity Aurora pauses. The first request triggers a resume (15–25 s) which exceeds API GW's 29 s hard timeout. The Lambda usually completes the work in background.

   Confirm: check the Lambda's CloudWatch log group. If there are no log entries for the failing request (or `request_received` but no `collection_completed`), Aurora was the bottleneck.

2. **Long Beatport crawl** — a large `POST /collect_bp_releases` (many pages) exceeds 29 s even with a warm Aurora. The Lambda logs will show `beatport_request` / `beatport_response` events but no `collection_completed`.

**Fix**

- **Immediate**: retry the same request after 5–10 s. Aurora will be warm for subsequent requests.
- **Persistent cold-start elimination**: set `aurora_serverless_min_acu = 0.5` in `infra/terraform.tfvars`, then `terraform apply`. Cost: ~$43/month more than `min_acu=0`. See `docs/ops/aurora.md` and ADR-0014.

---

## `processing_status=FAILED_TO_QUEUE`

**Symptom**

A run completes but tracks are not appearing in the canonical DB. Querying the run record shows `processing_status = FAILED_TO_QUEUE`.

**Diagnosis**

Check `processing_outcome` and `processing_reason` on the affected records:

| `processing_outcome` | `processing_reason` | Meaning |
|---------------------|---------------------|---------|
| `DISABLED` | `config_disabled` | `CANONICALIZATION_ENABLED=false` on the API Lambda — routing is turned off, no queue call was attempted |
| `ENQUEUE_FAILED` | `enqueue_exception` | The SQS `SendMessage` call failed; check Lambda logs for the exception |

**Fix**

- `config_disabled`: confirm `CANONICALIZATION_ENABLED=true` is set on `beatport-prod-collector-api`. In prod this is set via Terraform (`-var="canonicalization_enabled=true"`). Verify:
  ```bash
  aws lambda get-function-configuration \
    --function-name beatport-prod-collector-api \
    --query 'Environment.Variables.CANONICALIZATION_ENABLED'
  ```

- `enqueue_exception`: check `CANONICALIZATION_QUEUE_URL` is correct and the Lambda execution role has `sqs:SendMessage` on the queue. Review the Lambda CloudWatch log for the `enqueue_exception` event — it includes the SQS error detail.

---

## DLQ messages

**Symptom**

CloudWatch alarm fires on DLQ depth (`beatport-prod-canonicalization-dlq`, `beatport-prod-ai-search-dlq`, `beatport-prod-spotify-search-dlq`, or `beatport-prod-vendor-match-dlq`).

**Diagnosis**

Common causes:

| Queue | Common cause |
|-------|-------------|
| `ai-search-dlq` | Perplexity API 429 (rate limit) cascade. `ai_search_worker` reserved concurrency is uncapped when `enable_lambda_reserved_concurrency=false` (default), so bursts can hit the Perplexity 5 RPS limit. |
| `spotify-search-dlq` | Spotify Client Credentials rate limit; also fires if `SPOTIFY_METADATA_FALLBACK_ENABLED=true` and a large batch times out. |
| `vendor-match-dlq` | Malformed S3 key or missing `clouder_track_id` in the SQS message body. |
| `canonicalization-dlq` | Unhandled exception in `canonicalization_worker`; often a schema mismatch after a Beatport API change. |

**Inspect messages:**

```bash
# Get the DLQ URL
aws sqs get-queue-url --queue-name beatport-prod-canonicalization-dlq

# Receive up to 10 messages (non-destructive, visibility timeout 30s)
aws sqs receive-message \
  --queue-url <DLQ_URL> \
  --max-number-of-messages 10 \
  --visibility-timeout 30 \
  --attribute-names All \
  --message-attribute-names All
```

**Manual replay:**

After fixing the underlying issue, replay from DLQ to the main queue using the SQS console "Start DLQ redrive" feature, or with the AWS CLI:

```bash
aws sqs start-message-move-task \
  --source-arn <DLQ_ARN> \
  --destination-arn <MAIN_QUEUE_ARN>
```

Retrieve ARNs:

```bash
aws sqs get-queue-attributes \
  --queue-url <QUEUE_URL> \
  --attribute-names QueueArn
```

---

## Refresh-cookie replay revocation

**Symptom**

A user (or dev session) reuses a refresh cookie (e.g. replays a `/auth/refresh` request). The server detects cookie replay and revokes **all** of that user's sessions. Subsequent requests return 401 even with a previously valid access token.

See ADR-0015 for the design rationale.

**Diagnosis**

Refresh-cookie replay detection is intentional and unforgiving — reusing the same refresh cookie indicates a potential token theft scenario, so all sessions are invalidated.

**Fix**

The only recovery path is a fresh login:

1. Clear all cookies in the browser (or `document.cookie` reset in dev tools).
2. Navigate to `/auth/login` and complete the Spotify OAuth flow.

During development, avoid replaying raw HTTP requests that include the `refresh_token` cookie. Use browser-based navigation instead of curl/Postman for session-sensitive flows.

---

## Lambda reserved concurrency trip

**Symptom**

`terraform apply` fails with:

```
InvalidParameterValueException: The requested ReservedConcurrentExecutions ... will leave account-level UnreservedConcurrentExecution below the minimum threshold of 10.
```

Or workers behave as if unthrottled (Perplexity/Spotify 429s flowing back through SQS retry → DLQ) despite `enable_lambda_reserved_concurrency=true` being set.

**Diagnosis**

AWS new accounts start with a `ConcurrentExecutions` quota of 10. The reserved concurrency sum for CLOUDER workers is:

| Lambda | Reserved |
|--------|---------|
| `ai_search_worker` | 2 |
| `spotify_search_worker` | 3 |
| `vendor_match_worker` | 2 |
| **Total** | **7** |

AWS requires at least 10 unreserved concurrent executions in the account. With a quota of 10, reserving 7 leaves only 3 unreserved — below the floor — triggering `InvalidParameterValueException`.

Controlled by `var.enable_lambda_reserved_concurrency` in `infra/variables.tf` (default `false`).

**Fix**

1. Request a quota increase via AWS Service Quotas:
   - Service: Lambda
   - Quota: `Concurrent executions` (quota code `L-B99A9384`)
   - Target: 17 or higher (10 unreserved floor + 7 reserved)

2. After the quota is approved, set the Terraform variable:
   ```hcl
   # infra/terraform.tfvars
   enable_lambda_reserved_concurrency = true
   ```

3. Run `terraform apply`.

Until the quota is raised, leave `enable_lambda_reserved_concurrency = false`. Workers run unreserved and Perplexity/Spotify 429s flow to DLQ for retry.

## Analytics first run (bootstrap)

**Symptom**

Right after the first deploy of the analytics stack, `/admin/analytics` dashboards are empty and the `analytics` Lambda's Athena queries error with `TABLE_NOT_FOUND` for `gold.*`.

**Diagnosis**

`terraform apply` creates only the **bronze** Glue tables (`bronze_events`, `bronze_catalog_export`, `bronze_ops`) for Firehose + the export Lambdas. The **silver** and **gold** (star-schema) tables are created by **dbt on its first run**, executed by the `beatport-prod-analytics-daily` Step Functions state machine. The state machine runs on the EventBridge daily schedule — so until the first scheduled fire (or a manual trigger), `gold.*` does not exist and the dashboards have nothing to read. Telemetry must also be flowing first (`VITE_TELEMETRY_ENABLED=true` in the frontend build, default-on in `scripts/deploy_frontend.sh`) so `bronze/events/` is non-empty.

**Fix — trigger the pipeline once after the first telemetry has landed**

```bash
SFN_ARN=$(cd infra && terraform output -raw analytics_state_machine_arn)
aws stepfunctions start-execution --state-machine-arn "$SFN_ARN"

# Watch it: [catalog_export ‖ ops_log_export] → dbt_run → dbt source freshness → dbt_test
aws stepfunctions describe-execution --execution-arn "<arn from start-execution>" \
  --query 'status'   # RUNNING → SUCCEEDED
```

On `SUCCEEDED`, `gold.*` exists and the dashboards populate. Thereafter the daily EventBridge schedule keeps them fresh; if `dbt_test`/`dbt source freshness` fails, the DAG routes to `NotifyFailure` and the prior day's gold partitions are kept (no stale publish).

**Smoke test the ingest end-to-end** (one-shot, after deploy):

```bash
# POST a telemetry batch with a valid bearer, then confirm it lands:
aws s3 ls "s3://beatport-prod-analytics-lake/bronze/events/" --recursive | head
# Athena (after a partition shows up):
#   SELECT count(*) FROM clouder_analytics.bronze_events;  -- > 0
```

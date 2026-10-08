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
- **Persistent cold-start elimination**: set `aurora_serverless_min_acu = 0.5` in `infra/terraform.tfvars`, then `terraform apply`. Cost: an always-warm 0.5 ACU instead of nothing while idle. See `docs/ops/aurora.md` and ADR-0014.

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

- `config_disabled`: confirm `CANONICALIZATION_ENABLED=true` is set on `clouder-prod-collector-api`. In prod this is set via Terraform (`-var="canonicalization_enabled=true"`). Verify:
  ```bash
  aws lambda get-function-configuration \
    --function-name clouder-prod-collector-api \
    --query 'Environment.Variables.CANONICALIZATION_ENABLED'
  ```

- `enqueue_exception`: check `CANONICALIZATION_QUEUE_URL` is correct and the Lambda execution role has `sqs:SendMessage` on the queue. Review the Lambda CloudWatch log for the `enqueue_exception` event — it includes the SQS error detail.

---

## DLQ messages

**Symptom**

CloudWatch alarm fires on DLQ depth. The live DLQs are `clouder-prod-canonicalization-dlq`, `clouder-prod-spotify-search-dlq`, `clouder-prod-vendor-match-dlq`, `clouder-prod-label-enrichment-dlq`, `clouder-prod-artist-enrichment-dlq`, `clouder-prod-auto-enrich-dispatch-dlq`, and `clouder-prod-comments-collect-dlq`.

**Diagnosis**

Common causes:

| Queue | Common cause |
|-------|-------------|
| `label-enrichment-dlq` / `artist-enrichment-dlq` | Upstream AI/search vendor 429 or timeout during enrichment. See [ADR-0016](../adr/0016-label-enrichment.md), [ADR-0017](../adr/0017-artist-enrichment.md). |
| `spotify-search-dlq` | Spotify Client Credentials rate limit; also fires if `SPOTIFY_METADATA_FALLBACK_ENABLED=true` and a large batch times out. |
| `vendor-match-dlq` | Malformed S3 key or missing `clouder_track_id` in the SQS message body. |
| `canonicalization-dlq` | Unhandled exception in `canonicalization_worker`; often a schema mismatch after a Beatport API change. |

**Inspect messages:**

```bash
# Get the DLQ URL
aws sqs get-queue-url --queue-name clouder-prod-canonicalization-dlq

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

Or workers behave as if unthrottled (vendor 429s flowing back through SQS retry → DLQ) despite `enable_lambda_reserved_concurrency=true` being set.

**Diagnosis**

AWS new accounts start with a `ConcurrentExecutions` quota of 10. The reserved concurrency sum for CLOUDER workers is:

| Lambda | Reserved |
|--------|---------|
| `spotify_search_worker` | 3 |
| `vendor_match_worker` | 2 |
| `label_enricher_worker` | 10 |
| `artist_enricher_worker` | 10 |
| **Total** | **25** |

AWS requires at least 10 unreserved concurrent executions in the account. With a quota of 10, reserving 25 is impossible — below the floor — triggering `InvalidParameterValueException`.

Controlled by `var.enable_lambda_reserved_concurrency` in `infra/variables.tf` (default `false`).

**Fix**

1. Request a quota increase via AWS Service Quotas:
   - Service: Lambda
   - Quota: `Concurrent executions` (quota code `L-B99A9384`)
   - Target: 35 or higher (10 unreserved floor + 25 reserved)

2. After the quota is approved, set the Terraform variable:
   ```hcl
   # infra/terraform.tfvars
   enable_lambda_reserved_concurrency = true
   ```

3. Run `terraform apply`.

Until the quota is raised, leave `enable_lambda_reserved_concurrency = false`. Workers run unreserved and vendor 429s flow to DLQ for retry.

## Nightly dbt build failed

**Symptom**

Alarm `clouder-prod-transform-failed`, or the `clouder-prod-transform` execution ended `FAILED`.

**Diagnosis**

`aws logs tail /aws/codebuild/clouder-prod-dbt --since 12h` — dbt names the failing model or test. A failed data test means bronze delivered something a model's contract rejects; a failed model is usually Athena SQL or permissions.

**Fix**

Fix forward on `main`, then start the state machine by hand (`aws stepfunctions start-execution --state-machine-arn $(cd infra && terraform output -raw transform_state_machine_arn)`). The cards read the last three days from bronze, so two failed nights lose nothing; after a third, days drop until the next successful build catches up. To stop reading silver at once, clear `silver_events_table` and deploy. See [`docs/data/lakehouse.md`](../data/lakehouse.md).

---

## Contract drift or quarantined records

**Symptom**

Alarm `clouder-prod-contract-drift` or `clouder-prod-quarantined-records`.

**Diagnosis**

`aws logs filter-log-events --log-group-name /aws/lambda/clouder-prod-canonicalization-worker --filter-pattern '{ $.message = "contract_drift" }'` names the drifting fields; quarantined records are in `s3://<raw bucket>/raw/bp/releases/_quarantine/run_id=<run_id>/records.json.gz` with their reasons.

**Fix**

A new upstream field that is fine: add it to `FIELDS` in `src/collector/contracts.py`. A missing, re-typed or emptied field: check what canonicalization reads before acknowledging. Quarantined records: fix the cause upstream, then re-ingest the week (a replay re-reads the same raw object, so it only helps after the contract itself changed). Acknowledging a new field: add it to `FIELDS` and to `OPTIONAL` (older raw objects lack it). See [`docs/data/contracts.md`](../data/contracts.md).

---

## 429 Too Many Requests from the API

**Symptom**

The SPA or a script gets HTTP 429 from API Gateway.

**Diagnosis**

The `$default` stage limits every route to 100 requests/s with a burst of 200 (`infra/api_gateway.tf`). Count 429s per route in the access log: `aws logs filter-log-events --log-group-name /aws/apigateway/clouder-prod-collector-api --filter-pattern '{ $.status = "429" }'`.

**Fix**

A client loop or a script is the usual cause — fix it. If real traffic outgrew the limit, raise `throttling_rate_limit` / `throttling_burst_limit` and deploy.

---

## Telemetry delivery stalled

**Symptom**

Alarm `clouder-prod-telemetry-delivery-freshness`: Firehose records waited over 15 minutes for S3 delivery (the buffer is 300 s).

**Diagnosis**

`aws firehose describe-delivery-stream --delivery-stream-name clouder-prod-telemetry` (look at `Destinations[0].ExtendedS3DestinationDescription` and recent errors), and the Firehose error log group. Usual causes: the delivery role lost S3/Glue access, or the Glue table schema no longer matches the Parquet conversion.

**Fix**

Restore the permission or the schema through Terraform; Firehose retries for 24 h, so data buffered meanwhile is delivered once the cause is gone.

---

## Auto-ingest run failed

**Symptom**

Alarm `clouder-prod-auto-ingest-failed`, or the admin's Auto-ingest panel shows a failed last run.

**Diagnosis**

`aws logs filter-log-events --log-group-name /aws/lambda/clouder-prod-auto-ingest --filter-pattern '{ $.message = "auto_ingest_run_failed" }'`. A login failure carries `phase` (the step) and `status_code`; a run whose every period failed carries `count` / `runs_failed`, and the per-pair errors are in the panel's last run. Check the login alone with the `auth_check` invoke in [`docs/data/auto-ingest.md`](../data/auto-ingest.md#operating-it).

**Fix**

- `credentials`: the SSM parameters are missing or unreadable — add the GitHub secrets `BEATPORT_USERNAME` / `BEATPORT_PASSWORD` (environment `production`) and run the Deploy workflow by hand.
- `client_id` (`missing`): the GitHub secret `BEATPORT_CLIENT_ID` is unset — add it (current id: the JS of `https://api.beatport.com/v4/docs/`) and run Deploy by hand.
- `login` 401/403: the password changed — update the GitHub secret, redeploy.
- `authorize` / `token`: first suspect a rotated client id — take the current one from the JS of `https://api.beatport.com/v4/docs/`, set the GitHub secret `BEATPORT_CLIENT_ID`, run Deploy by hand, rerun `auth_check`. If that does not help, Beatport changed its login flow — disable auto-ingest in the admin; manual ingest with a pasted token still works.
- `catalog_auth`: login worked but the catalog API rejected the token (401/403) — check the account's catalog access; no pair was charged.
- Every period failed with the same Beatport error: an upstream outage; the next planned run retries.

---

## Auto-ingest stuck pairs

**Symptom**

The Auto-ingest panel lists a style × week under "Stuck": its last three automatic attempts within a week failed (the fetch, or the canonicalization of the run it created), so the planner skips it.

**Fix**

Read the listed error (`canonicalization failed` points at the worker logs for that run). Ingest the week by hand from the coverage matrix; once the run completes, the pair leaves the list. Otherwise it is retried automatically once its attempts are a week old.

---

## Disable auto-ingest

Admin → Coverage → Auto-ingest: switch off and Save — pending runs are deleted and nothing is planned. Emergency stop without the admin (reset by the next deploy): `aws lambda put-function-concurrency --function-name clouder-prod-auto-ingest --reserved-concurrent-executions 0`.

---

## Reprocess raw data (backfill)

**When**

- A canonicalization change must reach tracks already in the catalog.
- A run is stuck in `FAILED` or `RAW_SAVED` and is still the latest run for its raw object (a later re-ingest of the same style and week overwrote the object otherwise; such a run is superseded and is closed by hand).

**Fix**

Start the `clouder-prod-backfill` state machine with a dry run (`--input '{}'`, optionally `style_ids`, `since`, `until`), read the `summary` in the execution output (a failed execution has none; its cause lists the failed run ids), then run it again with `"dry_run": false`. Commands and inputs: [`backfill.md`](backfill.md). No Beatport token is needed.

---

## Running a one-off script against prod

**When**

Backfills and repair scripts under `scripts/` (e.g. `backfill_spotify_import_artists.py`) run from a laptop against prod. They talk to Aurora through the Data API, so they need the same environment the Lambdas get — but nothing sets it locally, and there is no committed `.env`.

**Get the env from a deployed Lambda** (ground truth — whatever the Lambda reads is what the settings classes expect):

```bash
aws lambda get-function-configuration --function-name clouder-prod-curation \
  --query "Environment.Variables" --output json
```

The values a DB/queue/Spotify script typically needs:

```bash
export PYTHONPATH=src
export AURORA_CLUSTER_ARN='arn:aws:rds:us-east-1:<acct>:cluster:clouder-prod-aurora'
export AURORA_SECRET_ARN='arn:aws:secretsmanager:us-east-1:<acct>:secret:rds!cluster-...'
export AURORA_DATABASE='clouder'
export VENDOR_MATCH_QUEUE_URL='https://sqs.us-east-1.amazonaws.com/<acct>/clouder-prod-vendor-match'
# Spotify client-credentials come from SSM, by parameter NAME:
export SPOTIFY_CLIENT_ID_SSM_PARAMETER='/clouder/spotify/client_id'
export SPOTIFY_CLIENT_SECRET_SSM_PARAMETER='/clouder/spotify/client_secret'
export RAW_BUCKET_NAME='beatport-prod-raw-<acct>'   # required by SpotifyWorkerSettings even when unused
```

**Rules**

- Use `.venv/bin/python`, not `python3` — these scripts import project dependencies. `PYTHONPATH=src` is required (`pytest.ini` sets it for the test runner only).
- **Always dry-run first.** Scripts default to read-only and take `--apply` to write; check the printed plan before applying.
- `RAW_BUCKET_NAME` is one of the deliberate `beatport-prod-*` survivors (see [backend/gotchas.md](../backend/gotchas.md)); everything else is `clouder-prod-*`.

## Analytics: checks

Analytics reads the lake live; the only bootstrap step is for the silver history: after the first green dbt build, set the Terraform variable `silver_events_table = "clouder_silver.events"` (until then the Lambda reads bronze only). Home cards and `/admin/analytics` show data as soon as telemetry lands (Firehose buffers ~5 min). Telemetry must be on in the frontend build (`VITE_TELEMETRY_ENABLED=true`, default in `scripts/deploy_frontend.sh`).

**Smoke test the ingest:**

```bash
aws s3 ls "s3://clouder-prod-analytics-lake/bronze/events/" | tail -3   # today's dt=... prefix
# Athena (workgroup beatport-prod-analytics, db clouder_analytics):
#   SELECT event_name, count(*) FROM bronze_events WHERE dt = '<today>' GROUP BY 1;
```

**Catalog snapshot (track → style dictionary)** runs nightly at 00:00 UTC (`clouder-prod-catalog-export`). Run it by hand after a deploy or if a night was missed:

```bash
aws lambda invoke --function-name clouder-prod-catalog-export /dev/stdout   # {"snapshot_dt": ..., "counts": {...}}
aws s3 ls "s3://clouder-prod-analytics-lake/bronze/catalog_export/" | tail -2
```

Snapshots older than 14 days expire (bucket lifecycle). A first run at midnight may wait out an Aurora resume (`min_acu=0`); the Data API retry covers it.

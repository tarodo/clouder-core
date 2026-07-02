# beatport → clouder Infra Rename — Migration Plan (Plan F)

> **Status: PLAN ONLY — NOT auto-executed.** This is an irreversible, high-blast-radius prod-infra migration whose safety can only be confirmed with `terraform plan` against live state (unavailable in the build environment). Executing a naive `var.project` flip risks **recreating the Aurora cluster and losing all curation data**. Apply is gated on a human `terraform plan` review + maintenance window (see "Execution gate").

**Goal:** Rename the AWS resource prefix `beatport-prod-*` → `clouder-prod-*`. Beatport is the upstream data *source*, not the product (CLOUDER). Keep `beatport` only where it genuinely means the source: the ingest provider code and the raw-releases S3 bucket.

**Plan series:** Plans 1-4 (analytics v2 backend + frontend) are DONE and independent of this. This rename can ship before or after them.

---

## Blast radius

`name_prefix = "${var.project}-${var.environment}"` (`infra/main.tf:2`), `var.project = "beatport"` (`infra/variables.tf:4`). **67 `${local.name_prefix}` references across 9 `.tf` files.** Flipping `var.project` renames every derived resource in one line — but AWS names are immutable, so Terraform **destroys + recreates** each renamed resource.

### Two tiers

**Stateless — safe to rename (destroy/recreate loses nothing durable):**
- Lambda functions (collector-api, workers, analytics-api, analytics-rollup, telemetry, migration, …), their IAM roles/policies, CloudWatch log groups.
- SQS queues + DLQs (in-flight messages lost — acceptable).
- API Gateway, integrations, routes, authorizer.
- Athena workgroup (`beatport-prod-analytics` — recreate is free).
- Frontend S3 bucket (`${name_prefix}-frontend` — static assets, CI re-deploys; CloudFront origin updates).

**Stateful — recreation = DATA LOSS (must NOT naively recreate):**
- `aws_rds_cluster.aurora` — `cluster_identifier = "${name_prefix}-aurora"` (`main.tf:27`). **Recreate ⇒ all curation data gone.**
- `aws_rds_cluster_instance.aurora_writer` — `identifier = "${db_cluster_identifier}-writer"` (`rds.tf:29`).
- `aws_db_subnet_group.aurora` — `name = "${name_prefix}-aurora-subnets"` (`network.tf:26`).
- `aws_security_group.aurora` — `name = "${name_prefix}-aurora-sg"` (`network.tf:31`).
- Aurora master secret — `db_secret_name = "${name_prefix}-aurora-credentials"` (`main.tf:28`; managed via `manage_master_user_password`).
- `aws_s3_bucket.raw` — `${name_prefix}-raw-${account_id}` (`main.tf:29`): the **Beatport-source** releases data. Keep `beatport`.

**The Aurora cascade (the landmine):** renaming `aws_db_subnet_group.aurora` or `aws_security_group.aurora` forces those resources to be recreated; because `aws_rds_cluster.aurora` references them by name (`db_subnet_group_name`, `vpc_security_group_ids`), the cluster may be **forced to replace** even if `cluster_identifier` itself were pinned. Pinning `cluster_identifier` alone is **insufficient** — the whole Aurora name cluster (cluster, writer, subnet group, SG, secret) must be pinned together, or migrated via snapshot/restore.

**Already literal (untouched by the flip):** `aws_s3_bucket.analytics_lake = "beatport-prod-analytics-lake"` and the `analytics_lake_bucket`/`athena_workgroup` var defaults in `analytics_routes.tf` are hard-coded literals, not `name_prefix`-derived — a `var.project` flip does not rename them. They keep the `beatport` name unless explicitly changed (cosmetic; analytics data-loss is acceptable but recreating the lake bucket cascades to Firehose/Glue/rollup — leave it for a separate step).

**Genuine-Beatport (keep `beatport`, do NOT rename):** `src/collector/beatport_client.py` (`BeatportClient`), route `POST /admin/beatport/ingest`, structlog `beatport_request`/`beatport_response`, `saturday_week.py` comments — these name the upstream source.

---

## Recommended strategy: **Approach A — stateless rename now, pin stateful**

Rename only the stateless tier; pin the entire stateful tier to its current literal names so the flip cannot touch it. Aurora keeps `beatport-prod-aurora` (internal identifier, not user-visible); a full Aurora rename is a separate snapshot/restore migration (Approach B) done only if the name itself must change.

### Edits
1. `infra/variables.tf:4` — `var.project` default `"beatport"` → `"clouder"`.
2. `infra/main.tf` — pin the stateful locals to literals (decoupled from `name_prefix`):
   - `db_cluster_identifier = "beatport-prod-aurora"`
   - `db_secret_name = "beatport-prod-aurora-credentials"`
   - `generated_bucket_name = "beatport-prod-raw-${data.aws_caller_identity.current.account_id}"`
3. `infra/network.tf` — pin the Aurora subnet group + SG names to literals:
   - `aws_db_subnet_group.aurora` `name = "beatport-prod-aurora-subnets"`
   - `aws_security_group.aurora` `name = "beatport-prod-aurora-sg"`
   (Introduce a `local.legacy_prefix = "beatport-prod"` and use `${local.legacy_prefix}-...` for all five pins so the intent is explicit and greppable.)
4. Leave `analytics_lake` bucket + `athena_workgroup`/`analytics_lake_bucket` var defaults as-is (already literal).
5. Do NOT touch the Beatport provider code.
6. `docs/api/openapi.yaml` / CLAUDE.md: update gotcha #4 (`beatport-prod-*` → `clouder-prod-*`, noting Aurora/raw-bucket/lake retain `beatport`).

### Execution gate (MANDATORY — cannot be done in the build env)
- `cd infra && terraform init && terraform plan` and **read every planned action**. The plan MUST show:
  - **0 destroy/replace** on `aws_rds_cluster.aurora`, `aws_rds_cluster_instance.aurora_writer`, `aws_db_subnet_group.aurora`, `aws_security_group.aurora`, `aws_s3_bucket.raw`, and the Aurora secret.
  - Only stateless resources (Lambdas/SQS/IAM/log groups/API GW/workgroup/frontend bucket) replaced/renamed.
- If the plan shows ANY Aurora-cluster replacement, STOP — a name pin was missed; do not apply.
- Apply in a **maintenance window** (stateless recreation ⇒ brief API downtime + new ARNs; event-source mappings / API GW integrations recreate). Re-deploy the frontend after its bucket recreates.
- Post-apply: smoke-test `/auth/login`, a curation write, and the analytics routes.

## Approach B — full Aurora rename (only if the identifier itself must change)
Separate migration, its own window: `snapshot` the cluster → `restore` under `clouder-prod-aurora` (+ new subnet group/SG named `clouder-*`) → repoint every `AURORA_CLUSTER_ARN`/`AURORA_SECRET_ARN` env var → verify → destroy the old cluster. High-touch; out of scope unless explicitly requested.

---

## Why this is a plan, not an auto-executed change
The correctness of the pin set is only provable by `terraform plan` against live state, which the build environment has no access to. A wrong or incomplete pin silently recreates Aurora and destroys production curation data — irreversible. The safe path is: land these edits on a branch, have a human run `terraform plan`, confirm the gate conditions, then apply in a window. The edits themselves are small (one var + five literal pins); the risk is entirely in the apply, which must be human-reviewed.

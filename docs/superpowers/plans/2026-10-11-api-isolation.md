# API Isolation from Background Workers — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Background SQS workers can no longer take the Lambda capacity the API needs, and when the API fails or is throttled the owner is told.

**Architecture:** Every SQS event source mapping gets a `maximum_concurrency` cap, and a guard test keeps the sum of caps plus API headroom under the account quota. The quota itself (10 today) is requested in Terraform through `aws_servicequotas_service_quota`. Three new alarm sets cover the failure the errors alarms cannot see: throttles of the six API functions, 5xx from API Gateway, and account concurrency near the quota.

**Tech Stack:** Terraform (AWS provider 5.100.0), pytest guard tests over `infra/*.tf`, Markdown docs.

**Spec:** `~/Desktop/HIRING_AUDIT_2026-10-11.ru.md` §1.4 п. 1–2, §0.3 phase 1. Evidence: on 2026-10-11 at 04:47 UTC one `triage_block_finalized` fanned out into 131 comment collections, 80 artist and 32 label enrichments; the comments worker (no cap) and the enrichers (cap 8 each) took all 10 account slots; `clouder-prod-collector-api` was throttled 10 times, `clouder-prod-auth-handler` 5 times, API Gateway answered 16 × 5xx between 04:42 and 04:49; no alarm fired. `clouder-prod-spotify-search-dlq` holds 11 messages and its alarm has been in ALARM since 2026-10-08 20:29 UTC.

## Global Constraints

- Worktree: `../clouder-core-loop` next to the main checkout, branch `feat/api-isolation` from `origin/main`. `.venv` lives in the main repo: run tools as `.venv/bin/<tool>`.
- Commit messages come from the `caveman:caveman-commit` skill; Conventional Commits; no AI attribution; author stays `tarodo <rsvolozhanin@gmail.com>`.
- Repo text is English. No money figures anywhere in the repo.
- SQS event-source `maximum_concurrency` must be between 2 and 1000 (AWS limit).
- Lambda concurrency quota code: `L-B99A9384`, service code `lambda`; requested value: **100**.
- `ruff format` line length 100; `terraform fmt` clean.
- `README.md` counts are guarded by `tests/unit/test_readme.py` (Terraform resource definitions in `infra/*.tf`, excluding modules).

## Review Focus

1. **Quota request denied or approved lower than 100** → Terraform reads the real value and plans another request on every deploy. Expected: documented in the runbook with what to do (lower `lambda_concurrency_quota` to the approved value). Not testable offline; covered by the runbook text in Task 4.
2. **Someone raises a worker cap in `prod.tfvars`** → the budget test must read `prod.tfvars` overrides, not only defaults. Pinned in Task 2 (`test_worker_caps_leave_room_for_the_api` reads both).
3. **A new SQS worker added without a cap** → `test_every_sqs_worker_has_a_concurrency_cap` fails. Pinned in Task 1.
4. **A single 503 after an Aurora resume** must not page → the 5xx alarm threshold is 5 per 5 minutes. Pinned in Task 3 (`test_api_5xx_alarm`).
5. **DLQ redrive restarts the Spotify ban** → the worker now paces and pauses on bans (#283); after the redrive, watch `clouder-prod-spotify-search-worker` errors for 30 minutes. Covered in Task 5, step "Redrive".

---

### Task 1: A concurrency cap on every SQS worker

**Files:**
- Modify: `infra/lambda.tf` (event source mappings `canonicalization_queue` ~line 103, `vendor_match_queue` ~195, `comments_collect_queue` ~372)
- Modify: `infra/variables.tf` (new `canonicalization_max_concurrency`, `vendor_match_max_concurrency`, `comments_collect_max_concurrency`; validation on `spotify_search_max_concurrency`)
- Create: `tests/unit/test_concurrency_infra.py`

**Interfaces:**
- Produces: helpers `_block(kind, name)`, `_caps()` (ESM name → variable name) in `tests/unit/test_concurrency_infra.py`, reused by Tasks 2 and 3.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_concurrency_infra.py`:

```python
"""Background workers cannot take the API's Lambda capacity (postmortem 2026-10-11)."""

from __future__ import annotations

import re
from pathlib import Path

INFRA = Path(__file__).resolve().parents[2] / "infra"
TF = "\n".join(p.read_text() for p in sorted(INFRA.glob("*.tf")))


def _block(kind: str, name: str) -> str:
    m = re.search(rf'{kind} "{name}" \{{(.*?)\n\}}', TF, re.S)
    assert m, f"{kind} {name}"
    return m.group(1)


def _caps() -> dict[str, str]:
    """Event source mapping name → the variable that holds its maximum_concurrency."""
    caps = {}
    for name, body in re.findall(
        r'resource "aws_lambda_event_source_mapping" "([a-z_]+)" \{(.*?)\n\}', TF, re.S
    ):
        m = re.search(r"maximum_concurrency\s*=\s*var\.([a-z_]+)", body)
        caps[name] = m.group(1) if m else ""
    return caps


def test_every_sqs_worker_has_a_concurrency_cap() -> None:
    caps = _caps()
    assert len(caps) >= 7
    for esm, var in caps.items():
        assert var, f"{esm}: scaling_config.maximum_concurrency is missing"
        assert re.search(rf"var\.{var} >= 2 && var\.{var} <= 1000", _block("variable", var)), var
```

- [ ] **Step 2: Run it to make sure it fails**

Run: `PYTHONPATH=src .venv/bin/pytest tests/unit/test_concurrency_infra.py -q`
Expected: FAIL — `canonicalization_queue: scaling_config.maximum_concurrency is missing`.

- [ ] **Step 3: Add the caps**

In `infra/lambda.tf`, replace the three mappings:

```hcl
resource "aws_lambda_event_source_mapping" "canonicalization_queue" {
  event_source_arn = aws_sqs_queue.canonicalization.arn
  function_name    = aws_lambda_function.canonicalization_worker.arn
  batch_size       = var.canonicalization_batch_size

  # Every worker is capped so together they leave the API room in the account's
  # concurrency pool (infra/concurrency.tf, postmortem 2026-10-11).
  scaling_config {
    maximum_concurrency = var.canonicalization_max_concurrency
  }
}
```

```hcl
resource "aws_lambda_event_source_mapping" "vendor_match_queue" {
  event_source_arn = aws_sqs_queue.vendor_match.arn
  function_name    = aws_lambda_function.vendor_match_worker.arn
  batch_size       = var.vendor_match_batch_size
  enabled          = var.vendor_match_enabled

  scaling_config {
    maximum_concurrency = var.vendor_match_max_concurrency
  }
}
```

```hcl
resource "aws_lambda_event_source_mapping" "comments_collect_queue" {
  event_source_arn = aws_sqs_queue.comments_collect.arn
  function_name    = aws_lambda_function.comments_collect_worker.arn
  batch_size       = var.comments_collect_batch_size

  # A block finalize enqueues a comment collection per track (131 on 2026-10-11);
  # uncapped, they took every slot in the account and the API answered 5xx.
  scaling_config {
    maximum_concurrency = var.comments_collect_max_concurrency
  }
}
```

In `infra/variables.tf`, after `canonicalization_batch_size`:

```hcl
variable "canonicalization_max_concurrency" {
  description = "Most canonicalization workers running at once (SQS event-source maximum_concurrency, 2-1000). Part of the worker budget under the account concurrency quota (infra/concurrency.tf)."
  type        = number
  default     = 2

  validation {
    condition     = var.canonicalization_max_concurrency >= 2 && var.canonicalization_max_concurrency <= 1000
    error_message = "maximum_concurrency must be between 2 and 1000 (AWS SQS event-source limit)."
  }
}
```

After `vendor_match_batch_size`:

```hcl
variable "vendor_match_max_concurrency" {
  description = "Most vendor-match workers running at once (SQS event-source maximum_concurrency, 2-1000). Part of the worker budget under the account concurrency quota (infra/concurrency.tf)."
  type        = number
  default     = 2

  validation {
    condition     = var.vendor_match_max_concurrency >= 2 && var.vendor_match_max_concurrency <= 1000
    error_message = "maximum_concurrency must be between 2 and 1000 (AWS SQS event-source limit)."
  }
}
```

After `comments_collect_batch_size`:

```hcl
variable "comments_collect_max_concurrency" {
  description = "Most comments-collect workers running at once (SQS event-source maximum_concurrency, 2-1000). A block finalize enqueues one job per track. Part of the worker budget under the account concurrency quota (infra/concurrency.tf)."
  type        = number
  default     = 2

  validation {
    condition     = var.comments_collect_max_concurrency >= 2 && var.comments_collect_max_concurrency <= 1000
    error_message = "maximum_concurrency must be between 2 and 1000 (AWS SQS event-source limit)."
  }
}
```

Replace `spotify_search_max_concurrency` so it carries the same validation:

```hcl
variable "spotify_search_max_concurrency" {
  description = "Most Spotify search workers draining the queue at once (the SQS trigger allows 2 at least)."
  type        = number
  default     = 2

  validation {
    condition     = var.spotify_search_max_concurrency >= 2 && var.spotify_search_max_concurrency <= 1000
    error_message = "maximum_concurrency must be between 2 and 1000 (AWS SQS event-source limit)."
  }
}
```

- [ ] **Step 4: Run the test and fmt**

Run: `PYTHONPATH=src .venv/bin/pytest tests/unit/test_concurrency_infra.py -q && (cd infra && terraform fmt -check)`
Expected: 1 passed; fmt prints nothing.

- [ ] **Step 5: Commit** (message from `caveman:caveman-commit`, e.g. `feat(infra): cap every SQS worker's concurrency`)

---

### Task 2: The account quota in code, a worker budget, an account concurrency alarm

**Files:**
- Create: `infra/concurrency.tf`
- Modify: `tests/unit/test_concurrency_infra.py`

**Interfaces:**
- Consumes: `_block`, `_caps` from Task 1.
- Produces: `local.lambda_concurrency_quota` (number, 100) in `infra/concurrency.tf`; helper `_quota()`; resource `aws_cloudwatch_metric_alarm.lambda_account_concurrency`.

- [ ] **Step 1: Write the failing tests** (append to `tests/unit/test_concurrency_infra.py`)

```python
PROD = (INFRA / "prod.tfvars").read_text()
API_HEADROOM = 20  # executions kept free for the API functions and the scheduled jobs


def _quota() -> int:
    m = re.search(r"lambda_concurrency_quota\s*=\s*(\d+)", TF)
    assert m, "local.lambda_concurrency_quota"
    return int(m.group(1))


def _value(var: str) -> int:
    """prod.tfvars wins over the default, as in every plan and apply."""
    m = re.search(rf"^{var}\s*=\s*(\d+)", PROD, re.M)
    if m:
        return int(m.group(1))
    return int(re.search(r"default\s*=\s*(\d+)", _block("variable", var)).group(1))


def test_account_quota_is_requested_in_code() -> None:
    # 'type" "name' makes _block match: resource "type" "name" {
    body = _block("resource", 'aws_servicequotas_service_quota" "lambda_concurrency')
    assert re.search(r'service_code\s*=\s*"lambda"', body)
    assert re.search(r'quota_code\s*=\s*"L-B99A9384"', body)
    assert re.search(r"value\s*=\s*local\.lambda_concurrency_quota", body)


def test_worker_caps_leave_room_for_the_api() -> None:
    total = sum(_value(var) for var in _caps().values())
    assert total + API_HEADROOM <= _quota(), (total, _quota())


def test_account_concurrency_alarm_warns_before_the_quota() -> None:
    body = _block("resource", 'aws_cloudwatch_metric_alarm" "lambda_account_concurrency')
    assert re.search(r'metric_name\s*=\s*"ConcurrentExecutions"', body)
    assert re.search(r"threshold\s*=\s*local\.lambda_concurrency_quota \* 0\.8", body)
    assert "dimensions" not in body  # account-wide, not one function
    assert "local.alarm_actions" in body
```

- [ ] **Step 2: Run them to make sure they fail**

Run: `PYTHONPATH=src .venv/bin/pytest tests/unit/test_concurrency_infra.py -q`
Expected: 3 failed (`local.lambda_concurrency_quota`, missing resources).

- [ ] **Step 3: Create `infra/concurrency.tf`**

```hcl
# ── Lambda concurrency: the account quota and who may use it ──
# A new account gets 10 concurrent executions, shared by every function. On 2026-10-11
# a triage finalize fanned out into ~240 enrichment jobs that took all 10, and the API
# answered 5xx (docs/postmortems/2026-10-11-api-throttled-by-worker-burst.md). The
# quota is requested here; every SQS worker is capped (lambda.tf) and a test keeps the
# caps plus room for the API under it (tests/unit/test_concurrency_infra.py).
locals {
  lambda_concurrency_quota = 100
}

# Submits an increase request while the account is below the value; while it is pending,
# reads return the requested value, so plans stay clean. Destroying it changes nothing.
resource "aws_servicequotas_service_quota" "lambda_concurrency" {
  service_code = "lambda"
  quota_code   = "L-B99A9384" # Concurrent executions
  value        = local.lambda_concurrency_quota
}

resource "aws_cloudwatch_metric_alarm" "lambda_account_concurrency" {
  alarm_name          = "${local.name_prefix}-lambda-account-concurrency"
  alarm_description   = "Account Lambda concurrency at 80 % of the quota for 3 minutes: workers are about to crowd out the API (docs/ops/runbook.md#api-5xx-or-lambda-throttles)"
  namespace           = "AWS/Lambda"
  metric_name         = "ConcurrentExecutions"
  statistic           = "Maximum"
  period              = 60
  evaluation_periods  = 3
  threshold           = local.lambda_concurrency_quota * 0.8
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "notBreaching"

  alarm_actions = local.alarm_actions
  ok_actions    = local.alarm_actions
}
```

- [ ] **Step 4: Run the tests, fmt and validate**

Run: `PYTHONPATH=src .venv/bin/pytest tests/unit/test_concurrency_infra.py tests/unit/test_alarm_routing_infra.py -q && (cd infra && terraform fmt -check && terraform init -backend=false -input=false >/dev/null && terraform validate)`
Expected: all passed; `Success! The configuration is valid.` (Worker caps today: 2+2+2+8+8+2+2 = 26; 26 + 20 ≤ 100.)

- [ ] **Step 5: Commit** (e.g. `feat(infra): request Lambda quota in Terraform`)

---

### Task 3: Alarms on API throttles and API 5xx

**Files:**
- Modify: `infra/alarms.tf` (new section after `lambda_duration_p95`)
- Modify: `tests/unit/test_concurrency_infra.py`

**Interfaces:**
- Consumes: `local.api_functions` (map of the six API `aws_lambda_function` objects, `infra/lambda_aliases.tf`), `local.alarm_actions`, `aws_apigatewayv2_api.collector`, `aws_apigatewayv2_stage.default`.
- Produces: `aws_cloudwatch_metric_alarm.api_throttles` (for_each over `local.api_functions`), `aws_cloudwatch_metric_alarm.api_5xx`.

- [ ] **Step 1: Write the failing tests** (append)

```python
def test_every_api_function_alarms_on_throttles() -> None:
    body = _block("resource", 'aws_cloudwatch_metric_alarm" "api_throttles')
    assert re.search(r"for_each\s*=\s*local\.api_functions", body)
    assert re.search(r'metric_name\s*=\s*"Throttles"', body)
    assert re.search(r"threshold\s*=\s*1\b", body)
    assert "local.alarm_actions" in body


def test_api_5xx_alarm() -> None:
    body = _block("resource", 'aws_cloudwatch_metric_alarm" "api_5xx')
    assert re.search(r'namespace\s*=\s*"AWS/ApiGateway"', body)
    assert re.search(r'metric_name\s*=\s*"5xx"', body)
    # One 503 after an Aurora resume is expected (ADR-0014); five in five minutes is not.
    assert re.search(r"threshold\s*=\s*5\b", body) and re.search(r"period\s*=\s*300\b", body)
    assert "aws_apigatewayv2_api.collector.id" in body
    assert "aws_apigatewayv2_stage.default.name" in body
    assert "local.alarm_actions" in body
```

- [ ] **Step 2: Run them to make sure they fail**

Run: `PYTHONPATH=src .venv/bin/pytest tests/unit/test_concurrency_infra.py -q`
Expected: 2 failed.

- [ ] **Step 3: Add the alarms** (in `infra/alarms.tf`, after the `lambda_duration_p95` resource)

```hcl
# ── API throttles and 5xx ────────────────────────────────────────
# The errors alarms see neither: a throttled invocation is not a function error, and
# API Gateway's 5xx (throttles, timeouts) never reach the function. On 2026-10-11 the
# API answered 16 × 5xx while workers held every slot, and nothing fired.
resource "aws_cloudwatch_metric_alarm" "api_throttles" {
  for_each = local.api_functions

  alarm_name          = "${each.value.function_name}-throttles"
  comparison_operator = "GreaterThanOrEqualToThreshold"
  evaluation_periods  = 1
  metric_name         = "Throttles"
  namespace           = "AWS/Lambda"
  period              = 300
  statistic           = "Sum"
  threshold           = 1
  treat_missing_data  = "notBreaching"
  alarm_description   = "Lambda ${each.value.function_name} was throttled: the account concurrency pool is full (docs/ops/runbook.md#api-5xx-or-lambda-throttles)"

  dimensions = {
    FunctionName = each.value.function_name
  }

  alarm_actions = local.alarm_actions
  ok_actions    = local.alarm_actions
}

resource "aws_cloudwatch_metric_alarm" "api_5xx" {
  alarm_name          = "${local.name_prefix}-api-5xx"
  comparison_operator = "GreaterThanOrEqualToThreshold"
  evaluation_periods  = 1
  metric_name         = "5xx"
  namespace           = "AWS/ApiGateway"
  period              = 300
  statistic           = "Sum"
  threshold           = 5
  treat_missing_data  = "notBreaching"
  alarm_description   = "The API answered 5xx at least 5 times in 5 minutes; a single 503 after an Aurora resume is expected (docs/ops/runbook.md#api-5xx-or-lambda-throttles)"

  dimensions = {
    ApiId = aws_apigatewayv2_api.collector.id
    Stage = aws_apigatewayv2_stage.default.name
  }

  alarm_actions = local.alarm_actions
  ok_actions    = local.alarm_actions
}
```

- [ ] **Step 4: Run the tests, fmt, validate**

Run: `PYTHONPATH=src .venv/bin/pytest tests/unit/test_concurrency_infra.py tests/unit/test_alarm_routing_infra.py -q && (cd infra && terraform fmt -check && terraform validate)`
Expected: all passed; valid.

- [ ] **Step 5: Commit** (e.g. `feat(infra): alarm on API throttles and 5xx`)

---

### Task 4: Documents — runbook, scalability, postmortem, README

**Files:**
- Modify: `docs/ops/runbook.md` (new section after `## 429 Too Many Requests from the API`; DLQ section tail; `## Lambda reserved concurrency trip` mitigation)
- Modify: `docs/backend/gotchas.md` (lines ~138–144)
- Modify: `docs/scalability.md` (summary row `SQS workers`; section `## Workers and concurrency`)
- Create: `docs/postmortems/2026-10-11-api-throttled-by-worker-burst.md`
- Modify: `docs/postmortems/README.md` (index row)
- Modify: `README.md` (postmortem count, observability lines, Terraform resource count)

- [ ] **Step 1: Runbook — new section** (insert before `## Spotify search paused (rate-limit ban)`)

```markdown
## API 5xx or Lambda throttles

**Alarms:** `clouder-prod-api-5xx` (5 or more 5xx in 5 minutes), `clouder-prod-<api function>-throttles` (any throttle of collector, curation, auth handler, authorizer, analytics, telemetry), `clouder-prod-lambda-account-concurrency` (account concurrency at 80 % of the quota for 3 minutes).

**Most likely cause:** background workers filled the account's concurrency pool. A triage block finalize fans out into enrichment and comment jobs (one per track); each SQS worker is capped (`*_max_concurrency` in `infra/variables.tf`), and the caps plus room for the API must fit the quota (`infra/concurrency.tf`, checked by `tests/unit/test_concurrency_infra.py`).

**Check:**

```bash
# Quota now, and the state of the increase request
aws service-quotas get-service-quota --service-code lambda --quota-code L-B99A9384 --query 'Quota.Value'
aws service-quotas list-requested-service-quota-change-history-by-quota \
  --service-code lambda --quota-code L-B99A9384 --query 'RequestedQuotas[].[DesiredValue,Status,Created]'
# Which functions were throttled, and who was running
aws cloudwatch get-metric-statistics --namespace AWS/Lambda --metric-name Throttles \
  --dimensions Name=FunctionName,Value=clouder-prod-collector-api \
  --start-time <utc-start> --end-time <utc-end> --period 300 --statistics Sum
```

A single 503 right after a quiet period is the Aurora resume ([Cold-start 503](#cold-start-503)), not this.

**Fix now:** lower the busy worker's cap (`*_max_concurrency` in `infra/prod.tfvars`) and deploy; in an emergency, pause its trigger with `aws lambda update-event-source-mapping --uuid <uuid> --no-enabled` (the next deploy re-enables it). Queued jobs wait in SQS; nothing is lost.

**If the quota request was denied or approved lower:** set `lambda_concurrency_quota` in `infra/concurrency.tf` to the approved value, so plans stop re-requesting it, and lower the worker caps until `test_worker_caps_leave_room_for_the_api` passes.
```

- [ ] **Step 2: Runbook — DLQ section tail** (append after the `start-message-move-task` code block)

```markdown
Without `--destination-arn` the messages go back to the queue they came from. Check that the `<queue>-dlq-has-messages` alarm returns to OK once the DLQ is empty: an alarm left in ALARM means messages nobody looked at (on 2026-10-08 → 10-11, 11 Spotify messages waited two and a half days after their cause was fixed).
```

- [ ] **Step 3: Runbook and gotchas — reserved concurrency**

In `docs/ops/runbook.md` `## Lambda reserved concurrency trip`, replace the mitigation step that starts `1. Request a quota increase via AWS Service Quotas:` and its code block with:

```markdown
1. The quota is requested in Terraform (`infra/concurrency.tf`, `local.lambda_concurrency_quota`); check that the request was approved:
   `aws service-quotas get-service-quota --service-code lambda --quota-code L-B99A9384 --query 'Quota.Value'`
```

(Keep the rest of the section. Read the section first and keep its numbering consistent.)

In `docs/backend/gotchas.md`, replace the **Mitigation** paragraph of `### Lambda reserved concurrency is off by default` with:

```markdown
**Mitigation:** The account quota (`L-B99A9384`) is requested in Terraform (`infra/concurrency.tf`). Once it is approved at 35 or more, set `enable_lambda_reserved_concurrency = true` in `infra/prod.tfvars`. Until then, every SQS worker runs under its own `maximum_concurrency` cap, and vendor 429s flow through SQS retry → DLQ.
```

- [ ] **Step 4: Scalability**

Replace the summary row:

```markdown
| SQS workers | capped per queue (26 executions in total) | back up in their queues | back up in their queues | Account concurrency quota (10 until the increase to 100 requested in Terraform is approved; the API hit it at 1× on 2026-10-11) | Reserved concurrency per worker once the quota allows (the Terraform switch exists) |
```

Replace the `## Workers and concurrency` paragraph with:

```markdown
## Workers and concurrency

All functions share one account pool of concurrent executions. It was 10, the value for new accounts, and on 2026-10-11 it ran out at today's volume: a block finalize fanned out into ~240 enrichment and comment jobs, the workers took every slot and the API answered 5xx ([postmortem](postmortems/2026-10-11-api-throttled-by-worker-burst.md)). Now every SQS worker has a `maximum_concurrency` cap (26 executions together), a test keeps the caps plus 20 executions for the API and scheduled jobs under the quota, and an increase to 100 is requested in Terraform (`infra/concurrency.tf`). Under 10× load the workers back up in their queues — slower, not lossy, since every queue has a DLQ and redrive. Past that, `enable_lambda_reserved_concurrency = true` reserves per-worker capacity (values already in Terraform).
```

- [ ] **Step 5: Postmortem** — create `docs/postmortems/2026-10-11-api-throttled-by-worker-burst.md`

```markdown
# 2026-10-11 — Background workers took the API's Lambda capacity

## Summary

A triage block finalize fanned out into about 240 background jobs. The comment-collection worker had no concurrency cap and the enrichers were capped at 8 each, while the whole AWS account allows 10 concurrent Lambda executions. The workers took every slot, the API functions were throttled, and API Gateway answered 5xx. No alarm fired: alarms watched function errors, and a throttle is not one. The third hiring-audit review found it in the 30-day metrics the same morning.

## Impact

Between 04:42 and 04:49 UTC, 16 of about 200 API requests failed with 5xx for the one active user (the owner, triaging in the app). The background jobs were delayed and retried by SQS; none reached a dead-letter queue.

## Timeline (UTC)

- 04:38–04:47 — the owner triages a week: 21 track moves, 11 block lists, then `triage_block_finalized`.
- 04:4x — the finalize reaches the auto-enrich dispatch worker, which enqueues 131 comment collections, 80 artist and 32 label enrichments.
- 04:47 — comments (uncapped), artist and label enrichers (cap 8 each) fill the account pool. Throttles in that window: comments 176, artist 53, label 37, `clouder-prod-collector-api` 10, `clouder-prod-auth-handler` 5.
- 04:48–04:49 — API Gateway returns 15 × 5xx (one more at 04:42); the queues drain and errors stop.
- 09:17 — found while reviewing Lambda throttles and API 5xx for the audit.

## Root cause

One shared pool of 10 executions and no budget for it. The enricher caps (8 + 8) were meant to leave room for interactive functions but together exceeded the pool on their own; the comments worker, added later, had no cap; nothing checked the sum against the quota.

## Fix

- Every SQS event source mapping has a `maximum_concurrency` cap with validation; `tests/unit/test_concurrency_infra.py` fails on a mapping without one and on caps that, with 20 executions for the API and scheduled jobs, exceed the quota.
- The quota increase to 100 is requested in Terraform (`infra/concurrency.tf`), so the budget and the quota live next to each other.
- Alarms on throttles of the six API functions, on API Gateway 5xx (5 in 5 minutes) and on account concurrency at 80 % of the quota, all to the owner's email.

## Detection gap

- Errors alarms only: a throttled invocation is not a function error, and 5xx from API Gateway never reach the function.
- The one throttle alarm (label enricher) existed only with reserved concurrency switched on, which the quota of 10 made impossible.
- API 5xx were on the dashboard, which nobody watches at night.

## Follow-ups

- When the quota increase is approved, decide on `enable_lambda_reserved_concurrency` (it also protects vendor rate limits).
- Earlier in the same 30 days the curation, collector and auth functions were throttled 24 more times; the same mechanism is the likely cause, and the new alarms would have reported each one.
```

Add the index row in `docs/postmortems/README.md` (after the 2026-10-08 row):

```markdown
| 2026-10-11 | [Background workers took the API's Lambda capacity: 16 API requests failed, no alarm fired](2026-10-11-api-throttled-by-worker-burst.md) | A shared limit needs a budget and an alarm on running out, not only on errors |
```

- [ ] **Step 6: README**

- `five blameless [postmortems]` → `six blameless [postmortems]`.
- Line under *Cloud & infrastructure* ending `error alarms on every function, routed to email through SNS.` → `error alarms on every function plus throttle and 5xx alarms on the API, routed to email through SNS.`
- AWS services row `**CloudWatch + SNS**`: `alarms on every function's errors and on data/pipeline health` → `alarms on every function's errors, API throttles and 5xx, account concurrency and data/pipeline health`.
- *Production readiness* → **Observability**: `Error alarms on every Lambda function plus pipeline and data-health alarms` → `Error alarms on every Lambda function, throttle and 5xx alarms on the API, an account-concurrency alarm, plus pipeline and data-health alarms`.
- Terraform count: run `grep -c '^resource "' infra/*.tf | awk -F: '{s+=$2} END {print s}'` and replace both `239 Terraform resource definitions` occurrences with the printed number (expected 243).

- [ ] **Step 7: Run the doc and README guards, then everything**

Run: `PYTHONPATH=src .venv/bin/pytest tests/unit/test_readme.py tests/unit/test_docs_freshness.py tests/unit/test_docs_links.py -q && PYTHONPATH=src .venv/bin/pytest -q && .venv/bin/ruff check src tests scripts && .venv/bin/ruff format --check src tests scripts`
Expected: all pass.

- [ ] **Step 8: Commit** (e.g. `docs: postmortem and runbook for API throttling`)

---

### Task 5: Ship and verify in production

- [ ] **Step 1: Push and open the PR** — title and body from `caveman:caveman-commit` (what changed, why, how verified; no template headings for their own sake, no AI attribution).

```bash
cd <worktree>
git push -u origin feat/api-isolation
gh pr create --base main --head feat/api-isolation --title "<from caveman-commit>" --body "<from caveman-commit>"
```

- [ ] **Step 2: Read the PR's Terraform plan** — `gh pr checks <n> --watch`, then `gh run view <run> --log | grep -E "Plan:|will be (created|updated|destroyed)"`. Expected: 3 ESMs updated in place, 1 service quota + 1 account alarm + 6 throttle alarms + 1 5xx alarm created, nothing destroyed. If the plan errors on `servicequotas:*` permissions for the plan role, stop and report.

- [ ] **Step 3: Merge and watch the deploy** — `gh pr merge <n> --merge`, then `gh run watch` on the Deploy run. Expected: success, smoke 9/9. If the apply fails on the quota request, stop and report to the owner with the error.

- [ ] **Step 4: Verify**

```bash
aws service-quotas list-requested-service-quota-change-history-by-quota --service-code lambda \
  --quota-code L-B99A9384 --query 'RequestedQuotas[].[DesiredValue,Status,Created]' --output text
aws lambda list-event-source-mappings --query 'EventSourceMappings[].[FunctionArn,ScalingConfig.MaximumConcurrency]' --output text
aws cloudwatch describe-alarms --alarm-name-prefix clouder-prod --query 'MetricAlarms[?contains(AlarmName,`throttles`)||contains(AlarmName,`5xx`)||contains(AlarmName,`account-concurrency`)].[AlarmName,StateValue,length(AlarmActions)]' --output text
```

Expected: a request for 100 (PENDING / CASE_OPENED / APPROVED); every mapping has a number; 8 new alarms, each with 1 action, OK or INSUFFICIENT_DATA.

- [ ] **Step 5: Redrive the Spotify DLQ**

```bash
DLQ_ARN=$(aws sqs get-queue-attributes --queue-url "$(aws sqs get-queue-url --queue-name clouder-prod-spotify-search-dlq --query QueueUrl --output text)" --attribute-names QueueArn --query Attributes.QueueArn --output text)
aws sqs start-message-move-task --source-arn "$DLQ_ARN"
aws sqs list-message-move-tasks --source-arn "$DLQ_ARN" --query 'Results[0].[Status,ApproximateNumberOfMessagesMoved]'
```

Expected: COMPLETED, 11 moved; within ~10 minutes `clouder-prod-spotify-search-dlq-has-messages` is OK; `clouder-prod-spotify-search-worker` errors stay 0 over the next 30 minutes. If the messages land back in the DLQ, stop and report.

- [ ] **Step 6: Update the board** — in `~/Desktop/HIRING_AUDIT_2026-10-11.ru.md` §0.3, phase 1 → `done 2026-10-11` with the plan path, PR number, quota request status and DLQ result.

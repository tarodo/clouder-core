# Triage-Finalize Dispatch — Phase 2: Async Dispatch Worker Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move the triage-block auto-enrichment fan-out off the synchronous finalize request onto a dedicated SQS-driven worker, so block size can never time out the curation Lambda.

**Architecture:** `_finalize_triage_block` enqueues one lightweight `{block_id, user_id}` message onto a new `auto_enrich_dispatch` SQS queue and returns immediately. A new worker Lambda consumes that queue and calls the (Phase-1-optimized) `try_dispatch_for_triage_block` + `try_dispatch_artists_for_triage_block`, which fan out per-item messages onto the existing label/artist enrichment queues. The single-track path stays inline (already fast). Downstream enricher workers are unchanged.

**Tech Stack:** Python 3.12, boto3 SQS, RDS Data API, Terraform (AWS Lambda, SQS, IAM, CloudWatch), pytest.

**Depends on:** Phase 1 plan (`...-phase1-inline-optimization.md`) — this plan reuses the optimized dispatch functions. Land Phase 1 first.

**AWS naming:** resources are prefixed `${var.project}-${var.environment}` → `beatport-prod-*` in prod.

**Run tests with:** `/Users/roman/Projects/clouder-projects/clouder-core/.venv/bin/pytest`

---

## File Structure

| File | Responsibility | Change |
|---|---|---|
| `src/collector/curation/auto_enrich_dispatch.py` | Enqueue a block-level dispatch message | Create |
| `src/collector/auto_enrich_dispatch_handler.py` | Worker: consume queue, run block fan-out | Create |
| `src/collector/curation_handler.py` | Finalize endpoint | Swap inline dispatch → enqueue |
| `infra/main.tf` | Name locals | Add queue/dlq/worker names |
| `infra/sqs.tf` | Queues | Add dispatch queue + DLQ |
| `infra/lambda.tf` | Lambdas | Add worker + event-source mapping |
| `infra/logging.tf` | Log groups + DLQ alarms | Add worker log group + alarm entry |
| `infra/iam.tf` | `collector_lambda` policy | Add dispatch queue ARN to send + receive statements |
| `infra/curation.tf` | curation env | Add `AUTO_ENRICH_DISPATCH_QUEUE_URL` |
| `infra/variables.tf` | Tunables | Add dispatch queue/worker vars |
| `tests/unit/test_*` | Coverage | New + updated tests per task |

---

## Task 1: Block-level enqueue helper

**Files:**
- Create: `src/collector/curation/auto_enrich_dispatch.py`
- Test: `tests/unit/test_curation_auto_enrich_dispatch_enqueue.py` (create)

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_curation_auto_enrich_dispatch_enqueue.py`:

```python
import json
import collector.curation.auto_enrich_dispatch as d


class FakeSQS:
    def __init__(self): self.sent = []
    def send_message(self, **kw): self.sent.append(kw)


def test_enqueue_sends_one_block_message(monkeypatch):
    sqs = FakeSQS()
    monkeypatch.setattr(d, "_build_sqs_client", lambda: sqs)
    monkeypatch.setattr(d, "_queue_url", lambda: "https://q/dispatch")
    d.enqueue_block_auto_enrich(block_id="blk-1", user_id="u1")
    assert len(sqs.sent) == 1
    body = json.loads(sqs.sent[0]["MessageBody"])
    assert body == {"block_id": "blk-1", "user_id": "u1"}


def test_enqueue_never_raises(monkeypatch):
    def boom(): raise RuntimeError("no queue")
    monkeypatch.setattr(d, "_build_sqs_client", boom)
    d.enqueue_block_auto_enrich(block_id="blk-1", user_id="u1")  # must not raise
```

- [ ] **Step 2: Run test to verify it fails**

Run: `/Users/roman/Projects/clouder-projects/clouder-core/.venv/bin/pytest tests/unit/test_curation_auto_enrich_dispatch_enqueue.py -q`
Expected: FAIL — module does not exist.

- [ ] **Step 3: Implement the helper**

Create `src/collector/curation/auto_enrich_dispatch.py`:

```python
"""Enqueue one block-level auto-enrichment dispatch message.

Called from the finalize handler INSTEAD of running the label + artist fan-out
inline. The fan-out (claim, resolve, create-run, per-item enqueue) runs in the
auto-enrich-dispatch worker, so finalize returns in milliseconds regardless of
block size. Best-effort: never break finalize.
"""

from __future__ import annotations

import json
import os

from ..logging_utils import log_event


def _build_sqs_client():
    import boto3
    return boto3.client("sqs")


def _queue_url() -> str:
    url = os.environ.get("AUTO_ENRICH_DISPATCH_QUEUE_URL", "").strip()
    if not url:
        raise RuntimeError("AUTO_ENRICH_DISPATCH_QUEUE_URL is required")
    return url


def enqueue_block_auto_enrich(*, block_id: str, user_id: str | None) -> None:
    try:
        sqs = _build_sqs_client()
        sqs.send_message(
            QueueUrl=_queue_url(),
            MessageBody=json.dumps({"block_id": block_id, "user_id": user_id}),
        )
    except Exception as exc:  # noqa: BLE001 — best-effort, never break finalize
        log_event(
            "ERROR", "auto_enrich_block_enqueue_error",
            block_id=block_id, error_message=str(exc)[:500],
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `/Users/roman/Projects/clouder-projects/clouder-core/.venv/bin/pytest tests/unit/test_curation_auto_enrich_dispatch_enqueue.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/collector/curation/auto_enrich_dispatch.py tests/unit/test_curation_auto_enrich_dispatch_enqueue.py
git commit -m "feat(curation): add block-level auto-enrich enqueue helper"
```

---

## Task 2: Dispatch worker handler

**Files:**
- Create: `src/collector/auto_enrich_dispatch_handler.py`
- Test: `tests/unit/test_auto_enrich_dispatch_handler.py` (create)

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_auto_enrich_dispatch_handler.py`:

```python
import json
import collector.auto_enrich_dispatch_handler as h


def _sqs_event(*bodies):
    return {"Records": [{"body": json.dumps(b)} for b in bodies]}


def test_worker_runs_both_dispatches_per_block(monkeypatch):
    calls = []
    monkeypatch.setattr(h, "try_dispatch_for_triage_block",
                        lambda **kw: calls.append(("labels", kw)))
    monkeypatch.setattr(h, "try_dispatch_artists_for_triage_block",
                        lambda **kw: calls.append(("artists", kw)))
    h.lambda_handler(_sqs_event({"block_id": "blk-1", "user_id": "u1"}), None)
    assert ("labels", {"block_id": "blk-1", "user_id": "u1"}) in calls
    assert ("artists", {"block_id": "blk-1", "user_id": "u1"}) in calls


def test_worker_processes_each_record(monkeypatch):
    seen = []
    monkeypatch.setattr(h, "try_dispatch_for_triage_block",
                        lambda **kw: seen.append(kw["block_id"]))
    monkeypatch.setattr(h, "try_dispatch_artists_for_triage_block", lambda **kw: None)
    h.lambda_handler(
        _sqs_event({"block_id": "b1", "user_id": "u"}, {"block_id": "b2", "user_id": "u"}),
        None,
    )
    assert seen == ["b1", "b2"]


def test_worker_raises_on_unparseable_record(monkeypatch):
    monkeypatch.setattr(h, "try_dispatch_for_triage_block", lambda **kw: None)
    monkeypatch.setattr(h, "try_dispatch_artists_for_triage_block", lambda **kw: None)
    import pytest
    with pytest.raises(Exception):
        h.lambda_handler({"Records": [{"body": "not json"}]}, None)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `/Users/roman/Projects/clouder-projects/clouder-core/.venv/bin/pytest tests/unit/test_auto_enrich_dispatch_handler.py -q`
Expected: FAIL — module does not exist.

- [ ] **Step 3: Implement the worker**

Create `src/collector/auto_enrich_dispatch_handler.py`:

```python
"""SQS worker: run triage-block auto-enrichment fan-out off the request path.

Each message is `{block_id, user_id}`. For each, runs the label + artist
dispatch (both best-effort internally), which enqueue per-item work onto the
existing enrichment queues. An unparseable record raises so SQS redrives it to
the DLQ after the queue's maxReceiveCount.
"""

from __future__ import annotations

import json
from typing import Any, Mapping

from .artist_enrichment.auto_dispatch import try_dispatch_artists_for_triage_block
from .label_enrichment.auto_dispatch import try_dispatch_for_triage_block
from .logging_utils import log_event


def lambda_handler(event: Mapping[str, Any], context: Any) -> dict[str, Any]:
    records = event.get("Records", [])
    for record in records:
        msg = json.loads(record["body"])
        block_id = msg["block_id"]
        user_id = msg.get("user_id")
        log_event("INFO", "auto_enrich_block_dispatch_received", block_id=block_id)
        try_dispatch_for_triage_block(block_id=block_id, user_id=user_id)
        try_dispatch_artists_for_triage_block(block_id=block_id, user_id=user_id)
    return {"processed": len(records)}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `/Users/roman/Projects/clouder-projects/clouder-core/.venv/bin/pytest tests/unit/test_auto_enrich_dispatch_handler.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/collector/auto_enrich_dispatch_handler.py tests/unit/test_auto_enrich_dispatch_handler.py
git commit -m "feat(enrich): add auto-enrich-dispatch SQS worker"
```

---

## Task 3: Finalize enqueues instead of dispatching inline

**Files:**
- Modify: `src/collector/curation_handler.py:1529-1530` (and imports near top)
- Test: `tests/unit/test_curation_artist_auto_trigger.py:43-59`, `tests/unit/test_curation_auto_enrich_trigger.py` (finalize cases)

- [ ] **Step 1: Update the finalize test to expect an enqueue**

In `tests/unit/test_curation_artist_auto_trigger.py`, replace `test_finalize_triggers_artist_dispatch_for_block` with:

```python
def test_finalize_enqueues_block_auto_enrich():
    from collector import curation_handler as ch

    repo = MagicMock()
    finalize_result = MagicMock()
    finalize_result.block = MagicMock(finalized_at="t")
    finalize_result.promoted = {"cat-1": 3}
    repo.finalize_block.return_value = finalize_result

    cat_repo = MagicMock()
    with patch.object(ch, "enqueue_block_auto_enrich") as enqueue, \
         patch.object(ch, "try_dispatch_for_triage_block") as labels_inline, \
         patch.object(ch, "try_dispatch_artists_for_triage_block") as artists_inline, \
         patch.object(ch, "create_default_categories_repository", return_value=cat_repo), \
         patch.object(ch, "_serialize_triage_block", return_value={}):
        ch._finalize_triage_block(_finalize_event(), repo, "u1", "corr-1")
    enqueue.assert_called_once()
    assert enqueue.call_args.kwargs["block_id"] == "blk-1"
    assert enqueue.call_args.kwargs["user_id"] == "u1"
    # fan-out no longer runs inline on the request path
    labels_inline.assert_not_called()
    artists_inline.assert_not_called()
```

In `tests/unit/test_curation_auto_enrich_trigger.py`, find the finalize test (the one asserting `try_dispatch_for_triage_block` is called on finalize) and change it the same way: assert `enqueue_block_auto_enrich` is called once with `block_id` / `user_id`, and that `try_dispatch_for_triage_block` is **not** called inline. Leave the single-track `add_track` tests unchanged — that path stays inline.

- [ ] **Step 2: Run tests to verify they fail**

Run: `/Users/roman/Projects/clouder-projects/clouder-core/.venv/bin/pytest tests/unit/test_curation_artist_auto_trigger.py tests/unit/test_curation_auto_enrich_trigger.py -q`
Expected: FAIL — `curation_handler` has no `enqueue_block_auto_enrich`, and still calls the inline dispatchers.

- [ ] **Step 3: Wire the enqueue into finalize**

In `src/collector/curation_handler.py`, add the import near the other curation imports (alongside the existing `try_dispatch_for_triage_block` / `try_dispatch_artists_for_triage_block` imports):

```python
from .curation.auto_enrich_dispatch import enqueue_block_auto_enrich
```

Replace the two inline dispatch calls at lines 1529-1530 with the single enqueue:

```python
    enqueue_block_auto_enrich(block_id=block_id, user_id=user_id)
```

Keep the inline `try_dispatch_*_for_track` imports/usages for the single-track path untouched. (The triage-block dispatch functions are now invoked only by the Task-2 worker; the `curation_handler` imports of `try_dispatch_for_triage_block` / `try_dispatch_artists_for_triage_block` may remain for the tests above to patch them, but they are no longer called by `_finalize_triage_block`.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `/Users/roman/Projects/clouder-projects/clouder-core/.venv/bin/pytest tests/unit/test_curation_artist_auto_trigger.py tests/unit/test_curation_auto_enrich_trigger.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/collector/curation_handler.py tests/unit/test_curation_artist_auto_trigger.py tests/unit/test_curation_auto_enrich_trigger.py
git commit -m "feat(curation): finalize enqueues block auto-enrich, not inline"
```

---

## Task 4: Terraform — names, queue + DLQ, variables

**Files:**
- Modify: `infra/main.tf` (locals, after line 20)
- Modify: `infra/sqs.tf` (append)
- Modify: `infra/variables.tf` (append)

- [ ] **Step 1: Add name locals**

In `infra/main.tf`, after the `artist_enrichment_dlq_name` local (line 20), add:

```hcl
  auto_enrich_dispatch_worker_lambda_name = "${local.name_prefix}-auto-enrich-dispatch-worker"
  auto_enrich_dispatch_queue_name         = "${local.name_prefix}-auto-enrich-dispatch"
  auto_enrich_dispatch_dlq_name           = "${local.name_prefix}-auto-enrich-dispatch-dlq"
```

- [ ] **Step 2: Add the queue + DLQ**

Append to `infra/sqs.tf`:

```hcl
# ── Auto-enrich dispatch queue ───────────────────────────────────

resource "aws_sqs_queue" "auto_enrich_dispatch_dlq" {
  name                      = local.auto_enrich_dispatch_dlq_name
  message_retention_seconds = var.auto_enrich_dispatch_queue_retention_seconds
}

resource "aws_sqs_queue" "auto_enrich_dispatch" {
  name = local.auto_enrich_dispatch_queue_name
  visibility_timeout_seconds = max(
    var.auto_enrich_dispatch_queue_visibility_timeout_seconds,
    var.auto_enrich_dispatch_worker_lambda_timeout_seconds
  )
  message_retention_seconds = var.auto_enrich_dispatch_queue_retention_seconds

  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.auto_enrich_dispatch_dlq.arn
    maxReceiveCount     = var.auto_enrich_dispatch_queue_max_receive_count
  })
}
```

- [ ] **Step 3: Add the variables**

Append to `infra/variables.tf`:

```hcl
variable "auto_enrich_dispatch_queue_visibility_timeout_seconds" {
  type    = number
  default = 360
}

variable "auto_enrich_dispatch_queue_retention_seconds" {
  type    = number
  default = 86400
}

variable "auto_enrich_dispatch_queue_max_receive_count" {
  type    = number
  default = 3
}

variable "auto_enrich_dispatch_worker_lambda_timeout_seconds" {
  type    = number
  default = 300
}

variable "auto_enrich_dispatch_worker_lambda_memory_mb" {
  type    = number
  default = 512
}

variable "auto_enrich_dispatch_batch_size" {
  type    = number
  default = 1
}

variable "auto_enrich_dispatch_worker_max_concurrency" {
  type    = number
  default = 2
}
```

- [ ] **Step 4: Validate**

Run: `cd infra && terraform fmt && terraform validate`
Expected: `Success! The configuration is valid.`

- [ ] **Step 5: Commit**

```bash
git add infra/main.tf infra/sqs.tf infra/variables.tf
git commit -m "feat(infra): add auto-enrich-dispatch queue, dlq, vars"
```

---

## Task 5: Terraform — worker Lambda, log group, event-source mapping, alarm

**Files:**
- Modify: `infra/logging.tf` (log group + `dlq_queues` map)
- Modify: `infra/lambda.tf` (append worker + ESM)

- [ ] **Step 1: Add the log group**

In `infra/logging.tf`, after the `artist_enricher_worker` log group block, add:

```hcl
resource "aws_cloudwatch_log_group" "auto_enrich_dispatch_worker" {
  name              = "/aws/lambda/${local.auto_enrich_dispatch_worker_lambda_name}"
  retention_in_days = var.log_retention_days
}
```

In the `dlq_queues` local map (same file), add an entry so the DLQ-depth alarm covers it:

```hcl
    auto_enrich_dispatch = aws_sqs_queue.auto_enrich_dispatch_dlq.name
```

- [ ] **Step 2: Add the worker Lambda + event-source mapping**

Append to `infra/lambda.tf`:

```hcl
# ── Auto-enrich dispatch worker ──────────────────────────────────

resource "aws_lambda_function" "auto_enrich_dispatch_worker" {
  function_name = local.auto_enrich_dispatch_worker_lambda_name
  role          = aws_iam_role.collector_lambda.arn
  runtime       = "python3.12"
  handler       = "collector.auto_enrich_dispatch_handler.lambda_handler"
  filename      = local.lambda_zip_file
  timeout       = var.auto_enrich_dispatch_worker_lambda_timeout_seconds
  memory_size   = var.auto_enrich_dispatch_worker_lambda_memory_mb

  source_code_hash = filebase64sha256(local.lambda_zip_file)

  environment {
    variables = {
      AURORA_CLUSTER_ARN          = aws_rds_cluster.aurora.arn
      AURORA_SECRET_ARN           = try(aws_rds_cluster.aurora.master_user_secret[0].secret_arn, "")
      AURORA_DATABASE             = var.aurora_database_name
      LABEL_ENRICHMENT_QUEUE_URL  = aws_sqs_queue.label_enrichment.url
      ARTIST_ENRICHMENT_QUEUE_URL = aws_sqs_queue.artist_enrichment.url
      LOG_LEVEL                   = "INFO"
    }
  }

  depends_on = [
    aws_cloudwatch_log_group.auto_enrich_dispatch_worker,
  ]
}

resource "aws_lambda_event_source_mapping" "auto_enrich_dispatch_queue" {
  event_source_arn = aws_sqs_queue.auto_enrich_dispatch.arn
  function_name    = aws_lambda_function.auto_enrich_dispatch_worker.arn
  batch_size       = var.auto_enrich_dispatch_batch_size

  scaling_config {
    maximum_concurrency = var.auto_enrich_dispatch_worker_max_concurrency
  }
}
```

- [ ] **Step 3: Validate**

Run: `cd infra && terraform fmt && terraform validate`
Expected: `Success! The configuration is valid.`

- [ ] **Step 4: Commit**

```bash
git add infra/logging.tf infra/lambda.tf
git commit -m "feat(infra): add auto-enrich-dispatch worker lambda + esm"
```

---

## Task 6: Terraform — IAM + curation env wiring

**Files:**
- Modify: `infra/iam.tf` (SQS send statement ~88-93, receive statement ~107-112)
- Modify: `infra/curation.tf:17-34` (env block)

- [ ] **Step 1: Grant the dispatch queue to the shared role**

In `infra/iam.tf`, add the dispatch queue ARN to BOTH SQS statements on `collector_lambda`:

In the `sqs:SendMessage` statement `resources` list (so curation can enqueue and the worker can fan out — the worker already needs send on label/artist, which is present):

```hcl
      aws_sqs_queue.auto_enrich_dispatch.arn,
```

In the `sqs:ReceiveMessage` / `DeleteMessage` statement `resources` list (so the worker can consume):

```hcl
      aws_sqs_queue.auto_enrich_dispatch.arn,
```

- [ ] **Step 2: Wire the queue URL into the curation Lambda**

In `infra/curation.tf`, inside the `environment { variables = { ... } }` block of `aws_lambda_function.curation`, add:

```hcl
      AUTO_ENRICH_DISPATCH_QUEUE_URL            = aws_sqs_queue.auto_enrich_dispatch.url
```

- [ ] **Step 3: Validate**

Run: `cd infra && terraform fmt && terraform validate`
Expected: `Success! The configuration is valid.`

- [ ] **Step 4: Plan (review only — do not apply yet)**

Run: `cd infra && terraform plan`
Expected: adds `aws_sqs_queue.auto_enrich_dispatch(+dlq)`, `aws_lambda_function.auto_enrich_dispatch_worker`, `aws_lambda_event_source_mapping.auto_enrich_dispatch_queue`, `aws_cloudwatch_log_group.auto_enrich_dispatch_worker`, a new `aws_cloudwatch_metric_alarm.dlq_depth["auto_enrich_dispatch"]`; updates `aws_lambda_function.curation` (env) and the `collector_lambda` IAM policy. No destroys.

- [ ] **Step 5: Commit**

```bash
git add infra/iam.tf infra/curation.tf
git commit -m "feat(infra): grant + wire auto-enrich-dispatch queue to curation"
```

---

## Task 7: Full-suite verification + deploy/verify note

**Files:** none (verification only)

- [ ] **Step 1: Run the entire unit suite**

Run: `/Users/roman/Projects/clouder-projects/clouder-core/.venv/bin/pytest -q`
Expected: PASS.

- [ ] **Step 2: Confirm the worker is in the package**

The package script zips `src/collector`; the new handler is included automatically. Confirm the handler import path matches the Terraform `handler` value:

Run: `grep -rn "def lambda_handler" src/collector/auto_enrich_dispatch_handler.py`
Expected: one match (handler = `collector.auto_enrich_dispatch_handler.lambda_handler`).

- [ ] **Step 3: Deploy + verify (after merge)**

Run `scripts/package_lambda.sh` then `cd infra && terraform apply`. Then finalize a real triage block and confirm:
- `/aws/lambda/beatport-prod-curation` finalize request `REPORT` duration is now milliseconds (no inline fan-out, no `Status: timeout`).
- `/aws/lambda/beatport-prod-auto-enrich-dispatch-worker` logs `auto_enrich_block_dispatch_received`, then both `auto_enrich_dispatched` and `auto_enrich_artists_dispatched` with non-zero `claimed`.
- `beatport-prod-auto-enrich-dispatch-dlq` stays at 0 messages.

---

## Self-Review

**Spec coverage (Phase 2 section of the design):**
- New `auto_enrich_dispatch` queue + DLQ → Task 4. ✔
- Finalize enqueues one `{block_id, user_id}` and returns → Task 3. ✔
- New worker Lambda runs both dispatch functions, fans out to existing queues → Task 2. ✔
- Terraform: queue, DLQ, worker, IAM, ESM, `AUTO_ENRICH_DISPATCH_QUEUE_URL` → Tasks 4-6. ✔
- Downstream enricher workers unchanged → confirmed (no edits to `*_enrichment_handler.py`). ✔
- Reuses Phase 1 optimized dispatch → worker imports `try_dispatch_*_for_triage_block`. ✔

**Type consistency:** `enqueue_block_auto_enrich(*, block_id, user_id)` defined Task 1, consumed Task 3; worker handler `lambda_handler(event, context)` matches the `handler` string in Task 5; message shape `{block_id, user_id}` consistent across Tasks 1-3; queue resource name `aws_sqs_queue.auto_enrich_dispatch` consistent across Tasks 4-6; local names consistent with Task 1's `AUTO_ENRICH_DISPATCH_QUEUE_URL`.

**Placeholder scan:** No TBD/TODO; every code/HCL step shows complete content with exact run commands and expected output.

**Scope note:** Single-track dispatch stays inline by design (fast); only the triage-block fan-out moves async. Worker `batch_size = 1` avoids re-running already-dispatched blocks on a partial batch retry.
```

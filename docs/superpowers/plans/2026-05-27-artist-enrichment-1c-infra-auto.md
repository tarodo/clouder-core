# Artist Enrichment 1C — Infra + Auto-Dispatch Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make artist enrichment run automatically and be deployable: an `auto_dispatch` that enqueues artists (all track-artist roles) when tracks are curated, wired into the existing curation trigger points, plus the Terraform infra (SQS queue + DLQ, `artist_enricher_worker` Lambda + event-source-mapping, queue-URL env on the producer Lambdas).

**Architecture:** Mirror `label_enrichment/auto_dispatch.py` for artists (the differences: resolve a LIST of artists per track via `artist_ids_for_track` over all roles; the SQS message carries no `style` — the worker derives context; independent `kind="artists"` config toggle). Add a parallel artist dispatch call beside each existing label dispatch call in `curation_handler.py`. Mirror the label SQS/Lambda/variable/output Terraform blocks for artists.

**Tech Stack:** Python 3.12 (boto3 SQS), Terraform (API Gateway/Lambda/SQS), pytest.

**Spec:** `docs/superpowers/specs/2026-05-27-artist-enrichment-backend-design.md` (sub-project 1). This is **plan 1C of 3** (1A core ✅ → 1B API ✅ → 1C infra+auto). After 1C, PR the whole of SP1 (1A+1B+1C). 1A/1B already built `artist_enrichment.auto_repository` (with `claim_artists`, `artist_ids_for_track`/`artist_ids_for_triage_block` all-roles, `get_config`, `attach_run`), `ArtistEnrichmentRepository` (`get_artist_by_id`, `create_run`, `RunSpec(requested_artists=...)`), and the `artist_enrichment_handler` worker.

**Conventions (same as 1A/1B):**
- `<repo>` = `/Users/roman/Projects/clouder-projects/clouder-core/.claude/worktrees/improve_artist_search`; `<main-repo>` = `/Users/roman/Projects/clouder-projects/clouder-core`. Tests: `cd <repo> && PYTHONPATH=src <main-repo>/.venv/bin/pytest <paths>`.
- Each task: failing test → impl → green → commit. Hook enforces Conventional Commits, no AI attribution. After committing verify `git log -1` + `git status --short` (clean).
- Mirror source-of-truth: `src/collector/label_enrichment/auto_dispatch.py`, `src/collector/curation_handler.py` (call sites lines 85-87 import, ~574 track-add, ~1343 triage-finalize), `infra/{sqs,lambda,curation,main,variables,outputs}.tf`, and the label tests `tests/unit/test_auto_dispatch.py` + `tests/unit/test_curation_auto_enrich_trigger.py`.
- Entity swaps: `label`→`artist`, `label_id`→`artist_id`, `claim_labels`→`claim_artists`, `label_id_for_track`→`artist_ids_for_track` (now returns a LIST), `LabelEnrichmentRepository`→`ArtistEnrichmentRepository`, `requested_labels`→`requested_artists`, `LABEL_ENRICHMENT_QUEUE_URL`→`ARTIST_ENRICHMENT_QUEUE_URL`, `label_enrichment`→`artist_enrichment` (infra), `_KIND="labels"`→`"artists"`. **No `style` in the artist SQS message** (worker derives context); `derive_style_for_label` is NOT used.

---

## File Structure

```
src/collector/artist_enrichment/auto_dispatch.py   Task 1 (NEW)
src/collector/curation_handler.py                  Task 2 (ADD import + 2 dispatch calls)
infra/variables.tf                                 Task 3 (ADD 8 artist_enrichment_* vars)
infra/main.tf                                      Task 3 (ADD 3 name locals)
infra/sqs.tf                                       Task 3 (ADD artist queue + DLQ)
infra/lambda.tf                                    Task 3 (ADD worker + ESM + queue-url env on worker & collector)
infra/curation.tf                                  Task 3 (ADD queue-url env)
infra/outputs.tf                                   Task 3 (ADD queue-url output)
tests/unit/test_artist_auto_dispatch.py            Task 1
tests/unit/test_curation_artist_auto_trigger.py    Task 2
```

---

## Task 1: Artist auto-dispatch module

**Files:**
- Create: `src/collector/artist_enrichment/auto_dispatch.py`
- Test: `tests/unit/test_artist_auto_dispatch.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_artist_auto_dispatch.py`:

```python
import json
import collector.artist_enrichment.auto_dispatch as ad
from collector.artist_enrichment.repository import RunSpec


class FakeAutoRepo:
    def __init__(self, enabled=True, claim=None, ids_for_track=None, ids_for_block=None):
        self._cfg = {"enabled": enabled, "prompt_slug": "artist_v1", "prompt_version": "v1",
                     "vendors": ["openai"], "models": {"openai": "m"},
                     "merge_vendor": "deepseek", "merge_model": "d"} if enabled else {"enabled": False}
        self._claim = claim if claim is not None else []
        self._ids_for_track = ids_for_track or []
        self._ids_for_block = ids_for_block or []
        self.attached = None
    def get_config(self, kind): assert kind == "artists"; return self._cfg
    def claim_artists(self, ids): return list(self._claim)
    def attach_run(self, ids, run_id): self.attached = (list(ids), run_id)
    def artist_ids_for_track(self, track_id): return list(self._ids_for_track)
    def artist_ids_for_triage_block(self, block_id): return list(self._ids_for_block)


class FakeArtistRepo:
    def __init__(self): self.created = None
    def get_artist_by_id(self, aid): return {"id": aid, "name": f"name-{aid}"}
    def create_run(self, spec): self.created = spec; return "run-1"


class FakeSQS:
    def __init__(self): self.sent = []
    def send_message(self, **kw): self.sent.append(kw)


def _wire(monkeypatch, auto_repo, artist_repo=None, sqs=None):
    artist_repo = artist_repo or FakeArtistRepo()
    sqs = sqs or FakeSQS()
    monkeypatch.setattr(ad, "_build_auto_repository", lambda: auto_repo)
    monkeypatch.setattr(ad, "_build_artist_repository", lambda: artist_repo)
    monkeypatch.setattr(ad, "_build_sqs_client", lambda: sqs)
    monkeypatch.setattr(ad, "_queue_url", lambda: "https://q")
    return artist_repo, sqs


def test_disabled_config_skips(monkeypatch):
    auto = FakeAutoRepo(enabled=False)
    artist_repo, sqs = _wire(monkeypatch, auto)
    ad._dispatch_artists(artist_ids=["a1"], source_hint="single", user_id="u")
    assert sqs.sent == [] and artist_repo.created is None


def test_no_claim_skips_enqueue(monkeypatch):
    auto = FakeAutoRepo(enabled=True, claim=[])
    artist_repo, sqs = _wire(monkeypatch, auto)
    ad._dispatch_artists(artist_ids=["a1"], source_hint="single", user_id="u")
    assert sqs.sent == [] and artist_repo.created is None


def test_happy_path_creates_run_and_enqueues_per_artist(monkeypatch):
    auto = FakeAutoRepo(enabled=True, claim=["a1", "a2"])
    artist_repo, sqs = _wire(monkeypatch, auto)
    ad._dispatch_artists(artist_ids=["a1", "a2"], source_hint="single", user_id="u")
    assert isinstance(artist_repo.created, RunSpec)
    assert artist_repo.created.requested_artists == 2
    assert artist_repo.created.source == "auto"
    assert auto.attached == (["a1", "a2"], "run-1")
    assert len(sqs.sent) == 2
    msg = json.loads(sqs.sent[0]["MessageBody"])
    assert msg["run_id"] == "run-1" and msg["artist_id"] == "a1" and msg["artist_name"] == "name-a1"
    assert "style" not in msg


def test_track_dispatch_resolves_all_roles(monkeypatch):
    # artist_ids_for_track returns MULTIPLE artists (all roles)
    auto = FakeAutoRepo(enabled=True, claim=["a1", "a2", "a3"], ids_for_track=["a1", "a2", "a3"])
    artist_repo, sqs = _wire(monkeypatch, auto)
    ad.try_dispatch_artists_for_track(track_id="t1", user_id="u")
    assert len(sqs.sent) == 3


def test_dispatch_never_raises(monkeypatch):
    def boom(): raise RuntimeError("db down")
    monkeypatch.setattr(ad, "_build_auto_repository", boom)
    # must not raise
    ad.try_dispatch_artists_for_track(track_id="t1", user_id="u")
    ad.try_dispatch_artists_for_triage_block(block_id="b1", user_id="u")
```

- [ ] **Step 2: Run → FAIL** (`No module named 'collector.artist_enrichment.auto_dispatch'`).

Run: `cd <repo> && PYTHONPATH=src <main-repo>/.venv/bin/pytest tests/unit/test_artist_auto_dispatch.py -q`

- [ ] **Step 3: Create `auto_dispatch.py`**

Create `src/collector/artist_enrichment/auto_dispatch.py` with EXACTLY this content (mirrors the label module; key differences: `artist_ids_for_track` returns a list, message has no `style`, no `derive_style`):

```python
"""Best-effort auto-enrichment dispatch for artists from curation actions.

Mirror of label_enrichment.auto_dispatch. Enqueues onto the artist-enrichment
SQS queue; the worker derives disambiguation context, so the message carries
only run_id/artist_id/artist_name (no style). Every public entrypoint swallows
exceptions: auto-search must never break curation.
"""

from __future__ import annotations

import json
import os

from ..data_api import DataAPIClient, create_default_data_api_client
from ..logging_utils import log_event
from ..settings import get_data_api_settings
from .auto_repository import AutoEnrichRepository
from .repository import ArtistEnrichmentRepository, RunSpec

_KIND = "artists"


def _build_data_api() -> DataAPIClient:
    settings = get_data_api_settings()
    if not settings.is_configured:
        raise RuntimeError("Aurora Data API not configured")
    return create_default_data_api_client(
        resource_arn=str(settings.aurora_cluster_arn),
        secret_arn=str(settings.aurora_secret_arn),
        database=settings.aurora_database,
    )


def _build_auto_repository() -> AutoEnrichRepository:
    return AutoEnrichRepository(data_api=_build_data_api())


def _build_artist_repository() -> ArtistEnrichmentRepository:
    return ArtistEnrichmentRepository(data_api=_build_data_api())


def _build_sqs_client():
    import boto3
    return boto3.client("sqs")


def _queue_url() -> str:
    url = os.environ.get("ARTIST_ENRICHMENT_QUEUE_URL", "").strip()
    if not url:
        raise RuntimeError("ARTIST_ENRICHMENT_QUEUE_URL is required")
    return url


def _dispatch_artists(*, artist_ids: list[str], source_hint: str, user_id: str | None) -> None:
    if not artist_ids:
        return
    auto_repo = _build_auto_repository()
    cfg = auto_repo.get_config(_KIND)
    if not cfg or not cfg.get("enabled"):
        log_event(
            "INFO", "auto_enrich_artists_skipped_disabled",
            source_hint=source_hint, candidate_artists=len(artist_ids),
        )
        return

    claimed = auto_repo.claim_artists(sorted(set(artist_ids)))
    if not claimed:
        log_event(
            "INFO", "auto_enrich_artists_dispatched",
            claimed=0, skipped=len(set(artist_ids)), run_id=None, source_hint=source_hint,
        )
        return

    ae_repo = _build_artist_repository()
    resolved: list[tuple[str, str]] = []  # (artist_id, name)
    for artist_id in claimed:
        row = ae_repo.get_artist_by_id(artist_id)
        if row is None:
            continue
        resolved.append((artist_id, row["name"]))

    if not resolved:
        # Artists vanished between claim and resolve — leave state queued; the
        # stale-queued recovery in claim_artists re-enables them later.
        return

    spec = RunSpec(
        prompt_slug=cfg["prompt_slug"],
        prompt_version=cfg["prompt_version"],
        vendors=list(cfg["vendors"]),
        models=dict(cfg["models"]),
        merge_vendor=cfg["merge_vendor"],
        merge_model=cfg["merge_model"],
        requested_artists=len(resolved),
        created_by_user_id=user_id,
        source="auto",
    )
    run_id = ae_repo.create_run(spec)
    auto_repo.attach_run(claimed, run_id)

    sqs = _build_sqs_client()
    queue_url = _queue_url()
    for artist_id, name in resolved:
        sqs.send_message(
            QueueUrl=queue_url,
            MessageBody=json.dumps({
                "run_id": run_id,
                "artist_id": artist_id,
                "artist_name": name,
            }),
        )

    log_event(
        "INFO", "auto_enrich_artists_dispatched",
        claimed=len(resolved), skipped=len(set(artist_ids)) - len(claimed),
        run_id=run_id, source_hint=source_hint,
    )


def _safe(fn) -> None:
    try:
        fn()
    except Exception as exc:  # noqa: BLE001 — best-effort, never break curation
        log_event("ERROR", "auto_enrich_artists_dispatch_error", error_message=str(exc)[:500])


def try_dispatch_artists_for_track(*, track_id: str, user_id: str | None) -> None:
    def _run() -> None:
        auto_repo = _build_auto_repository()
        artist_ids = auto_repo.artist_ids_for_track(track_id)
        if not artist_ids:
            return
        _dispatch_artists(artist_ids=artist_ids, source_hint="single", user_id=user_id)
    _safe(_run)


def try_dispatch_artists_for_triage_block(*, block_id: str, user_id: str | None) -> None:
    def _run() -> None:
        auto_repo = _build_auto_repository()
        artist_ids = auto_repo.artist_ids_for_triage_block(block_id)
        if not artist_ids:
            return
        _dispatch_artists(artist_ids=artist_ids, source_hint="triage", user_id=user_id)
    _safe(_run)
```

- [ ] **Step 4: Run → PASS (5 passed).**

- [ ] **Step 5: Commit**

```bash
git add src/collector/artist_enrichment/auto_dispatch.py tests/unit/test_artist_auto_dispatch.py
git commit -m "feat(artist-enrich): add auto-dispatch (all-roles, no style)"
git log -1 --format='%H %s'
git status --short
```

---

## Task 2: Wire artist dispatch into curation

**Files:**
- Modify: `src/collector/curation_handler.py` (add import + 2 dispatch calls beside the label ones)
- Test: `tests/unit/test_curation_artist_auto_trigger.py`

The label dispatch is wired at: import (lines ~85-87), track-added-to-category (~line 574: `try_dispatch_for_track(track_id=body.track_id, user_id=user_id)`), and triage-block-finalized (~line 1343: `try_dispatch_for_triage_block(block_id=block_id, user_id=user_id)`). Add the artist dispatch right beside each.

- [ ] **Step 1: Write the failing test**

First find the label trigger test to mirror its structure + the curation entry points it calls: read `tests/unit/test_curation_auto_enrich_trigger.py`. Create `tests/unit/test_curation_artist_auto_trigger.py` mirroring it for artists: monkeypatch `collector.curation_handler.try_dispatch_artists_for_track` (and `_for_triage_block`) with a recorder, drive the same curation entry points the label test drives (the track-add handler and the triage-finalize handler), and assert the artist dispatch was called with the right `track_id`/`block_id` + `user_id`. (Reuse the label test's fixtures/event-builders — copy them and add artist-dispatch assertions.) Keep it focused: one test for track-add → `try_dispatch_artists_for_track` called, one for triage-finalize → `try_dispatch_artists_for_triage_block` called.

- [ ] **Step 2: Run → FAIL** (artist dispatch not called / not imported).

- [ ] **Step 3: Edit `curation_handler.py`**

- Extend the import (lines ~85-87) — add a second import beside the label one:
```python
from .artist_enrichment.auto_dispatch import (
    try_dispatch_artists_for_track,
    try_dispatch_artists_for_triage_block,
)
```
- At the track-added site (~line 574), add immediately after the existing `try_dispatch_for_track(...)`:
```python
        try_dispatch_artists_for_track(track_id=body.track_id, user_id=user_id)
```
(match the surrounding indentation — it's inside the same `if was_new:` block as the label call).
- At the triage-finalize site (~line 1343), add immediately after the existing `try_dispatch_for_triage_block(...)`:
```python
    try_dispatch_artists_for_triage_block(block_id=block_id, user_id=user_id)
```
Both artist functions are best-effort (swallow their own exceptions), so they can't break curation. They use the independent `kind="artists"` config toggle, so artist auto-enrich is on/off independently of labels.

- [ ] **Step 4: Run → PASS.** Then sanity: `cd <repo> && PYTHONPATH=src <main-repo>/.venv/bin/pytest tests/unit/test_curation_auto_enrich_trigger.py tests/unit/test_curation_artist_auto_trigger.py -q` → both label + artist trigger tests pass (label wiring unbroken). Import check: `PYTHONPATH=src <main-repo>/.venv/bin/python -c "import collector.curation_handler; print('ok')"`.

- [ ] **Step 5: Commit**

```bash
git add src/collector/curation_handler.py tests/unit/test_curation_artist_auto_trigger.py
git commit -m "feat(artist-enrich): dispatch artists on curation (track add, triage finalize)"
git log -1 --format='%H %s'
git status --short
```

---

## Task 3: Terraform infra (SQS + worker Lambda + env)

**Files:**
- Modify: `infra/variables.tf`, `infra/main.tf`, `infra/sqs.tf`, `infra/lambda.tf`, `infra/curation.tf`, `infra/outputs.tf`

No Python tests — verify with `terraform fmt` + `terraform validate` (needs `init`; if unavailable, `fmt` + grep checks). Mirror the label-enrichment infra for artists.

- [ ] **Step 1: Variables** — in `infra/variables.tf`, copy the 8 `variable "label_enrichment_*"` blocks (lines ~425-467: `_queue_visibility_timeout_seconds`, `_queue_retention_seconds`, `_queue_max_receive_count`, `_worker_lambda_timeout_seconds`, `_worker_lambda_memory_mb`, `_worker_reserved_concurrency`, `_batch_size`, `_worker_max_concurrency`) to `variable "artist_enrichment_*"` equivalents (same defaults/descriptions, swap `label`→`artist`).

- [ ] **Step 2: Name locals** — in `infra/main.tf`, add beside the label locals (lines ~15-17):
```hcl
  artist_enrichment_worker_lambda_name = "${local.name_prefix}-artist-enricher-worker"
  artist_enrichment_queue_name         = "${local.name_prefix}-artist-enrichment"
  artist_enrichment_dlq_name           = "${local.name_prefix}-artist-enrichment-dlq"
```

- [ ] **Step 3: SQS** — in `infra/sqs.tf`, copy the label queue + DLQ blocks (`aws_sqs_queue.label_enrichment_dlq` + `aws_sqs_queue.label_enrichment`) to `aws_sqs_queue.artist_enrichment_dlq` + `aws_sqs_queue.artist_enrichment`, swapping the local names + the `var.label_enrichment_*` → `var.artist_enrichment_*` references + the redrive `deadLetterTargetArn`/`maxReceiveCount`.

- [ ] **Step 4: Worker Lambda + ESM** — in `infra/lambda.tf`, copy the `aws_lambda_function.label_enricher_worker` + `aws_cloudwatch_log_group.label_enricher_worker` (if present) + `aws_lambda_event_source_mapping.label_enrichment_queue` to artist equivalents: handler `collector.artist_enrichment_handler.lambda_handler`, name `local.artist_enrichment_worker_lambda_name`, `var.artist_enrichment_*` tunables, env block includes `ARTIST_ENRICHMENT_QUEUE_URL = aws_sqs_queue.artist_enrichment.url` (plus the same SSM API-key vars + Aurora env + `AI_FLAG_CONFIDENCE_THRESHOLD` as the label worker), event-source-mapping maps `aws_sqs_queue.artist_enrichment.arn` → the artist worker with `scaling_config.maximum_concurrency = var.artist_enrichment_worker_max_concurrency`. Also add `ARTIST_ENRICHMENT_QUEUE_URL = aws_sqs_queue.artist_enrichment.url` to the **collector** lambda's environment (it already has `LABEL_ENRICHMENT_QUEUE_URL` — add the artist one beside it) so the manual-enrich route (`POST /admin/artists/enrich`, hosted on the collector lambda) can enqueue. (If a `aws_cloudwatch_log_group` for the worker exists, mirror it + the `depends_on`.)

- [ ] **Step 5: Curation env** — in `infra/curation.tf`, add `ARTIST_ENRICHMENT_QUEUE_URL = aws_sqs_queue.artist_enrichment.url` beside the existing `LABEL_ENRICHMENT_QUEUE_URL` (line ~22) so `auto_dispatch` can enqueue from curation.

- [ ] **Step 6: Output** — in `infra/outputs.tf`, add an `output "artist_enrichment_queue_url"` mirroring the label one (`value = aws_sqs_queue.artist_enrichment.url`).

- [ ] **Step 7: Verify**
- `cd <repo>/infra && terraform fmt` → exits 0 (no reformatting). Run `terraform fmt -check` to confirm.
- `grep -c "artist_enrichment" infra/*.tf` → references present across sqs/lambda/curation/main/variables/outputs.
- `grep -n "ARTIST_ENRICHMENT_QUEUE_URL" infra/lambda.tf infra/curation.tf` → present on the worker, the collector, and curation lambdas.
- `terraform validate` if `terraform init` works offline; otherwise note it needs init (provider download) — not a code error.

- [ ] **Step 8: Commit**

```bash
git add infra/variables.tf infra/main.tf infra/sqs.tf infra/lambda.tf infra/curation.tf infra/outputs.tf
git commit -m "feat(artist-enrich): add artist SQS queue + worker Lambda infra"
git log -1 --format='%H %s'
git status --short
```

---

## Done criteria for plan 1C

- `try_dispatch_artists_for_track`/`_for_triage_block` enqueue all of a track's artists (all roles) when curation adds tracks / finalizes a triage block, gated by the independent `kind="artists"` auto-config, best-effort (never break curation).
- Terraform defines the artist SQS queue + DLQ, the `artist_enricher_worker` Lambda + event-source-mapping, and the `ARTIST_ENRICHMENT_QUEUE_URL` env on the worker, collector, and curation Lambdas; `terraform fmt` clean.
- Label suite + curation suite remain green; no live API calls in tests.

## After 1C: finish sub-project 1

All of SP1 (1A core + 1B API + 1C infra+auto) is on branch `worktree-improve_artist_search`. Run the full backend test suite, then use `superpowers:finishing-a-development-branch` to PR the whole sub-project 1. Apply the migration (`db_migration` Lambda `{"action":"upgrade","revision":"head"}`) + `terraform apply` on deploy. Then sub-project 2 (frontend) gets its own spec → plan → implementation cycle, consuming the endpoints shipped here.

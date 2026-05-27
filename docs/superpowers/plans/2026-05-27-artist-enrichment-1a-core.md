# Artist Enrichment 1A — Core Engine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the server-side core of artist enrichment — DB tables + the `artist_enrichment` package engine (schema, prompt, aggregator, repository, orchestrator, SQS worker handler) — so a single artist can be enriched end-to-end by invoking the worker with mocked vendors.

**Architecture:** Mirror `src/collector/label_enrichment/` as a parallel `src/collector/artist_enrichment/` package, swapping the entity (`artist_id`, many-to-many via `clouder_track_artists`) and the payload schema (`ArtistInfo`). Reuse the schema-agnostic vendor adapters + pricing from `label_enrichment.vendors` by import. Port `ArtistInfo`, the `artist_v1` prompt, and the artist-adapted consensus aggregator from the validated `experiments/artists/` sandbox.

**Tech Stack:** Python 3.12, pydantic v2, Aurora RDS Data API (no psycopg), alembic, pytest. No live API calls in tests.

**Spec:** `docs/superpowers/specs/2026-05-27-artist-enrichment-backend-design.md` (sub-project 1 of 2). This is **plan 1A of 3** (1A core → 1B API → 1C infra+auto). 1A leaves out: HTTP routes, OpenAPI, auto-dispatch, infra, preferences — those are 1B/1C.

**Conventions:**
- **Paths:** `<repo>` = `/Users/roman/Projects/clouder-projects/clouder-core/.claude/worktrees/improve_artist_search` (the worktree — work here). `<main-repo>` = `/Users/roman/Projects/clouder-projects/clouder-core` (the original repo). Per CLAUDE.md gotcha #3, in a worktree the `.venv` lives at the MAIN repo root, so the test binary is `<main-repo>/.venv/bin/pytest`.
- Run tests from `<repo>` as: `cd <repo> && PYTHONPATH=src <main-repo>/.venv/bin/pytest <paths>`. Existing suites live in `tests/unit/` and `tests/integration/`.
- Each task ends with a commit. Generate the subject/body with `caveman:caveman-commit` (CLAUDE.md); the message shown is the expected output. A PreToolUse hook enforces Conventional Commits and strips AI attribution — no `Co-Authored-By`.
- After committing, verify with `git log -1 --format='%H %s'` + `git status --short` (clean) — a prior session saw a subagent skip the commit silently.
- **Source of truth for mirror files:** the proven `src/collector/label_enrichment/` modules. Where a task says "copy + transform", copy the named label file and apply the exact listed edits — do not re-transcribe from memory.
- **Port source:** the merged experiment at `experiments/artists/src/artlab/{schemas,prompts,aggregate}.py`.

---

## File Structure

```
alembic/versions/20260527_26_add_artist_enrichment_tables.py   Task 1 (NEW)
src/collector/artist_enrichment/
  __init__.py            Task 2  (empty)
  schemas.py             Task 2  (port ArtistInfo)
  prompts/__init__.py    Task 3  (registry)
  prompts/base.py        Task 3  (PromptConfig + render_user)
  prompts/artist_v1.py   Task 3  (port prompt)
  aggregator.py          Task 4  (port experiment aggregate.py; reuse label pricing)
  settings_provider.py   Task 5  (ArtistEnrichmentSecrets)
  repository.py          Task 6  (core CRUD + derive_artist_context)
  orchestrator.py        Task 7  (run vendors + enrich_artist_for_run + build adapters)
src/collector/artist_enrichment_handler.py   Task 8 (SQS worker)
tests/unit/test_artist_enrichment_schemas.py      Task 2
tests/unit/test_artist_enrichment_prompts.py      Task 3
tests/unit/test_artist_enrichment_aggregator.py   Task 4
tests/unit/test_artist_enrichment_repository.py   Task 6
tests/unit/test_artist_enrichment_orchestrator.py Task 7
tests/integration/test_artist_enrichment_handler.py Task 8
```

Reused by import (NOT copied): `label_enrichment.vendors.{base,gemini,openai_gpt,tavily_deepseek,pricing}`.

---

## Task 1: DB migration — artist enrichment tables

**Files:**
- Create: `alembic/versions/20260527_26_add_artist_enrichment_tables.py`

Mirror `alembic/versions/20260518_22_add_label_enrichment_tables.py` (runs/cells/info) + `20260525_25_auto_enrich.py` (state) for artists, plus the preferences table. Confirm the current head revision first.

- [ ] **Step 1: Find the current alembic head**

Run: `cd /Users/roman/Projects/clouder-projects/clouder-core/.claude/worktrees/improve_artist_search && grep -rl "down_revision" alembic/versions/ | xargs grep -h "^revision" | sort | tail -5`
Also run `PYTHONPATH=src ALEMBIC_DATABASE_URL='postgresql+psycopg://x' <main-repo>/.venv/bin/alembic heads 2>/dev/null` if available. Note the latest revision id (e.g. `20260525_25`); use it as `down_revision`.

- [ ] **Step 2: Write the migration**

Create `alembic/versions/20260527_26_add_artist_enrichment_tables.py` (set `down_revision` to the head found in Step 1):

```python
"""add artist enrichment tables (runs, cells, artist_info, auto state, prefs)

Revision ID: 20260527_26
Revises: 20260525_25
Create Date: 2026-05-27 00:00:01
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import ARRAY, JSONB

revision = "20260527_26"
down_revision = "20260525_25"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "clouder_artist_enrichment_runs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("status", sa.Text, nullable=False, server_default=sa.text("'queued'")),
        sa.Column("prompt_slug", sa.Text, nullable=False),
        sa.Column("prompt_version", sa.Text, nullable=False),
        sa.Column("vendors", JSONB, nullable=False),
        sa.Column("models", JSONB, nullable=False),
        sa.Column("merge_vendor", sa.Text, nullable=False),
        sa.Column("merge_model", sa.Text, nullable=False),
        sa.Column("requested_artists", sa.Integer, nullable=False),
        sa.Column("cells_total", sa.Integer, nullable=False),
        sa.Column("cells_ok", sa.Integer, nullable=False, server_default=sa.text("0")),
        sa.Column("cells_error", sa.Integer, nullable=False, server_default=sa.text("0")),
        sa.Column("cost_usd", sa.Numeric(10, 4), nullable=False, server_default=sa.text("0")),
        sa.Column("created_by_user_id", sa.String(36)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("source", sa.Text, nullable=False, server_default=sa.text("'manual'")),
    )
    op.create_index(
        "idx_artist_enr_runs_created_at",
        "clouder_artist_enrichment_runs",
        [sa.text("created_at DESC")],
    )

    op.create_table(
        "clouder_artist_enrichment_cells",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("run_id", sa.String(36), sa.ForeignKey("clouder_artist_enrichment_runs.id"), nullable=False),
        sa.Column("artist_id", sa.String(36), sa.ForeignKey("clouder_artists.id"), nullable=False),
        sa.Column("vendor", sa.Text, nullable=False),
        sa.Column("model", sa.Text, nullable=False),
        sa.Column("status", sa.Text, nullable=False),
        sa.Column("parsed", JSONB),
        sa.Column("citations", JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("usage", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("latency_ms", sa.Integer),
        sa.Column("error", JSONB),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("run_id", "artist_id", "vendor", name="uq_artist_enr_cell"),
    )
    op.create_index(
        "idx_artist_enr_cells_artist",
        "clouder_artist_enrichment_cells",
        ["artist_id", sa.text("created_at DESC")],
    )

    op.create_table(
        "clouder_artist_info",
        sa.Column("artist_id", sa.String(36), sa.ForeignKey("clouder_artists.id"), primary_key=True),
        sa.Column("last_run_id", sa.String(36), sa.ForeignKey("clouder_artist_enrichment_runs.id"), nullable=False),
        sa.Column("prompt_slug", sa.Text, nullable=False),
        sa.Column("prompt_version", sa.Text, nullable=False),
        sa.Column("merged", JSONB, nullable=False),
        sa.Column("provenance", JSONB, nullable=False),
        sa.Column("ai_content", sa.Text, nullable=False),
        sa.Column("ai_confidence", sa.Numeric(3, 2), nullable=False),
        sa.Column("status", sa.Text, nullable=False),
        sa.Column("primary_styles", ARRAY(sa.Text), nullable=False, server_default=sa.text("'{}'::text[]")),
        sa.Column("artist_type", sa.Text),
        sa.Column("country", sa.Text),
        sa.Column("active_since", sa.Integer),
        sa.Column("tagline", sa.Text),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("idx_artist_info_updated_at", "clouder_artist_info", [sa.text("updated_at DESC")])
    op.create_index("idx_artist_info_status", "clouder_artist_info", ["status"])
    op.create_index(
        "idx_artist_info_primary_styles",
        "clouder_artist_info",
        ["primary_styles"],
        postgresql_using="gin",
    )

    op.create_table(
        "artist_auto_enrich_state",
        sa.Column("artist_id", sa.String(36), sa.ForeignKey("clouder_artists.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("attempts", sa.Integer, nullable=False, server_default=sa.text("0")),
        sa.Column("status", sa.Text, nullable=False),
        sa.Column("last_run_id", sa.String(36), sa.ForeignKey("clouder_artist_enrichment_runs.id", ondelete="SET NULL")),
        sa.Column("first_enqueued_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_artist_auto_enrich_state_status", "artist_auto_enrich_state", ["status"])

    op.create_table(
        "clouder_user_artist_prefs",
        sa.Column("user_id", sa.String(36), nullable=False),
        sa.Column("artist_id", sa.String(36), sa.ForeignKey("clouder_artists.id", ondelete="CASCADE"), nullable=False),
        sa.Column("status", sa.Text, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("user_id", "artist_id", name="pk_user_artist_prefs"),
    )


def downgrade() -> None:
    op.drop_table("clouder_user_artist_prefs")
    op.drop_index("ix_artist_auto_enrich_state_status", table_name="artist_auto_enrich_state")
    op.drop_table("artist_auto_enrich_state")
    op.drop_index("idx_artist_info_primary_styles", table_name="clouder_artist_info")
    op.drop_index("idx_artist_info_status", table_name="clouder_artist_info")
    op.drop_index("idx_artist_info_updated_at", table_name="clouder_artist_info")
    op.drop_table("clouder_artist_info")
    op.drop_index("idx_artist_enr_cells_artist", table_name="clouder_artist_enrichment_cells")
    op.drop_table("clouder_artist_enrichment_cells")
    op.drop_index("idx_artist_enr_runs_created_at", table_name="clouder_artist_enrichment_runs")
    op.drop_table("clouder_artist_enrichment_runs")
```

NOTE: if Step 1 shows the head is NOT `20260525_25`, set `down_revision` to whatever the actual head is. The `clouder_user_label_prefs` table the artist version mirrors has columns `(user_id, label_id, status, updated_at)` with PK `(user_id, label_id)` — confirm against its migration and match exactly (no `created_at`).

- [ ] **Step 3: Verify the migration imports and the revision chain is valid**

Run: `cd <repo> && PYTHONPATH=src ALEMBIC_DATABASE_URL='postgresql+psycopg://postgres:postgres@localhost:5432/postgres' <main-repo>/.venv/bin/alembic history | head -3`
Expected: the new `20260527_26` appears at the top of the chain with no "multiple heads" error. (A live DB is not required just to validate the chain loads; if `alembic history` needs the DB, at minimum `python -c "import alembic.versions..."` must import the file without error.)

- [ ] **Step 4: Commit**

```bash
git add alembic/versions/20260527_26_add_artist_enrichment_tables.py
git commit -m "feat(artist-enrich): add artist enrichment + prefs tables"
```

---

## Task 2: `ArtistInfo` schema (port)

**Files:**
- Create: `src/collector/artist_enrichment/__init__.py` (empty)
- Create: `src/collector/artist_enrichment/schemas.py`
- Test: `tests/unit/test_artist_enrichment_schemas.py`

Port the validated schema from `experiments/artists/src/artlab/schemas.py` (`ArtistInfo`, `ArtistType`, `AIContentStatus`, `AISignalKind`, `AISignal`). Drop the experiment-only `Fixture`/`GroundTruth`/`FixturesFile` (those are sandbox fixtures, not needed in production).

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_artist_enrichment_schemas.py`:

```python
import pytest
from pydantic import ValidationError

from collector.artist_enrichment.schemas import (
    AIContentStatus,
    AISignal,
    AISignalKind,
    ArtistInfo,
    ArtistType,
)


def test_minimal_valid():
    info = ArtistInfo(artist_name="ANNA", ai_reasoning="none", summary="Brazilian techno DJ.", confidence=0.9)
    assert info.artist_name == "ANNA"
    assert info.artist_type == ArtistType.UNKNOWN
    assert info.ai_content == AIContentStatus.UNKNOWN
    assert info.labels == []


def test_confidence_bounds():
    with pytest.raises(ValidationError):
        ArtistInfo(artist_name="x", ai_reasoning="x", summary="x", confidence=1.5)


def test_ai_signal_and_links():
    info = ArtistInfo(
        artist_name="Aiva Nova",
        active_since=2024,
        spotify_url="https://open.spotify.com/artist/x",
        ai_content=AIContentStatus.SUSPECTED,
        ai_signals=[AISignal(kind=AISignalKind.NO_LIVE_PRESENCE, description="no gigs")],
        ai_reasoning="no presence",
        summary="synthetic",
        confidence=0.6,
    )
    assert info.active_since == 2024
    assert info.ai_signals[0].kind == AISignalKind.NO_LIVE_PRESENCE
    assert info.spotify_url.endswith("/x")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd <repo> && PYTHONPATH=src <main-repo>/.venv/bin/pytest tests/unit/test_artist_enrichment_schemas.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'collector.artist_enrichment'`.

- [ ] **Step 3: Create the package + schema**

Create empty `src/collector/artist_enrichment/__init__.py`.

Create `src/collector/artist_enrichment/schemas.py` by copying the `ArtistInfo`/`ArtistType`/`AIContentStatus`/`AISignalKind`/`AISignal` definitions verbatim from `experiments/artists/src/artlab/schemas.py` (everything EXCEPT the `Fixture`, `GroundTruth`, `FixturesFile` classes). The field set is: identity (`artist_name`, `aliases`, `real_name`, `artist_type`, `members`), origin (`country`, `city`, `active_since`, `status`), music (`primary_styles`, `labels`, `notable_collaborators`, `notable_releases`), 9 link fields, narrative (`tagline`, `bio`, `summary`), AI (`ai_content`, `ai_signals`, `ai_reasoning`), meta (`confidence`, `sources`, `notes`).

- [ ] **Step 4: Run test to verify it passes**

Run: `cd <repo> && PYTHONPATH=src <main-repo>/.venv/bin/pytest tests/unit/test_artist_enrichment_schemas.py -q`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add src/collector/artist_enrichment/__init__.py src/collector/artist_enrichment/schemas.py tests/unit/test_artist_enrichment_schemas.py
git commit -m "feat(artist-enrich): port ArtistInfo schema"
```

---

## Task 3: Prompts (`base`, registry, `artist_v1`) — port

**Files:**
- Create: `src/collector/artist_enrichment/prompts/__init__.py`
- Create: `src/collector/artist_enrichment/prompts/base.py`
- Create: `src/collector/artist_enrichment/prompts/artist_v1.py`
- Test: `tests/unit/test_artist_enrichment_prompts.py`

Port from `experiments/artists/src/artlab/prompts/`. The `render_user(cfg, artist_name, style, sample_tracks=None, known_labels=None)` signature and the disambiguation `context_block` logic are exactly what the orchestrator needs.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_artist_enrichment_prompts.py`:

```python
from collector.artist_enrichment.prompts import PROMPTS, get_prompt, load_builtin_prompts
from collector.artist_enrichment.prompts.base import render_user
from collector.artist_enrichment.schemas import ArtistInfo


def test_builtin_artist_v1_registered():
    load_builtin_prompts()
    cfg = get_prompt("artist_v1")
    assert cfg.version == "v1"
    assert cfg.schema is ArtistInfo
    assert "{context_block}" in cfg.user_template


def test_render_user_with_context():
    load_builtin_prompts()
    cfg = PROMPTS["artist_v1"]
    out = render_user(cfg, artist_name="ANNA", style="techno",
                      sample_tracks=["Hidden Beauties"], known_labels=["Drumcode"])
    assert "ANNA" in out and "Hidden Beauties" in out and "Drumcode" in out
    assert "genre hint: techno" in out


def test_render_user_without_context():
    load_builtin_prompts()
    cfg = PROMPTS["artist_v1"]
    out = render_user(cfg, artist_name="ANNA", style="techno")
    assert "Disambiguation context" not in out
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd <repo> && PYTHONPATH=src <main-repo>/.venv/bin/pytest tests/unit/test_artist_enrichment_prompts.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'collector.artist_enrichment.prompts'`.

- [ ] **Step 3: Port the three prompt modules**

Copy these three files from the experiment, changing ONLY the relative schema import (the experiment uses `..schemas`; production also uses `..schemas` — so no change needed):
- `experiments/artists/src/artlab/prompts/base.py` → `src/collector/artist_enrichment/prompts/base.py` (verbatim: `PromptConfig` dataclass + `render_user`).
- `experiments/artists/src/artlab/prompts/__init__.py` → `src/collector/artist_enrichment/prompts/__init__.py` (verbatim: `PROMPTS`, `register`, `get_prompt`, `load_builtin_prompts` importing `artist_v1`).
- `experiments/artists/src/artlab/prompts/artist_v1.py` → `src/collector/artist_enrichment/prompts/artist_v1.py` (verbatim: `SYSTEM`, `USER_TEMPLATE`, `register(PromptConfig(slug="artist_v1", version="v1", ..., schema=ArtistInfo))`).

Confirm each uses only relative imports (`from . import register`, `from .base import PromptConfig`, `from ..schemas import ArtistInfo`) so they resolve under `collector.artist_enrichment`.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd <repo> && PYTHONPATH=src <main-repo>/.venv/bin/pytest tests/unit/test_artist_enrichment_prompts.py -q`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add src/collector/artist_enrichment/prompts tests/unit/test_artist_enrichment_prompts.py
git commit -m "feat(artist-enrich): port artist_v1 prompt and registry"
```

---

## Task 4: Aggregator (port; reuse label pricing)

**Files:**
- Create: `src/collector/artist_enrichment/aggregator.py`
- Test: `tests/unit/test_artist_enrichment_aggregator.py`

The experiment's `experiments/artists/src/artlab/aggregate.py` is already artist-adapted (`ArtistInfo` field categories, `bio` in narrative). Port it, repointing the pricing import to the reused label vendor pricing.

- [ ] **Step 1: Copy the aggregator and repoint imports**

Copy `experiments/artists/src/artlab/aggregate.py` → `src/collector/artist_enrichment/aggregator.py`, then apply exactly these import edits:
- `from .schemas import ArtistInfo` stays as-is (resolves to `artist_enrichment.schemas`).
- `from .vendors.pricing import estimate_cost` → `from ..label_enrichment.vendors.pricing import estimate_cost`

No other change. The public `merge_cells(cells, deepseek_client, deepseek_model="deepseek-v4-flash") -> tuple[ArtistInfo, dict]` and helpers (`_filter_parseable`, `_merge_deterministic`, `_merge_narrative`) are unchanged.

- [ ] **Step 2: Port the aggregator test**

Copy `experiments/artists/tests/test_aggregate.py` → `tests/unit/test_artist_enrichment_aggregator.py`, then change the imports:
- `from artlab.aggregate import _filter_parseable, _merge_deterministic, merge_cells` → `from collector.artist_enrichment.aggregator import _filter_parseable, _merge_deterministic, merge_cells`
- `from artlab.schemas import ArtistInfo` → `from collector.artist_enrichment.schemas import ArtistInfo`

The test bodies (15 cases: median/majority/tie/country/round-robin/url/confidence/unknown-abstain/narrative-through-deepseek/fallback/single/all-failed/malformed/missing-key) are unchanged — they assert on the merge behavior, which is identical.

- [ ] **Step 3: Run the test**

Run: `cd <repo> && PYTHONPATH=src <main-repo>/.venv/bin/pytest tests/unit/test_artist_enrichment_aggregator.py -q`
Expected: PASS (15 passed). If a failure mentions the pricing import, re-check the Step 1 import edit.

- [ ] **Step 4: Commit**

```bash
git add src/collector/artist_enrichment/aggregator.py tests/unit/test_artist_enrichment_aggregator.py
git commit -m "feat(artist-enrich): port consensus aggregator"
```

---

## Task 5: Settings provider + vendor reuse

**Files:**
- Create: `src/collector/artist_enrichment/settings_provider.py`

The artist worker uses the same four vendor API keys as the label worker. Define a parallel secrets container (mirror `label_enrichment/settings_provider.py`); the vendor adapters themselves are imported from `label_enrichment.vendors` in Task 7 (no copy).

- [ ] **Step 1: Write `settings_provider.py`**

Create `src/collector/artist_enrichment/settings_provider.py`:

```python
"""Lightweight container so the factory does not depend on settings.py at import time."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ArtistEnrichmentSecrets:
    gemini_api_key: str
    openai_api_key: str
    tavily_api_key: str
    deepseek_api_key: str
```

- [ ] **Step 2: Verify it imports**

Run: `cd <repo> && PYTHONPATH=src <main-repo>/.venv/bin/python -c "from collector.artist_enrichment.settings_provider import ArtistEnrichmentSecrets; print('ok')"`
Expected: `ok`.

- [ ] **Step 3: Commit**

```bash
git add src/collector/artist_enrichment/settings_provider.py
git commit -m "feat(artist-enrich): add secrets container"
```

---

## Task 6: Repository (core write path + `derive_artist_context`)

**Files:**
- Create: `src/collector/artist_enrichment/repository.py`
- Test: `tests/unit/test_artist_enrichment_repository.py`

This is where artists genuinely differ from labels: many-to-many context derivation, artist denormalized columns (`artist_type`/`active_since` instead of `founded_year`/`activity`/`last_release_date`), and projecting the AI flag onto `clouder_artists`. The 1A subset covers the write/core path only; list/read/preference queries are deferred to plan 1B.

> Reference: `src/collector/label_enrichment/repository.py` (the proven patterns for Data API usage, JSONB decode, `_pg_text_array`, counters). The code below is the artist 1A subset — write it as given.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_artist_enrichment_repository.py`:

```python
from decimal import Decimal

from collector.artist_enrichment.repository import ArtistEnrichmentRepository, RunSpec
from collector.artist_enrichment.schemas import AIContentStatus, ArtistInfo
from collector.label_enrichment.vendors.base import VendorResponse


class FakeDataAPI:
    """Records execute() calls; returns queued responses FIFO (default [])."""

    def __init__(self, responses=None):
        self.calls = []
        self._responses = list(responses or [])

    def execute(self, sql, params=None):
        self.calls.append((sql, dict(params or {})))
        return self._responses.pop(0) if self._responses else []

    def last(self):
        return self.calls[-1]


def _info(**over):
    base = dict(artist_name="ANNA", ai_reasoning="x", summary="x", confidence=0.9)
    base.update(over)
    return ArtistInfo(**base)


def test_create_run_sets_cells_total():
    api = FakeDataAPI()
    repo = ArtistEnrichmentRepository(api)
    spec = RunSpec(
        prompt_slug="artist_v1", prompt_version="v1",
        vendors=["openai", "gemini"], models={"openai": "m", "gemini": "m"},
        merge_vendor="deepseek", merge_model="d", requested_artists=3, source="auto",
    )
    run_id = repo.create_run(spec)
    assert run_id
    sql, params = api.last()
    assert "clouder_artist_enrichment_runs" in sql
    assert params["requested_artists"] == 3
    assert params["cells_total"] == 6  # 3 artists * 2 vendors
    assert params["source"] == "auto"


def test_insert_cell_marks_error_when_no_parse():
    api = FakeDataAPI()
    repo = ArtistEnrichmentRepository(api)
    resp = VendorResponse(parsed=None, raw={}, citations=[], usage={"cost_usd": 0.0},
                          latency_ms=5, model="m", error="boom")
    repo.insert_cell(run_id="r", artist_id="a", vendor="openai", response=resp)
    sql, params = api.last()
    assert "clouder_artist_enrichment_cells" in sql
    assert params["status"] == "error"
    assert params["error"] == {"message": "boom"}


def test_upsert_artist_info_denormalizes_artist_columns():
    api = FakeDataAPI()
    repo = ArtistEnrichmentRepository(api)
    info = _info(artist_type="solo", country="Brazil", active_since=2008,
                 tagline="Brazilian techno", primary_styles=["techno", "house"],
                 ai_content=AIContentStatus.NONE_DETECTED, status="active", confidence=0.91)
    repo.upsert_artist_info(artist_id="a", last_run_id="r", prompt_slug="artist_v1",
                            prompt_version="v1", merged=info, provenance={"country": "x"})
    sql, params = api.last()
    assert "clouder_artist_info" in sql
    assert params["artist_type"] == "solo"
    assert params["country"] == "Brazil"
    assert params["active_since"] == 2008
    assert params["tagline"] == "Brazilian techno"
    assert params["ai_content"] == "none_detected"
    assert params["ai_confidence"] == Decimal("0.91")
    assert params["primary_styles"] == '{"techno","house"}'
    # no label-only columns leaked
    assert "founded_year" not in params and "activity" not in params


def test_project_ai_suspected_sets_flag_above_threshold():
    api = FakeDataAPI()
    repo = ArtistEnrichmentRepository(api)
    info = _info(ai_content=AIContentStatus.CONFIRMED, confidence=0.95)
    repo.project_ai_suspected("a", info, threshold=0.7)
    sql, params = api.last()
    assert "UPDATE clouder_artists" in sql
    assert params["value"] is True
    assert params["id"] == "a"


def test_project_ai_suspected_noop_below_threshold():
    api = FakeDataAPI()
    repo = ArtistEnrichmentRepository(api)
    info = _info(ai_content=AIContentStatus.CONFIRMED, confidence=0.5)
    repo.project_ai_suspected("a", info, threshold=0.7)
    assert api.calls == []  # nothing executed


def test_derive_artist_context_reads_style_tracks_labels():
    api = FakeDataAPI(responses=[
        [{"style_name": "techno", "cnt": 9}],                       # style query
        [{"title": "Hidden Beauties"}, {"title": "Forsaken"}],       # tracks query
        [{"label_name": "Drumcode"}, {"label_name": "Kompakt"}],     # labels query
    ])
    repo = ArtistEnrichmentRepository(api)
    ctx = repo.derive_artist_context("a")
    assert ctx.style == "techno"
    assert ctx.sample_tracks == ["Hidden Beauties", "Forsaken"]
    assert ctx.known_labels == ["Drumcode", "Kompakt"]


def test_derive_artist_context_defaults_style_to_music_when_no_tracks():
    api = FakeDataAPI(responses=[[], [], []])
    repo = ArtistEnrichmentRepository(api)
    ctx = repo.derive_artist_context("a")
    assert ctx.style == "music"
    assert ctx.sample_tracks == []
    assert ctx.known_labels == []


def test_upsert_artist_by_name_returns_existing_id():
    api = FakeDataAPI(responses=[[{"id": "existing-1"}]])
    repo = ArtistEnrichmentRepository(api)
    assert repo.upsert_artist_by_name("ANNA") == "existing-1"
    assert len(api.calls) == 1  # only the SELECT, no INSERT
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd <repo> && PYTHONPATH=src <main-repo>/.venv/bin/pytest tests/unit/test_artist_enrichment_repository.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'collector.artist_enrichment.repository'`.

- [ ] **Step 3: Write `repository.py` (1A subset)**

Create `src/collector/artist_enrichment/repository.py`:

```python
"""Aurora Data API persistence for artist enrichment (core write path)."""

from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Callable, Mapping, TYPE_CHECKING

from ..data_api import DataAPIClient

if TYPE_CHECKING:
    from .schemas import ArtistInfo
    from ..label_enrichment.vendors.base import VendorResponse


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


_NORM_RE = re.compile(r"\s+")


def _normalize_name(name: str) -> str:
    return _NORM_RE.sub(" ", name.strip().lower())


def _pg_text_array(items: list[str]) -> str:
    parts = []
    for item in items:
        if not isinstance(item, str):
            item = str(item)
        escaped = item.replace("\\", "\\\\").replace('"', '\\"')
        parts.append(f'"{escaped}"')
    return "{" + ",".join(parts) + "}"


@dataclass(frozen=True)
class RunSpec:
    prompt_slug: str
    prompt_version: str
    vendors: list[str]
    models: dict[str, str]
    merge_vendor: str
    merge_model: str
    requested_artists: int
    created_by_user_id: str | None = None
    source: str = "manual"


@dataclass(frozen=True)
class ArtistContext:
    style: str
    sample_tracks: list[str]
    known_labels: list[str]


class ArtistEnrichmentRepository:
    def __init__(self, data_api: DataAPIClient, now: Callable[[], datetime] = _utc_now) -> None:
        self._data_api = data_api
        self._now = now

    # ── artists ─────────────────────────────────────────────────────
    def get_artist_by_id(self, artist_id: str) -> dict[str, Any] | None:
        rows = self._data_api.execute(
            "SELECT id, name FROM clouder_artists WHERE id = :id LIMIT 1",
            {"id": artist_id},
        )
        return rows[0] if rows else None

    def upsert_artist_by_name(self, name: str) -> str:
        normalized = _normalize_name(name)
        rows = self._data_api.execute(
            "SELECT id FROM clouder_artists WHERE normalized_name = :n LIMIT 1",
            {"n": normalized},
        )
        if rows:
            return rows[0]["id"]
        new_id = str(uuid.uuid4())
        ts = self._now()
        self._data_api.execute(
            """
            INSERT INTO clouder_artists (
                id, name, normalized_name, is_ai_suspected, created_at, updated_at
            ) VALUES (
                :id, :name, :normalized_name, FALSE, :ts, :ts
            )
            """,
            {"id": new_id, "name": name.strip(), "normalized_name": normalized, "ts": ts},
        )
        return new_id

    def derive_artist_context(self, artist_id: str) -> ArtistContext:
        """Disambiguation context from the artist's tracks: dominant style,
        up to 3 recent track titles, and the distinct labels of those tracks."""
        style_rows = self._data_api.execute(
            """
            SELECT s.name AS style_name, COUNT(*) AS cnt
            FROM clouder_track_artists ta
            JOIN clouder_tracks t ON t.id = ta.track_id
            JOIN clouder_styles s ON s.id = t.style_id
            WHERE ta.artist_id = :artist_id
            GROUP BY s.name
            ORDER BY cnt DESC
            LIMIT 1
            """,
            {"artist_id": artist_id},
        )
        style = (style_rows[0].get("style_name") if style_rows else None) or "music"

        track_rows = self._data_api.execute(
            """
            SELECT t.title AS title
            FROM clouder_track_artists ta
            JOIN clouder_tracks t ON t.id = ta.track_id
            WHERE ta.artist_id = :artist_id
            ORDER BY t.publish_date DESC NULLS LAST, t.id DESC
            LIMIT 3
            """,
            {"artist_id": artist_id},
        )
        sample_tracks = [r["title"] for r in track_rows if r.get("title")]

        label_rows = self._data_api.execute(
            """
            SELECT DISTINCT l.name AS label_name
            FROM clouder_track_artists ta
            JOIN clouder_tracks t ON t.id = ta.track_id
            JOIN clouder_albums a ON a.id = t.album_id
            JOIN clouder_labels l ON l.id = a.label_id
            WHERE ta.artist_id = :artist_id AND a.label_id IS NOT NULL
            LIMIT 5
            """,
            {"artist_id": artist_id},
        )
        known_labels = [r["label_name"] for r in label_rows if r.get("label_name")]
        return ArtistContext(style=style, sample_tracks=sample_tracks, known_labels=known_labels)

    # ── runs ────────────────────────────────────────────────────────
    def create_run(self, spec: RunSpec) -> str:
        run_id = str(uuid.uuid4())
        ts = self._now()
        self._data_api.execute(
            """
            INSERT INTO clouder_artist_enrichment_runs (
                id, status, prompt_slug, prompt_version, vendors, models,
                merge_vendor, merge_model, requested_artists, cells_total,
                cells_ok, cells_error, cost_usd, created_by_user_id, created_at, source
            ) VALUES (
                :id, :status, :prompt_slug, :prompt_version, :vendors, :models,
                :merge_vendor, :merge_model, :requested_artists, :cells_total,
                0, 0, 0, :created_by_user_id, :created_at, :source
            )
            """,
            {
                "id": run_id,
                "status": "queued",
                "prompt_slug": spec.prompt_slug,
                "prompt_version": spec.prompt_version,
                "vendors": list(spec.vendors),
                "models": dict(spec.models),
                "merge_vendor": spec.merge_vendor,
                "merge_model": spec.merge_model,
                "requested_artists": spec.requested_artists,
                "cells_total": spec.requested_artists * len(spec.vendors),
                "created_by_user_id": spec.created_by_user_id,
                "created_at": ts,
                "source": spec.source,
            },
        )
        return run_id

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        rows = self._data_api.execute(
            """
            SELECT id, status, prompt_slug, prompt_version, vendors, models,
                   merge_vendor, merge_model, requested_artists, cells_total,
                   cells_ok, cells_error, cost_usd, created_by_user_id,
                   created_at, started_at, finished_at, source
            FROM clouder_artist_enrichment_runs
            WHERE id = :id
            LIMIT 1
            """,
            {"id": run_id},
        )
        if not rows:
            return None
        row = dict(rows[0])
        vendors_raw = row.get("vendors")
        if isinstance(vendors_raw, str):
            row["vendors"] = json.loads(vendors_raw)
        models_raw = row.get("models")
        if isinstance(models_raw, str):
            row["models"] = json.loads(models_raw)
        cost_usd = row.get("cost_usd")
        if isinstance(cost_usd, Decimal):
            row["cost_usd"] = float(cost_usd)
        elif isinstance(cost_usd, str):
            try:
                row["cost_usd"] = float(cost_usd)
            except (TypeError, ValueError):
                pass
        return row

    def mark_run_running(self, run_id: str) -> None:
        self._data_api.execute(
            """
            UPDATE clouder_artist_enrichment_runs
            SET status = 'running', started_at = :ts
            WHERE id = :id AND status = 'queued'
            """,
            {"id": run_id, "ts": self._now()},
        )

    def increment_run_counters(
        self, *, run_id: str, ok_delta: int, error_delta: int, cost_delta: float
    ) -> None:
        self._data_api.execute(
            """
            UPDATE clouder_artist_enrichment_runs
            SET
                cells_ok = cells_ok + :ok,
                cells_error = cells_error + :err,
                cost_usd = cost_usd + :cost,
                status = CASE WHEN cells_ok + cells_error + :ok + :err >= cells_total
                    THEN 'completed' ELSE status END,
                finished_at = CASE WHEN cells_ok + cells_error + :ok + :err >= cells_total
                    THEN :ts ELSE finished_at END
            WHERE id = :id
            """,
            {
                "id": run_id,
                "ok": ok_delta,
                "err": error_delta,
                "cost": Decimal(str(round(cost_delta, 4))),
                "ts": self._now(),
            },
        )

    # ── cells ───────────────────────────────────────────────────────
    def insert_cell(
        self, *, run_id: str, artist_id: str, vendor: str, response: "VendorResponse"
    ) -> None:
        from ..label_enrichment.vendors.base import VendorResponse

        assert isinstance(response, VendorResponse)
        cell_id = str(uuid.uuid4())
        ts = self._now()
        status = "ok" if response.error is None and response.parsed is not None else "error"
        parsed_payload = response.parsed.model_dump() if response.parsed is not None else None
        self._data_api.execute(
            """
            INSERT INTO clouder_artist_enrichment_cells (
                id, run_id, artist_id, vendor, model, status,
                parsed, citations, usage, latency_ms, error, created_at
            ) VALUES (
                :id, :run_id, :artist_id, :vendor, :model, :status,
                :parsed, :citations, :usage, :latency_ms, :error, :created_at
            )
            ON CONFLICT (run_id, artist_id, vendor) DO NOTHING
            """,
            {
                "id": cell_id,
                "run_id": run_id,
                "artist_id": artist_id,
                "vendor": vendor,
                "model": response.model,
                "status": status,
                "parsed": parsed_payload,
                "citations": list(response.citations),
                "usage": dict(response.usage),
                "latency_ms": response.latency_ms,
                "error": {"message": response.error} if response.error is not None else None,
                "created_at": ts,
            },
        )

    # ── artist_info ─────────────────────────────────────────────────
    def upsert_artist_info(
        self, *, artist_id: str, last_run_id: str, prompt_slug: str,
        prompt_version: str, merged: "ArtistInfo", provenance: Mapping[str, Any],
    ) -> None:
        ts = self._now()
        payload = merged.model_dump(mode="json")  # coerces enums to wire str
        self._data_api.execute(
            """
            INSERT INTO clouder_artist_info (
                artist_id, last_run_id, prompt_slug, prompt_version,
                merged, provenance,
                ai_content, ai_confidence, status, primary_styles,
                artist_type, country, active_since, tagline, updated_at
            ) VALUES (
                :artist_id, :last_run_id, :prompt_slug, :prompt_version,
                :merged, :provenance,
                :ai_content, :ai_confidence, :status, CAST(:primary_styles AS text[]),
                :artist_type, :country, :active_since, :tagline, :updated_at
            )
            ON CONFLICT (artist_id) DO UPDATE SET
                last_run_id = EXCLUDED.last_run_id,
                prompt_slug = EXCLUDED.prompt_slug,
                prompt_version = EXCLUDED.prompt_version,
                merged = EXCLUDED.merged,
                provenance = EXCLUDED.provenance,
                ai_content = EXCLUDED.ai_content,
                ai_confidence = EXCLUDED.ai_confidence,
                status = EXCLUDED.status,
                primary_styles = EXCLUDED.primary_styles,
                artist_type = EXCLUDED.artist_type,
                country = EXCLUDED.country,
                active_since = EXCLUDED.active_since,
                tagline = EXCLUDED.tagline,
                updated_at = EXCLUDED.updated_at
            """,
            {
                "artist_id": artist_id,
                "last_run_id": last_run_id,
                "prompt_slug": prompt_slug,
                "prompt_version": prompt_version,
                "merged": payload,
                "provenance": dict(provenance),
                "ai_content": payload.get("ai_content", "unknown"),
                "ai_confidence": Decimal(str(round(payload.get("confidence", 0.0), 2))),
                "status": payload.get("status", "unknown"),
                "primary_styles": _pg_text_array(payload.get("primary_styles") or []),
                "artist_type": payload.get("artist_type"),
                "country": payload.get("country"),
                "active_since": payload.get("active_since"),
                "tagline": payload.get("tagline"),
                "updated_at": ts,
            },
        )

    def project_ai_suspected(self, artist_id: str, merged: "ArtistInfo", threshold: float) -> None:
        """Mirror merged.ai_content into clouder_artists.is_ai_suspected when confidence >= threshold."""
        from .schemas import AIContentStatus

        if merged.confidence < threshold:
            return
        if merged.ai_content in (AIContentStatus.SUSPECTED, AIContentStatus.CONFIRMED):
            value = True
        elif merged.ai_content == AIContentStatus.NONE_DETECTED:
            value = False
        else:
            return
        self._data_api.execute(
            """
            UPDATE clouder_artists
            SET is_ai_suspected = :value, updated_at = :ts
            WHERE id = :id
            """,
            {"value": value, "ts": self._now(), "id": artist_id},
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd <repo> && PYTHONPATH=src <main-repo>/.venv/bin/pytest tests/unit/test_artist_enrichment_repository.py -q`
Expected: PASS (8 passed).

- [ ] **Step 5: Commit**

```bash
git add src/collector/artist_enrichment/repository.py tests/unit/test_artist_enrichment_repository.py
git commit -m "feat(artist-enrich): add repository core write path"
```

---

## Task 7: Orchestrator (derive context → run vendors → persist)

**Files:**
- Create: `src/collector/artist_enrichment/orchestrator.py`
- Test: `tests/unit/test_artist_enrichment_orchestrator.py`

Mirror `label_enrichment/orchestrator.py`, with two artist changes: (a) the cell `fixture` carries `artist_name` (the ported aggregator reads `fixture["artist_name"]`); (b) `enrich_artist_for_run` derives the disambiguation context via `repository.derive_artist_context(artist_id)` and feeds `sample_tracks`/`known_labels` into `render_user`. `build_adapters_from_run_config` imports the vendor adapters from `label_enrichment.vendors`.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_artist_enrichment_orchestrator.py`:

```python
from collector.artist_enrichment.orchestrator import enrich_artist_for_run, run_vendors_parallel
from collector.artist_enrichment.prompts import get_prompt, load_builtin_prompts
from collector.artist_enrichment.repository import ArtistContext
from collector.artist_enrichment.schemas import ArtistInfo
from collector.label_enrichment.vendors.base import VendorResponse


class StubAdapter:
    def __init__(self, name):
        self.name = name
        self.default_model = "stub-model"
        self.supports_web_search = True
        self.seen_user = None

    def run(self, *, system, user, schema, model=None):
        self.seen_user = user
        parsed = schema.model_validate(
            {"artist_name": "ANNA", "ai_reasoning": "x", "summary": "x", "confidence": 0.8}
        )
        return VendorResponse(parsed=parsed, raw={}, citations=["u"],
                              usage={"cost_usd": 0.001}, latency_ms=3,
                              model=model or self.default_model, error=None)


class FakeRepo:
    def __init__(self):
        self.cells = []
        self.upserted = None
        self.projected = None
        self.counters = None
        self.running = None

    def derive_artist_context(self, artist_id):
        return ArtistContext(style="techno", sample_tracks=["Hidden Beauties"], known_labels=["Drumcode"])

    def mark_run_running(self, run_id):
        self.running = run_id

    def insert_cell(self, *, run_id, artist_id, vendor, response):
        self.cells.append((vendor, response.error))

    def upsert_artist_info(self, *, artist_id, last_run_id, prompt_slug, prompt_version, merged, provenance):
        self.upserted = (artist_id, merged)

    def project_ai_suspected(self, artist_id, merged, threshold):
        self.projected = artist_id

    def increment_run_counters(self, *, run_id, ok_delta, error_delta, cost_delta):
        self.counters = (ok_delta, error_delta)


class FakeMergeClient:
    pass  # single-source path skips DeepSeek; multi-source uses it (mocked elsewhere)


def test_enrich_artist_for_run_persists_and_projects():
    load_builtin_prompts()
    prompt = get_prompt("artist_v1")
    repo = FakeRepo()
    adapters = [StubAdapter("openai")]
    outcomes = []

    enrich_artist_for_run(
        run_id="r", artist_id="a", artist_name="ANNA",
        adapters=adapters, merge_client=FakeMergeClient(), merge_model="d",
        prompt=prompt, repository=repo, ai_flag_threshold=0.7,
        on_outcome=lambda aid, ok: outcomes.append((aid, ok)),
    )

    assert repo.running == "r"
    assert repo.cells == [("openai", None)]
    assert isinstance(repo.upserted[1], ArtistInfo)
    assert repo.projected == "a"
    assert repo.counters == (1, 0)
    assert outcomes == [("a", True)]
    # disambiguation context flowed into the rendered prompt
    assert "Hidden Beauties" in adapters[0].seen_user
    assert "Drumcode" in adapters[0].seen_user
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd <repo> && PYTHONPATH=src <main-repo>/.venv/bin/pytest tests/unit/test_artist_enrichment_orchestrator.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'collector.artist_enrichment.orchestrator'`.

- [ ] **Step 3: Write `orchestrator.py`**

Create `src/collector/artist_enrichment/orchestrator.py`:

```python
"""High-level wiring: derive context, run vendors in parallel, aggregate, persist."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Callable

from .aggregator import merge_cells
from .prompts.base import PromptConfig, render_user
from .repository import ArtistEnrichmentRepository
from .settings_provider import ArtistEnrichmentSecrets
from ..label_enrichment.vendors.base import VendorAdapter, VendorResponse


def _cell_payload(vendor: VendorAdapter, response: VendorResponse, artist_name: str) -> dict:
    """Shape mirrors the aggregator input so merge_cells works unchanged."""
    return {
        "vendor": {"name": vendor.name, "model": response.model},
        "fixture": {"artist_name": artist_name},
        "response": {
            "parsed": response.parsed.model_dump() if response.parsed is not None else None,
            "citations": response.citations,
            "usage": response.usage,
            "latency_ms": response.latency_ms,
        },
        "error": response.error,
    }


def run_vendors_parallel(
    *,
    adapters: list[VendorAdapter],
    artist_name: str,
    style: str,
    sample_tracks: list[str],
    known_labels: list[str],
    prompt: PromptConfig,
) -> list[dict]:
    user = render_user(
        prompt,
        artist_name=artist_name,
        style=style,
        sample_tracks=sample_tracks,
        known_labels=known_labels,
    )
    results: list[tuple[VendorAdapter, VendorResponse]] = []
    with ThreadPoolExecutor(max_workers=max(1, len(adapters))) as pool:
        future_to_adapter = {
            pool.submit(
                adapter.run,
                system=prompt.system,
                user=user,
                schema=prompt.schema,
                model=prompt.vendor_overrides.get(adapter.name),
            ): adapter
            for adapter in adapters
        }
        for fut in as_completed(future_to_adapter):
            adapter = future_to_adapter[fut]
            try:
                resp = fut.result()
            except Exception as exc:  # noqa: BLE001 — vendors must not raise, but be defensive
                resp = VendorResponse(
                    parsed=None, raw={}, citations=[],
                    usage={"input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0},
                    latency_ms=0, model=adapter.default_model,
                    error=f"adapter raised: {type(exc).__name__}: {exc}",
                )
            results.append((adapter, resp))

    by_name = {a.name: r for a, r in results}
    return [_cell_payload(a, by_name[a.name], artist_name) for a in adapters]


def enrich_artist_for_run(
    *,
    run_id: str,
    artist_id: str,
    artist_name: str,
    adapters: list[VendorAdapter],
    merge_client: Any,
    merge_model: str,
    prompt: PromptConfig,
    repository: ArtistEnrichmentRepository,
    ai_flag_threshold: float,
    on_outcome: "Callable[[str, bool], None] | None" = None,
) -> None:
    """End-to-end: derive context, flip status, run vendors, persist cells + merged + counters."""
    context = repository.derive_artist_context(artist_id)
    repository.mark_run_running(run_id)

    cells = run_vendors_parallel(
        adapters=adapters,
        artist_name=artist_name,
        style=context.style,
        sample_tracks=context.sample_tracks,
        known_labels=context.known_labels,
        prompt=prompt,
    )

    ok = 0
    err = 0
    cost = 0.0
    for adapter, cell in zip(adapters, cells):
        response = _response_from_cell(cell, default_model=adapter.default_model)
        repository.insert_cell(run_id=run_id, artist_id=artist_id, vendor=adapter.name, response=response)
        if cell["error"] is None and cell["response"]["parsed"] is not None:
            ok += 1
        else:
            err += 1
        cost += float(cell["response"]["usage"].get("cost_usd") or 0.0)

    merged_info, meta = merge_cells(cells, merge_client, merge_model)
    cost += float(meta.get("narrative_cost_usd") or 0.0)

    repository.upsert_artist_info(
        artist_id=artist_id,
        last_run_id=run_id,
        prompt_slug=prompt.slug,
        prompt_version=prompt.version,
        merged=merged_info,
        provenance=meta.get("field_provenance") or {},
    )
    repository.project_ai_suspected(artist_id, merged_info, ai_flag_threshold)
    repository.increment_run_counters(run_id=run_id, ok_delta=ok, error_delta=err, cost_delta=cost)

    if on_outcome is not None:
        on_outcome(artist_id, ok > 0)


def _response_from_cell(cell: dict, default_model: str) -> VendorResponse:
    from .schemas import ArtistInfo

    parsed_payload = cell["response"]["parsed"]
    parsed = ArtistInfo.model_validate(parsed_payload) if parsed_payload else None
    return VendorResponse(
        parsed=parsed,
        raw={},
        citations=cell["response"].get("citations") or [],
        usage=cell["response"].get("usage") or {"input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0},
        latency_ms=cell["response"].get("latency_ms") or 0,
        model=cell["vendor"].get("model") or default_model,
        error=cell.get("error"),
    )


def build_adapters_from_run_config(
    *,
    vendor_names: list[str],
    models: dict[str, str],
    secrets: "ArtistEnrichmentSecrets",
    request_timeout_s: float,
) -> list[VendorAdapter]:
    """Instantiate the requested adapters (reused from label_enrichment.vendors) with per-run models."""
    from ..label_enrichment.vendors.gemini import GeminiAdapter
    from ..label_enrichment.vendors.openai_gpt import OpenAIAdapter
    from ..label_enrichment.vendors.tavily_deepseek import TavilyDeepSeekAdapter

    adapters: list[VendorAdapter] = []
    for name in vendor_names:
        model = models.get(name)
        if not model:
            raise ValueError(f"model missing for vendor {name!r}")
        if name == "gemini":
            adapters.append(GeminiAdapter(api_key=secrets.gemini_api_key, default_model=model, timeout_s=request_timeout_s))
        elif name == "openai":
            adapters.append(OpenAIAdapter(api_key=secrets.openai_api_key, default_model=model, timeout_s=request_timeout_s))
        elif name == "tavily_deepseek":
            adapters.append(TavilyDeepSeekAdapter(
                tavily_api_key=secrets.tavily_api_key,
                deepseek_api_key=secrets.deepseek_api_key,
                default_model=model,
                timeout_s=request_timeout_s,
            ))
        else:
            raise ValueError(f"unknown vendor {name!r}")
    return adapters
```

NOTE: `build_adapters_from_run_config` assumes the label vendor adapter constructor signatures (`GeminiAdapter(api_key, default_model, timeout_s)`, etc.). Confirm against `src/collector/label_enrichment/orchestrator.py:build_adapters_from_run_config` — they must match exactly since we reuse those classes.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd <repo> && PYTHONPATH=src <main-repo>/.venv/bin/pytest tests/unit/test_artist_enrichment_orchestrator.py -q`
Expected: PASS (1 passed). (Single-vendor → single-source merge path, no DeepSeek call.)

- [ ] **Step 5: Commit**

```bash
git add src/collector/artist_enrichment/orchestrator.py tests/unit/test_artist_enrichment_orchestrator.py
git commit -m "feat(artist-enrich): add orchestrator with context derivation"
```

---

## Task 8: SQS worker handler + integration test

**Files:**
- Create: `src/collector/artist_enrichment_handler.py`
- Create: `src/collector/artist_enrichment/messages.py` (only `ArtistEnrichmentMessage` in 1A; the HTTP request models are added in 1B)
- Test: `tests/integration/test_artist_enrichment_handler.py`

Mirror `label_enrichment_handler.py`. The SQS message carries `run_id`, `artist_id`, `artist_name` (no `style` — the worker derives context). Reuse the existing data-api + worker settings helpers.

- [ ] **Step 1: Write `messages.py` (1A subset)**

Create `src/collector/artist_enrichment/messages.py`:

```python
"""SQS message schema for artist enrichment (HTTP request models added in 1B)."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class ArtistEnrichmentMessage(BaseModel):
    """Body of one SQS message — one per artist, one Lambda invocation.

    The disambiguation context (style, sample_tracks, known_labels) is NOT
    carried here — the worker derives it from the artist's tracks.
    """

    model_config = ConfigDict(extra="ignore")

    run_id: str = Field(min_length=1)
    artist_id: str = Field(min_length=1)
    artist_name: str = Field(min_length=1)
```

- [ ] **Step 2: Write the failing integration test**

Create `tests/integration/test_artist_enrichment_handler.py`:

```python
import json

from collector import artist_enrichment_handler as handler_mod
from collector.artist_enrichment.repository import ArtistContext


class FakeRepo:
    def __init__(self):
        self.upserted = None
        self.projected = None
        self.counters = None

    def get_run(self, run_id):
        return {"vendors": ["openai"], "models": {"openai": "m"},
                "prompt_slug": "artist_v1", "merge_model": "deepseek-v4-flash"}

    def derive_artist_context(self, artist_id):
        return ArtistContext(style="techno", sample_tracks=["Hidden Beauties"], known_labels=["Drumcode"])

    def mark_run_running(self, run_id): pass
    def insert_cell(self, **kw): pass
    def upsert_artist_info(self, **kw): self.upserted = kw["artist_id"]
    def project_ai_suspected(self, artist_id, merged, threshold): self.projected = artist_id
    def increment_run_counters(self, **kw): self.counters = kw


class FakeAutoRepo:
    def __init__(self): self.outcomes = []
    def mark_auto_enrich_outcome(self, artist_id, success): self.outcomes.append((artist_id, success))


def test_handler_enriches_one_artist(monkeypatch):
    repo, auto = FakeRepo(), FakeAutoRepo()
    monkeypatch.setattr(handler_mod, "_build_clients", lambda: (repo, auto))

    class _Settings:
        gemini_api_key = openai_api_key = tavily_api_key = deepseek_api_key = "k"
        request_timeout_s = 30.0
        ai_flag_confidence_threshold = 0.7
    monkeypatch.setattr(handler_mod, "get_artist_enrichment_worker_settings", lambda: _Settings(), raising=False)
    monkeypatch.setattr(handler_mod, "_build_merge_client", lambda *a, **k: object())

    # Stub the vendor build + enrich on the HANDLER module (the handler imports
    # both names, so they are handler_mod attributes — patch them there).
    monkeypatch.setattr(handler_mod, "build_adapters_from_run_config", lambda **k: [])

    def fake_enrich(**kw):
        kw["repository"].upsert_artist_info(artist_id=kw["artist_id"], last_run_id="r",
                                            prompt_slug="artist_v1", prompt_version="v1",
                                            merged=object(), provenance={})
        if kw.get("on_outcome"):
            kw["on_outcome"](kw["artist_id"], True)
    monkeypatch.setattr(handler_mod, "enrich_artist_for_run", fake_enrich)

    event = {"Records": [{"body": json.dumps({"run_id": "r", "artist_id": "a", "artist_name": "ANNA"})}]}
    out = handler_mod.lambda_handler(event, None)
    assert out["processed"] == 1
    assert repo.upserted == "a"
    assert auto.outcomes == [("a", True)]
```

- [ ] **Step 3: Write the handler**

Create `src/collector/artist_enrichment_handler.py` by mirroring `src/collector/label_enrichment_handler.py` with these swaps: imports from `.artist_enrichment.*`; `ArtistEnrichmentMessage` (fields `run_id`/`artist_id`/`artist_name`); call `enrich_artist_for_run(run_id=..., artist_id=msg.artist_id, artist_name=msg.artist_name, adapters=..., merge_client=..., merge_model=run_row["merge_model"], prompt=..., repository=..., ai_flag_threshold=..., on_outcome=auto_repository.mark_auto_enrich_outcome)`. Build clients via `ArtistEnrichmentRepository` + the artist `AutoEnrichRepository` (added in 1C — for 1A, the handler imports it lazily; the integration test monkeypatches `_build_clients`, so the real auto-repo import is not exercised in 1A tests). Use `ArtistEnrichmentSecrets`.

For worker settings: add a thin `get_artist_enrichment_worker_settings()` to `src/collector/settings.py` that returns the same vendor keys + `request_timeout_s` + `ai_flag_confidence_threshold` as `get_label_enrichment_worker_settings()` (copy that function, rename; it reads the same SSM/env values — no label-specific field needed). If `get_label_enrichment_worker_settings` is already vendor-generic and carries no label-only required field, you may instead import and reuse it directly; prefer the rename for clarity.

The handler body mirrors the label handler exactly otherwise (parse records, `get_run`, decode vendors/models JSONB, `build_adapters_from_run_config`, `get_prompt`, `enrich_artist_for_run`, `log_event`). Provide the same `_build_clients`, `_build_merge_client` helpers (DeepSeek via OpenAI base_url).

NOTE: `_build_clients` returns `(ArtistEnrichmentRepository, AutoEnrichRepository)`. The artist `AutoEnrichRepository` is built in plan 1C. For 1A, import it inside `_build_clients` so the module imports cleanly; the integration test monkeypatches `_build_clients` and never hits the real auto-repo. If the import would fail at module load, guard it (lazy import inside the function — it already is).

- [ ] **Step 4: Run test to verify it passes**

Run: `cd <repo> && PYTHONPATH=src <main-repo>/.venv/bin/pytest tests/integration/test_artist_enrichment_handler.py -q`
Expected: PASS (1 passed).

- [ ] **Step 5: Run the full 1A suite**

Run: `cd <repo> && PYTHONPATH=src <main-repo>/.venv/bin/pytest tests/unit/test_artist_enrichment_*.py tests/integration/test_artist_enrichment_handler.py -q`
Expected: all pass (schemas 3 + prompts 3 + aggregator 15 + repository 8 + orchestrator 1 + handler 1 = 31).

- [ ] **Step 6: Commit**

```bash
git add src/collector/artist_enrichment_handler.py src/collector/artist_enrichment/messages.py tests/integration/test_artist_enrichment_handler.py
git commit -m "feat(artist-enrich): add SQS worker handler"
```

---

## Done criteria for plan 1A

- The full 1A suite passes (~31 tests), no live API calls.
- `clouder_artist_*` tables + prefs migration applies cleanly on the chain.
- `artist_enrichment_handler.lambda_handler` enriches one artist end-to-end against mocked vendors: derives context, writes cells, upserts `clouder_artist_info` (artist denorm columns), projects `clouder_artists.is_ai_suspected`, increments counters, fires the auto-outcome callback.
- No routes/OpenAPI/infra/auto-dispatch/preferences yet — those are plans 1B and 1C.

## Next: plan 1B (API surface)

Routes (`routes.py`/`auto_routes.py`), the HTTP request models in `messages.py`/`auto_messages.py`, the repository read/list/preference methods (`list_artists`, `list_backlog`, `list_runs`, `list_cells_for_run`, `list_history_for_artist`, `get_artist_info`, `get_artist_info_for_user`, `upsert_user_artist_pref`, `list_user_artist_prefs`), OpenAPI registration in `scripts/generate_openapi.py:ROUTES`, API Gateway routes, and dispatch in `collector/handler.py`. Then plan 1C: infra (SQS + worker Lambda + env wiring) + `auto_repository.py` (config/state/`claim_artists`/`artist_ids_for_track` all-roles) + auto-dispatch wiring into `curation_handler.py`.

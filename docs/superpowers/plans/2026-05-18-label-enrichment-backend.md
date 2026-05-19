# Label Enrichment Backend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the old Perplexity-only label search with a production multi-vendor enrichment pipeline (Gemini, OpenAI, Tavily+DeepSeek), persist merged LabelInfo per label in Aurora, expose admin HTTP endpoints, and run vendor calls asynchronously via SQS.

**Architecture:** API Lambda enqueues per-label SQS messages → worker Lambda calls vendors in parallel via `ThreadPoolExecutor` → aggregates with `merge_cells` (deterministic + DeepSeek narrative) → upserts `clouder_label_info`. Aurora via the RDS Data API only — no `psycopg` at runtime. Pipeline logic is copied verbatim from `experiments/labels/src/lab/`; adapters keep the never-raise contract.

**Tech Stack:** Python 3.12 (Pydantic v2, `google-genai`, `openai`, `httpx`), AWS Lambda + SQS + Aurora Serverless v2 (RDS Data API), Terraform.

**Spec:** `docs/superpowers/specs/2026-05-18-label-enrichment-backend-design.md` (commits `065a9df`, `7fe68e7`).

**Branch:** all commits land on `worktree-collect_info` (worktree of `main`).

**Commit policy:** Conventional Commits, scope-prefixed (`feat(backend)`, `chore(infra)`, `test(backend)`, etc.). Multi-line bodies use heredoc form. No `Co-Authored-By` trailer.

---

## File Structure

### Created

```
src/collector/label_enrichment/
├── __init__.py                       # empty
├── schemas.py                        # LabelInfo, AISignal, enums (ported)
├── messages.py                       # LabelEnrichmentMessage, EnrichLabelsRequestIn (Pydantic)
├── prompts/
│   ├── __init__.py                   # registry: register/get_prompt/load_builtin_prompts
│   ├── base.py                       # PromptConfig dataclass + render_user
│   ├── label_v2_facts.py             # ported
│   └── label_v3_app_fields.py        # ported
├── vendors/
│   ├── __init__.py                   # empty
│   ├── base.py                       # VendorAdapter Protocol + VendorResponse
│   ├── pricing.py                    # ported
│   ├── gemini.py                     # ported
│   ├── openai_gpt.py                 # ported
│   └── tavily_deepseek.py            # ported
├── aggregator.py                     # merge_cells (ported)
├── repository.py                     # Data API persistence
├── orchestrator.py                   # enrich_label_for_run + run_vendors_parallel
└── routes.py                         # _handle_enrich_post + _handle_get_run + _handle_get_label
src/collector/label_enrichment_handler.py  # SQS worker Lambda entrypoint

alembic/versions/20260518_21_drop_ai_search_results.py
alembic/versions/20260518_22_add_label_enrichment_tables.py

tests/unit/
├── test_label_enrichment_schemas.py
├── test_label_enrichment_prompts.py
├── test_label_enrichment_aggregator.py
├── test_label_enrichment_repository.py
├── test_label_enrichment_api.py
├── test_label_enrichment_worker.py
└── test_label_enrichment_messages.py
tests/integration/test_label_enrichment_e2e.py
```

### Modified

- `src/collector/handler.py` — register 3 new routes; drop `_enqueue_label_search`, `search_label_count` field, `search_labels_enqueued` response field, the `from .search.prompts import …` import.
- `src/collector/schemas.py` — drop `EntitySearchMessage`, `LabelSearchMessage`, `coerce_search_message`, `search_label_count` field on `AdminIngestRequestIn`.
- `src/collector/repositories.py` — drop `save_search_result`, `find_labels_needing_search`, `update_entity_is_ai_suspected`, `_AI_SUSPECTED_TABLES`.
- `src/collector/db_models.py` — drop `AISearchResult`.
- `src/collector/providers/registry.py` — drop `_build_perplexity_label`, `_build_perplexity_artist`, their `_BUILDERS` entries, `get_enricher_for_prompt`.
- `src/collector/settings.py` — drop `SearchWorkerSettings`, `get_search_worker_settings`; drop `ai_search_*` fields on `ApiSettings` and `WorkerSettings`; add `LabelEnrichmentWorkerSettings` + `get_label_enrichment_worker_settings`.
- `src/collector/worker_handler.py` — drop the `from .search.prompts import get_latest as get_latest_prompt` import (currently unused in worker_handler but present per the search code).
- `src/collector/requirements.txt` — add `google-genai`, `openai`, `httpx`.
- `scripts/generate_openapi.py` — add 3 new routes + request/response schemas to `ROUTES`.
- `infra/lambda.tf`, `infra/sqs.tf`, `infra/iam.tf`, `infra/alarms.tf`, `infra/variables.tf`, `infra/outputs.tf`, `infra/main.tf`, `infra/api_gateway.tf` — remove old `ai_search` resources, add `label_enricher` resources.

### Deleted

- `src/collector/search/` (whole package: `prompts.py`, `schemas.py`, `perplexity_client.py`, `__init__.py`)
- `src/collector/providers/perplexity/` (whole package: `label.py`, `artist.py`, `__init__.py`)
- `src/collector/search_handler.py`
- Tests targeting any of the above (see Phase 9).

---

## Phase 1 — Alembic migrations

### Task 1.1: Drop the legacy ai_search_results table

**Files:**
- Create: `alembic/versions/20260518_21_drop_ai_search_results.py`

- [ ] **Step 1: Inspect current head**

Run: `PYTHONPATH=src .venv/bin/python -c "from alembic.config import Config; from alembic.script import ScriptDirectory; print(ScriptDirectory.from_config(Config('alembic.ini')).get_current_head())"`
Expected: prints `20260512_20` (the latest existing revision is `20260512_20_playlist_status`).

- [ ] **Step 2: Write the migration**

```python
"""drop legacy ai_search_results table

Revision ID: 20260518_21
Revises: 20260512_20
Create Date: 2026-05-18 00:00:00
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "20260518_21"
down_revision = "20260512_20"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_index("uq_search_result", table_name="ai_search_results")
    op.drop_table("ai_search_results")


def downgrade() -> None:
    op.create_table(
        "ai_search_results",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("entity_type", sa.String(32), nullable=False),
        sa.Column("entity_id", sa.String(36), nullable=False),
        sa.Column("prompt_slug", sa.String(64), nullable=False),
        sa.Column("prompt_version", sa.String(16), nullable=False),
        sa.Column("result", JSONB, nullable=False),
        sa.Column("searched_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "uq_search_result",
        "ai_search_results",
        ["entity_type", "entity_id", "prompt_slug", "prompt_version"],
        unique=True,
    )
```

- [ ] **Step 3: Verify upgrade against a local Postgres**

Run:
```bash
export PYTHONPATH=src
export ALEMBIC_DATABASE_URL='postgresql+psycopg://postgres:postgres@localhost:5432/postgres'
alembic upgrade head
```
Expected: `20260518_21` is now head. `\d ai_search_results` in psql shows the table gone.

- [ ] **Step 4: Verify downgrade**

Run: `alembic downgrade -1 && alembic upgrade head`
Expected: table reappears then disappears without error.

- [ ] **Step 5: Commit**

```bash
git add alembic/versions/20260518_21_drop_ai_search_results.py
git commit -m "$(cat <<'EOF'
chore(data): drop legacy ai_search_results table

The old Perplexity-only label search pipeline is being replaced. The
table's data was a discontinued single-prompt cache with no FK
references — safe to drop without preservation.
EOF
)"
```

---

### Task 1.2: Add the three label-enrichment tables

**Files:**
- Create: `alembic/versions/20260518_22_add_label_enrichment_tables.py`

- [ ] **Step 1: Write the migration**

```python
"""add label enrichment tables (runs, cells, label_info)

Revision ID: 20260518_22
Revises: 20260518_21
Create Date: 2026-05-18 00:00:01
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import ARRAY, JSONB

revision = "20260518_22"
down_revision = "20260518_21"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "clouder_label_enrichment_runs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("status", sa.Text, nullable=False, server_default=sa.text("'queued'")),
        sa.Column("prompt_slug", sa.Text, nullable=False),
        sa.Column("prompt_version", sa.Text, nullable=False),
        sa.Column("vendors", JSONB, nullable=False),
        sa.Column("models", JSONB, nullable=False),
        sa.Column("merge_vendor", sa.Text, nullable=False),
        sa.Column("merge_model", sa.Text, nullable=False),
        sa.Column("requested_labels", sa.Integer, nullable=False),
        sa.Column("cells_total", sa.Integer, nullable=False),
        sa.Column("cells_ok", sa.Integer, nullable=False, server_default=sa.text("0")),
        sa.Column("cells_error", sa.Integer, nullable=False, server_default=sa.text("0")),
        sa.Column("cost_usd", sa.Numeric(10, 4), nullable=False, server_default=sa.text("0")),
        sa.Column("created_by_user_id", sa.String(36)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
    )
    op.create_index(
        "idx_label_enr_runs_created_at",
        "clouder_label_enrichment_runs",
        [sa.text("created_at DESC")],
    )

    op.create_table(
        "clouder_label_enrichment_cells",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "run_id",
            sa.String(36),
            sa.ForeignKey("clouder_label_enrichment_runs.id"),
            nullable=False,
        ),
        sa.Column(
            "label_id",
            sa.String(36),
            sa.ForeignKey("clouder_labels.id"),
            nullable=False,
        ),
        sa.Column("vendor", sa.Text, nullable=False),
        sa.Column("model", sa.Text, nullable=False),
        sa.Column("status", sa.Text, nullable=False),
        sa.Column("parsed", JSONB),
        sa.Column("citations", JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("usage", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("latency_ms", sa.Integer),
        sa.Column("error", JSONB),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("run_id", "label_id", "vendor", name="uq_label_enr_cell"),
    )
    op.create_index(
        "idx_label_enr_cells_label",
        "clouder_label_enrichment_cells",
        ["label_id", sa.text("created_at DESC")],
    )

    op.create_table(
        "clouder_label_info",
        sa.Column(
            "label_id",
            sa.String(36),
            sa.ForeignKey("clouder_labels.id"),
            primary_key=True,
        ),
        sa.Column(
            "last_run_id",
            sa.String(36),
            sa.ForeignKey("clouder_label_enrichment_runs.id"),
            nullable=False,
        ),
        sa.Column("prompt_slug", sa.Text, nullable=False),
        sa.Column("prompt_version", sa.Text, nullable=False),
        sa.Column("merged", JSONB, nullable=False),
        sa.Column("provenance", JSONB, nullable=False),
        sa.Column("ai_content", sa.Text, nullable=False),
        sa.Column("ai_confidence", sa.Numeric(3, 2), nullable=False),
        sa.Column("status", sa.Text, nullable=False),
        sa.Column(
            "primary_styles",
            ARRAY(sa.Text),
            nullable=False,
            server_default=sa.text("'{}'::text[]"),
        ),
        sa.Column("tagline", sa.Text),
        sa.Column("country", sa.Text),
        sa.Column("founded_year", sa.Integer),
        sa.Column("activity", sa.Text),
        sa.Column("last_release_date", sa.Date),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "idx_label_info_updated_at",
        "clouder_label_info",
        [sa.text("updated_at DESC")],
    )
    op.create_index("idx_label_info_status", "clouder_label_info", ["status"])
    op.create_index(
        "idx_label_info_primary_styles",
        "clouder_label_info",
        ["primary_styles"],
        postgresql_using="gin",
    )


def downgrade() -> None:
    op.drop_index("idx_label_info_primary_styles", table_name="clouder_label_info")
    op.drop_index("idx_label_info_status", table_name="clouder_label_info")
    op.drop_index("idx_label_info_updated_at", table_name="clouder_label_info")
    op.drop_table("clouder_label_info")

    op.drop_index("idx_label_enr_cells_label", table_name="clouder_label_enrichment_cells")
    op.drop_table("clouder_label_enrichment_cells")

    op.drop_index("idx_label_enr_runs_created_at", table_name="clouder_label_enrichment_runs")
    op.drop_table("clouder_label_enrichment_runs")
```

- [ ] **Step 2: Run upgrade**

Run: `alembic upgrade head`
Expected: 3 tables created, head = `20260518_22`.

- [ ] **Step 3: Run downgrade then re-upgrade**

Run: `alembic downgrade -1 && alembic upgrade head`
Expected: clean round-trip.

- [ ] **Step 4: Sanity-check columns in psql**

Run: `psql postgresql://postgres:postgres@localhost:5432/postgres -c "\\d clouder_label_info"`
Expected: shows `merged jsonb`, `provenance jsonb`, `primary_styles text[]`, indexes including `idx_label_info_primary_styles` of type `gin`.

- [ ] **Step 5: Commit**

```bash
git add alembic/versions/20260518_22_add_label_enrichment_tables.py
git commit -m "$(cat <<'EOF'
feat(data): add label-enrichment tables

Three tables for the new multi-vendor pipeline: runs (config + counters),
cells (per-vendor raw cell, idempotent on UNIQUE(run, label, vendor)),
label_info (single merged row per label, hybrid JSONB + denormalized
scalars). GIN index on primary_styles and B-tree on status support the
expected filter paths.
EOF
)"
```

---

## Phase 2 — Port the experiment pipeline

Goal: every file listed below is copied from `experiments/labels/src/lab/` into `src/collector/label_enrichment/` with imports adjusted. Each task ends with its own commit so the tree compiles incrementally.

### Task 2.1: Package skeleton

**Files:**
- Create: `src/collector/label_enrichment/__init__.py`
- Create: `src/collector/label_enrichment/prompts/__init__.py` (placeholder; the real registry lands in Task 2.3)
- Create: `src/collector/label_enrichment/vendors/__init__.py`

- [ ] **Step 1: Write the three empty package markers**

```python
# src/collector/label_enrichment/__init__.py
"""Label-enrichment subsystem: schemas, prompts, vendors, aggregator, orchestrator."""
```

```python
# src/collector/label_enrichment/vendors/__init__.py
"""Vendor adapters for label enrichment (gemini, openai, tavily_deepseek)."""
```

```python
# src/collector/label_enrichment/prompts/__init__.py
"""Prompt registry (populated by Task 2.3)."""
```

- [ ] **Step 2: Verify import works**

Run: `PYTHONPATH=src python3 -c "import collector.label_enrichment, collector.label_enrichment.prompts, collector.label_enrichment.vendors"`
Expected: no output, no error.

- [ ] **Step 3: Commit**

```bash
git add src/collector/label_enrichment/__init__.py \
        src/collector/label_enrichment/prompts/__init__.py \
        src/collector/label_enrichment/vendors/__init__.py
git commit -m "feat(backend): scaffold label_enrichment package"
```

---

### Task 2.2: Port the `LabelInfo` schema

**Files:**
- Create: `src/collector/label_enrichment/schemas.py`
- Create: `tests/unit/test_label_enrichment_schemas.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_label_enrichment_schemas.py
from collector.label_enrichment.schemas import (
    ActivityLevel,
    AIContentStatus,
    AISignal,
    AISignalKind,
    LabelInfo,
)


def test_label_info_minimal_round_trip():
    info = LabelInfo(
        label_name="Drumcode",
        ai_reasoning="No AI signals detected.",
        summary="Swedish techno label.",
        confidence=0.9,
    )
    dumped = info.model_dump()
    reloaded = LabelInfo.model_validate(dumped)
    assert reloaded.label_name == "Drumcode"
    assert reloaded.status == "unknown"  # default
    assert reloaded.activity == ActivityLevel.UNKNOWN
    assert reloaded.ai_content == AIContentStatus.UNKNOWN
    assert reloaded.primary_styles == []


def test_label_info_status_enum_validates():
    import pytest
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        LabelInfo(
            label_name="x",
            ai_reasoning="x",
            summary="x",
            confidence=0.5,
            status="hibernating",  # not in Literal
        )


def test_ai_signal_round_trip():
    sig = AISignal(
        kind=AISignalKind.VOLUME,
        description="Suspicious volume of releases.",
        source_url="https://example.com",
    )
    assert AISignal.model_validate(sig.model_dump()) == sig
```

- [ ] **Step 2: Run test — expect ImportError**

Run: `PYTHONPATH=src pytest tests/unit/test_label_enrichment_schemas.py -v`
Expected: collection error (`collector.label_enrichment.schemas` not yet a module).

- [ ] **Step 3: Implement by copying from the experiment**

Source: `experiments/labels/src/lab/schemas.py` (the `ActivityLevel`, `AIContentStatus`, `AISignalKind`, `AISignal`, `LabelInfo` definitions — lines 11-78).

Write `src/collector/label_enrichment/schemas.py` with **exactly the same** classes minus `Fixture`, `GroundTruth`, `FixturesFile` (sandbox-only):

```python
"""LabelInfo + AI signal data models for label enrichment."""

from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field


class ActivityLevel(str, Enum):
    UNKNOWN = "unknown"
    DORMANT = "dormant"
    LOW = "low"
    STEADY = "steady"
    HIGH = "high"
    FIRE_HOSE = "fire_hose"


class AIContentStatus(str, Enum):
    UNKNOWN = "unknown"
    NONE_DETECTED = "none_detected"
    SUSPECTED = "suspected"
    CONFIRMED = "confirmed"


class AISignalKind(str, Enum):
    VOLUME = "volume"
    ARTIST_GENERIC_NAMES = "artist_generic_names"
    COVER_ART = "cover_art"
    NAMED_IN_PRESS = "named_in_press"
    CREDITED_TOOL = "credited_tool"
    OTHER = "other"


class AISignal(BaseModel):
    kind: AISignalKind
    description: str
    source_url: str | None = None


class LabelInfo(BaseModel):
    label_name: str
    aliases: list[str] = Field(default_factory=list)
    parent_label: str | None = None
    sublabels: list[str] = Field(default_factory=list)
    country: str | None = None
    founded_year: int | None = None
    status: Literal["active", "inactive", "unknown"] = "unknown"
    tagline: str | None = None

    catalog_size_estimate: int | None = None
    roster_size_estimate: int | None = None
    releases_last_12_months: int | None = None
    last_release_date: str | None = None
    activity: ActivityLevel = ActivityLevel.UNKNOWN

    website: str | None = None
    bandcamp_url: str | None = None
    residentadvisor_url: str | None = None
    discogs_url: str | None = None
    beatport_url: str | None = None
    soundcloud_url: str | None = None
    instagram_url: str | None = None
    twitter_url: str | None = None

    notable_artists: list[str] = Field(default_factory=list)
    primary_styles: list[str] = Field(default_factory=list)
    distribution: str | None = None

    ai_content: AIContentStatus = AIContentStatus.UNKNOWN
    ai_signals: list[AISignal] = Field(default_factory=list)
    ai_reasoning: str

    summary: str
    confidence: float = Field(ge=0, le=1)
    sources: list[str] = Field(default_factory=list)
    notes: str | None = None
```

- [ ] **Step 4: Run tests, expect PASS**

Run: `PYTHONPATH=src pytest tests/unit/test_label_enrichment_schemas.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add src/collector/label_enrichment/schemas.py tests/unit/test_label_enrichment_schemas.py
git commit -m "feat(backend): port LabelInfo schema into label_enrichment"
```

---

### Task 2.3: Port the prompt registry and the two prompts we keep

**Files:**
- Replace: `src/collector/label_enrichment/prompts/__init__.py`
- Create: `src/collector/label_enrichment/prompts/base.py`
- Create: `src/collector/label_enrichment/prompts/label_v2_facts.py`
- Create: `src/collector/label_enrichment/prompts/label_v3_app_fields.py`
- Create: `tests/unit/test_label_enrichment_prompts.py`

Only `label_v2_facts` and `label_v3_app_fields` are ported; `label_v1_baseline` from the experiment is a control prompt and is intentionally dropped (we only ship the production-grade prompts).

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_label_enrichment_prompts.py
import pytest

from collector.label_enrichment.prompts import (
    PROMPTS,
    load_builtin_prompts,
    get_prompt,
)
from collector.label_enrichment.prompts.base import render_user
from collector.label_enrichment.schemas import LabelInfo


def setup_function(_):
    PROMPTS.clear()
    load_builtin_prompts()


def test_builtin_prompts_register():
    assert {"label_v2_facts", "label_v3_app_fields"} <= set(PROMPTS)
    assert "label_v1_baseline" not in PROMPTS


def test_label_v3_directives_present():
    cfg = get_prompt("label_v3_app_fields")
    assert cfg.version == "v1"
    assert cfg.schema is LabelInfo
    for directive in ("instagram_url", "tagline", "status", "primary_styles"):
        assert directive in cfg.system


def test_render_user_without_release():
    cfg = get_prompt("label_v2_facts")
    out = render_user(cfg, label_name="Drumcode", style="techno", release_name=None)
    assert 'Research label "Drumcode" in style "techno".' in out
    assert "Recent release" not in out


def test_render_user_with_release():
    cfg = get_prompt("label_v2_facts")
    out = render_user(
        cfg,
        label_name="Wisdom Teeth",
        style="bass",
        release_name="K-LONE - Cape Cira",
    )
    assert "Recent release: K-LONE - Cape Cira" in out


def test_get_prompt_unknown_raises():
    with pytest.raises(KeyError):
        get_prompt("nope")
```

- [ ] **Step 2: Run, expect ImportError**

Run: `PYTHONPATH=src pytest tests/unit/test_label_enrichment_prompts.py -v`
Expected: collection failure.

- [ ] **Step 3: Write `prompts/base.py`**

```python
# src/collector/label_enrichment/prompts/base.py
"""Prompt configuration and rendering helpers."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Type

from pydantic import BaseModel


@dataclass(frozen=True)
class PromptConfig:
    slug: str
    version: str
    description: str
    system: str
    user_template: str
    schema: Type[BaseModel]
    vendor_overrides: dict[str, str] = field(default_factory=dict)


def render_user(
    cfg: PromptConfig,
    label_name: str,
    style: str,
    release_name: str | None,
) -> str:
    release_block = (
        f"\nRecent release: {release_name}" if release_name else ""
    )
    return cfg.user_template.format(
        label_name=label_name,
        style=style,
        release_block=release_block,
    )
```

- [ ] **Step 4: Replace `prompts/__init__.py` with the registry**

```python
# src/collector/label_enrichment/prompts/__init__.py
"""Prompt registry (process-wide). Built-ins self-register on import."""

from __future__ import annotations

from .base import PromptConfig

PROMPTS: dict[str, PromptConfig] = {}
_BUILTIN_CONFIGS: list[PromptConfig] = []


def register(cfg: PromptConfig) -> None:
    if cfg.slug in PROMPTS:
        if PROMPTS[cfg.slug] is not cfg:
            raise ValueError(f"prompt {cfg.slug!r} already registered")
        return
    PROMPTS[cfg.slug] = cfg


def get_prompt(slug: str) -> PromptConfig:
    if slug not in PROMPTS:
        raise KeyError(f"prompt {slug!r} not found")
    return PROMPTS[slug]


def load_builtin_prompts() -> None:
    """Import the built-in prompt modules so they self-register."""
    global _BUILTIN_CONFIGS

    if not _BUILTIN_CONFIGS:
        before = set(PROMPTS)
        from . import label_v2_facts  # noqa: F401
        from . import label_v3_app_fields  # noqa: F401
        _BUILTIN_CONFIGS = [cfg for slug, cfg in PROMPTS.items() if slug not in before]

    for cfg in _BUILTIN_CONFIGS:
        register(cfg)
```

- [ ] **Step 5: Write `label_v2_facts.py` (verbatim from experiment, swap imports)**

```python
# src/collector/label_enrichment/prompts/label_v2_facts.py
"""label_v2_facts — facts-discipline prompt: numbers, sources, no guessing."""

from __future__ import annotations

from . import register
from .base import PromptConfig
from ..schemas import LabelInfo

SYSTEM = (
    "You research music labels. Output structured facts only.\n"
    "Rules:\n"
    "- Every numeric field (founded_year, catalog_size_estimate, "
    "roster_size_estimate, releases_last_12_months) requires at least one "
    "supporting URL in `sources`. If you cannot verify, leave the field "
    "null. Never guess numbers.\n"
    "- aliases, sublabels, parent_label: list everything you find, even "
    "uncertain ones, and mark uncertainty in `notes`.\n"
    "- `activity` is derived from `releases_last_12_months`: "
    "null/unknown -> unknown; 0 with last_release_date >2y ago -> dormant; "
    "<6 -> low; 6-24 -> steady; 25-60 -> high; >60 -> fire_hose. "
    "Do not set activity independently of releases_last_12_months.\n"
    "- notable_artists: at most 5, by recognizable name, not the full "
    "roster.\n"
    "- If the label name is ambiguous (multiple labels share the name), "
    "pick the one matching the style and explain the choice in `notes`.\n"
    "- confidence: 1.0 only if founded_year, country, and >=3 "
    "notable_artists are all sourced.\n"
    "- ai_reasoning is required even if status is unknown — explain why."
)

USER_TEMPLATE = (
    'Research label "{label_name}" in style "{style}".{release_block}\n'
    "Find: founding year, country, parent and sublabels, catalog and "
    "roster size, releases in the last 12 months, last release date, "
    "official channels (website, Bandcamp, Resident Advisor, Discogs, "
    "Beatport, SoundCloud), notable artists, distributor.\n"
    "Then assess AI-content status and explain your reasoning."
)


register(
    PromptConfig(
        slug="label_v2_facts",
        version="v1",
        description="Facts-discipline: numbers require sources, no guessing.",
        system=SYSTEM,
        user_template=USER_TEMPLATE,
        schema=LabelInfo,
    )
)
```

- [ ] **Step 6: Write `label_v3_app_fields.py` (verbatim)**

Copy the file contents shown for `experiments/labels/src/lab/prompts/label_v3_app_fields.py` verbatim into `src/collector/label_enrichment/prompts/label_v3_app_fields.py` — the file already uses relative imports (`from . import register`, `from ..schemas import LabelInfo`) that resolve correctly under the new package.

- [ ] **Step 7: Run tests, expect PASS**

Run: `PYTHONPATH=src pytest tests/unit/test_label_enrichment_prompts.py -v`
Expected: 5 passed.

- [ ] **Step 8: Commit**

```bash
git add src/collector/label_enrichment/prompts/ tests/unit/test_label_enrichment_prompts.py
git commit -m "$(cat <<'EOF'
feat(backend): port v2/v3 prompt registry into label_enrichment

Drops the v1 baseline (sandbox-only control prompt). Two production
prompts ship: label_v2_facts (numbers require sources) and
label_v3_app_fields (adds tagline, status, primary_styles, social URLs).
EOF
)"
```

---

### Task 2.4: Port the vendor base contract and pricing

**Files:**
- Create: `src/collector/label_enrichment/vendors/base.py`
- Create: `src/collector/label_enrichment/vendors/pricing.py`
- Create: `tests/unit/test_label_enrichment_pricing.py`

- [ ] **Step 1: Write failing test**

```python
# tests/unit/test_label_enrichment_pricing.py
from collector.label_enrichment.vendors.pricing import estimate_cost


def test_known_model():
    # gemini-3-flash-preview: 0.50 in, 3.00 out per 1M tokens
    assert estimate_cost("gemini-3-flash-preview", 1_000_000, 1_000_000) == 3.50


def test_unknown_model_zero():
    assert estimate_cost("unknown-xyz", 1_000_000, 1_000_000) == 0.0


def test_fractional_tokens():
    # gpt-5.4-mini: 0.25 in, 2.00 out per 1M
    cost = estimate_cost("gpt-5.4-mini", 100_000, 50_000)
    assert abs(cost - (0.025 + 0.1)) < 1e-9
```

- [ ] **Step 2: Run test — expect ImportError**

Run: `PYTHONPATH=src pytest tests/unit/test_label_enrichment_pricing.py -v`
Expected: collection failure.

- [ ] **Step 3: Write `vendors/base.py` (verbatim port)**

```python
# src/collector/label_enrichment/vendors/base.py
"""Vendor adapter protocol and response container."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, Type

from pydantic import BaseModel


@dataclass
class VendorResponse:
    parsed: BaseModel | None
    raw: dict
    citations: list[str]
    usage: dict          # {"input_tokens": int, "output_tokens": int, "cost_usd": float}
    latency_ms: int
    model: str
    error: str | None = None


class VendorAdapter(Protocol):
    name: str
    default_model: str
    supports_web_search: bool

    def run(
        self,
        system: str,
        user: str,
        schema: Type[BaseModel],
        model: str | None = None,
    ) -> VendorResponse: ...
```

- [ ] **Step 4: Write `vendors/pricing.py` (verbatim port — drop Anthropic/xAI/Perplexity entries since we don't ship those vendors)**

```python
# src/collector/label_enrichment/vendors/pricing.py
"""Approximate per-model pricing in USD per million tokens.

Values are informational only — used to compute cost estimates that
accumulate into the run row's cost_usd column.
"""

from __future__ import annotations

PRICING: dict[str, tuple[float, float]] = {
    # Google Gemini
    "gemini-2.5-flash": (0.30, 2.50),
    "gemini-2.5-pro":   (1.25, 10.0),
    "gemini-3-flash-preview": (0.50, 3.00),
    "gemini-3-pro-preview":   (2.00, 12.00),
    "gemini-3.1-pro-preview": (2.00, 12.00),

    # OpenAI GPT
    "gpt-5-mini":   (0.25, 2.00),
    "gpt-5":        (1.25, 10.0),
    "gpt-5-nano":   (0.05, 0.40),
    "gpt-5.4-mini": (0.25, 2.00),
    "gpt-5.4":      (1.25, 10.00),
    "gpt-5.4-nano": (0.05, 0.40),

    # DeepSeek (used for Tavily synthesis stage AND the narrative merge)
    "deepseek-v4-flash": (0.14, 0.28),
    "deepseek-v4-pro":   (0.435, 0.87),
    "deepseek-chat":     (0.14, 0.28),
}


def estimate_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    if model not in PRICING:
        return 0.0
    in_rate, out_rate = PRICING[model]
    return (input_tokens / 1_000_000) * in_rate + (output_tokens / 1_000_000) * out_rate
```

- [ ] **Step 5: Run tests, expect PASS**

Run: `PYTHONPATH=src pytest tests/unit/test_label_enrichment_pricing.py -v`
Expected: 3 passed.

- [ ] **Step 6: Commit**

```bash
git add src/collector/label_enrichment/vendors/base.py \
        src/collector/label_enrichment/vendors/pricing.py \
        tests/unit/test_label_enrichment_pricing.py
git commit -m "feat(backend): port vendor protocol and pricing table"
```

---

### Task 2.5: Port the Gemini adapter

**Files:**
- Create: `src/collector/label_enrichment/vendors/gemini.py`
- Create: `tests/unit/test_label_enrichment_vendor_gemini.py`

- [ ] **Step 1: Write failing test (mocks the `google-genai` client)**

```python
# tests/unit/test_label_enrichment_vendor_gemini.py
from types import SimpleNamespace
from unittest.mock import MagicMock

from collector.label_enrichment.schemas import LabelInfo
from collector.label_enrichment.vendors.gemini import GeminiAdapter


def _fake_response(text: str, in_tok: int = 100, out_tok: int = 50) -> SimpleNamespace:
    usage = SimpleNamespace(prompt_token_count=in_tok, candidates_token_count=out_tok)
    return SimpleNamespace(text=text, usage_metadata=usage, candidates=[])


def test_gemini_parses_valid_payload():
    payload = (
        '{"label_name":"Drumcode","ai_reasoning":"none","summary":"techno","confidence":0.9}'
    )
    client = MagicMock()
    client.models.generate_content.return_value = _fake_response(payload)
    adapter = GeminiAdapter(api_key="x", default_model="gemini-3-flash-preview", client=client)

    resp = adapter.run(system="sys", user="user", schema=LabelInfo)

    assert resp.error is None
    assert resp.parsed.label_name == "Drumcode"
    assert resp.usage["input_tokens"] == 100
    assert resp.usage["output_tokens"] == 50
    assert resp.usage["cost_usd"] > 0.0


def test_gemini_returns_error_on_api_exception():
    client = MagicMock()
    client.models.generate_content.side_effect = RuntimeError("boom")
    adapter = GeminiAdapter(api_key="x", default_model="gemini-3-flash-preview", client=client)

    resp = adapter.run(system="sys", user="user", schema=LabelInfo)

    assert resp.parsed is None
    assert "RuntimeError" in resp.error
    assert resp.usage["cost_usd"] == 0.0


def test_gemini_handles_fenced_json():
    fenced = "```json\n{\"label_name\":\"X\",\"ai_reasoning\":\"r\",\"summary\":\"s\",\"confidence\":0.1}\n```"
    client = MagicMock()
    client.models.generate_content.return_value = _fake_response(fenced)
    adapter = GeminiAdapter(api_key="x", default_model="gemini-3-flash-preview", client=client)

    resp = adapter.run(system="sys", user="user", schema=LabelInfo)
    assert resp.error is None
    assert resp.parsed.label_name == "X"
```

- [ ] **Step 2: Run test — expect ImportError**

Run: `PYTHONPATH=src pytest tests/unit/test_label_enrichment_vendor_gemini.py -v`
Expected: collection failure.

- [ ] **Step 3: Port the adapter from `experiments/labels/src/lab/vendors/gemini_flash.py`**

Write `src/collector/label_enrichment/vendors/gemini.py` with these surgical adjustments to the experiment copy:

1. Rename class `GeminiFlashAdapter` → `GeminiAdapter`.
2. Use `from .base import VendorResponse` and `from .pricing import estimate_cost` (the imports are already `from .base import …` in the experiment — no path change needed).
3. Keep the entire retry block (`is_quota`, `is_unavailable`, `_parse_retry_delay`, etc.) and `_extract_json` helper verbatim — they handle Gemini's 429 / 503 / fenced output quirks documented in the experiment's commit history.

The full file body matches `experiments/labels/src/lab/vendors/gemini_flash.py` lines 1-201 with the class renamed; reproduce it verbatim in the new file.

- [ ] **Step 4: Run tests, expect PASS**

Run: `PYTHONPATH=src pytest tests/unit/test_label_enrichment_vendor_gemini.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add src/collector/label_enrichment/vendors/gemini.py tests/unit/test_label_enrichment_vendor_gemini.py
git commit -m "$(cat <<'EOF'
feat(backend): port Gemini vendor adapter

Keeps the experiment's never-raise contract, 429/503 retry loop with
retryDelay parsing, and fence-aware JSON extraction. Renamed
GeminiFlashAdapter -> GeminiAdapter to drop the "Flash" branding now
that the model is a runtime parameter, not a hard-coded class trait.
EOF
)"
```

---

### Task 2.6: Port the OpenAI adapter

**Files:**
- Create: `src/collector/label_enrichment/vendors/openai_gpt.py`
- Create: `tests/unit/test_label_enrichment_vendor_openai.py`

- [ ] **Step 1: Write failing test**

```python
# tests/unit/test_label_enrichment_vendor_openai.py
from types import SimpleNamespace
from unittest.mock import MagicMock

from collector.label_enrichment.schemas import LabelInfo
from collector.label_enrichment.vendors.openai_gpt import OpenAIAdapter


def _fake_parsed() -> LabelInfo:
    return LabelInfo(
        label_name="Drumcode",
        ai_reasoning="none",
        summary="techno",
        confidence=0.9,
    )


def test_openai_uses_output_parsed():
    parsed = _fake_parsed()
    usage = SimpleNamespace(input_tokens=200, output_tokens=80)
    response = SimpleNamespace(
        output_parsed=parsed, usage=usage, citations=[], output=[]
    )
    client = MagicMock()
    client.responses.parse.return_value = response
    adapter = OpenAIAdapter(api_key="x", default_model="gpt-5.4-mini", client=client)

    resp = adapter.run(system="sys", user="user", schema=LabelInfo)
    assert resp.error is None
    assert resp.parsed.label_name == "Drumcode"
    assert resp.usage["input_tokens"] == 200
    assert resp.usage["cost_usd"] > 0.0


def test_openai_returns_error_when_no_parsed():
    response = SimpleNamespace(
        output_parsed=None, usage=None, citations=[], output=[]
    )
    client = MagicMock()
    client.responses.parse.return_value = response
    adapter = OpenAIAdapter(api_key="x", default_model="gpt-5.4-mini", client=client)

    resp = adapter.run(system="sys", user="user", schema=LabelInfo)
    assert resp.parsed is None
    assert "no output_parsed" in resp.error


def test_openai_returns_error_on_api_exception():
    client = MagicMock()
    client.responses.parse.side_effect = RuntimeError("rate limited")
    adapter = OpenAIAdapter(api_key="x", default_model="gpt-5.4-mini", client=client)

    resp = adapter.run(system="sys", user="user", schema=LabelInfo)
    assert resp.parsed is None
    assert "RuntimeError" in resp.error
```

- [ ] **Step 2: Run test — expect ImportError**

Run: `PYTHONPATH=src pytest tests/unit/test_label_enrichment_vendor_openai.py -v`
Expected: collection failure.

- [ ] **Step 3: Port from `experiments/labels/src/lab/vendors/openai_gpt.py`**

Write `src/collector/label_enrichment/vendors/openai_gpt.py` verbatim from the experiment, with one rename: `OpenAIGPTAdapter` → `OpenAIAdapter`. Imports (`from .base import VendorResponse`, `from .pricing import estimate_cost`) already resolve correctly.

- [ ] **Step 4: Run tests, expect PASS**

Run: `PYTHONPATH=src pytest tests/unit/test_label_enrichment_vendor_openai.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add src/collector/label_enrichment/vendors/openai_gpt.py tests/unit/test_label_enrichment_vendor_openai.py
git commit -m "feat(backend): port OpenAI vendor adapter"
```

---

### Task 2.7: Port the Tavily+DeepSeek two-stage adapter

**Files:**
- Create: `src/collector/label_enrichment/vendors/tavily_deepseek.py`
- Create: `tests/unit/test_label_enrichment_vendor_tavily.py`

- [ ] **Step 1: Write failing test**

```python
# tests/unit/test_label_enrichment_vendor_tavily.py
import json
from types import SimpleNamespace
from unittest.mock import MagicMock

from collector.label_enrichment.schemas import LabelInfo
from collector.label_enrichment.vendors.tavily_deepseek import (
    TavilyDeepSeekAdapter,
    _build_search_query,
)


def test_search_query_extracts_quoted_label():
    user = 'Research label "Drumcode" in style "techno".\nFind: ...'
    assert _build_search_query(user) == '"Drumcode" techno music label'


def test_search_query_fallback_when_unquoted():
    assert _build_search_query("plain text") == "plain text"


def test_tavily_deepseek_happy_path():
    payload = {
        "label_name": "Drumcode",
        "ai_reasoning": "none",
        "summary": "Swedish techno",
        "confidence": 0.95,
    }
    tavily_resp = SimpleNamespace(
        raise_for_status=lambda: None,
        json=lambda: {"results": [{"url": "https://example.com", "title": "t", "content": "c"}]},
    )
    http = MagicMock()
    http.post.return_value = tavily_resp

    llm_resp = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(payload)))],
        usage=SimpleNamespace(prompt_tokens=300, completion_tokens=120),
    )
    llm = MagicMock()
    llm.chat.completions.create.return_value = llm_resp

    adapter = TavilyDeepSeekAdapter(
        tavily_api_key="t",
        deepseek_api_key="d",
        default_model="deepseek-v4-flash",
        http_client=http,
        llm_client=llm,
    )
    resp = adapter.run(system="sys", user='Research label "Drumcode" in style "techno".', schema=LabelInfo)

    assert resp.error is None
    assert resp.parsed.label_name == "Drumcode"
    assert resp.citations == ["https://example.com"]
    assert resp.usage["cost_usd"] > 0.0


def test_tavily_failure_returns_error_cell():
    http = MagicMock()
    http.post.side_effect = RuntimeError("network down")
    llm = MagicMock()
    adapter = TavilyDeepSeekAdapter(
        tavily_api_key="t",
        deepseek_api_key="d",
        default_model="deepseek-v4-flash",
        http_client=http,
        llm_client=llm,
    )
    resp = adapter.run(system="sys", user='Research label "X" in style "y".', schema=LabelInfo)
    assert resp.parsed is None
    assert "tavily error" in resp.error
    llm.chat.completions.create.assert_not_called()
```

- [ ] **Step 2: Run test — expect ImportError**

Run: `PYTHONPATH=src pytest tests/unit/test_label_enrichment_vendor_tavily.py -v`
Expected: collection failure.

- [ ] **Step 3: Port from `experiments/labels/src/lab/vendors/tavily_deepseek.py`**

Copy the entire file verbatim into `src/collector/label_enrichment/vendors/tavily_deepseek.py`. Class name (`TavilyDeepSeekAdapter`) stays; imports resolve.

- [ ] **Step 4: Run tests, expect PASS**

Run: `PYTHONPATH=src pytest tests/unit/test_label_enrichment_vendor_tavily.py -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add src/collector/label_enrichment/vendors/tavily_deepseek.py tests/unit/test_label_enrichment_vendor_tavily.py
git commit -m "$(cat <<'EOF'
feat(backend): port Tavily+DeepSeek two-stage vendor

Stage 1: Tavily search (general pass + social-domain pass merged by URL).
Stage 2: DeepSeek synthesises the snippets into structured JSON.
Both stages keep the never-raise contract.
EOF
)"
```

---

### Task 2.8: Port the aggregator (`merge_cells`)

**Files:**
- Create: `src/collector/label_enrichment/aggregator.py`
- Create: `tests/unit/test_label_enrichment_aggregator.py`

- [ ] **Step 1: Write failing test**

```python
# tests/unit/test_label_enrichment_aggregator.py
import json
from types import SimpleNamespace
from unittest.mock import MagicMock

from collector.label_enrichment.aggregator import (
    merge_cells,
    _filter_parseable,
    _merge_deterministic,
)


def _cell(vendor: str, parsed: dict | None, error: str | None = None) -> dict:
    return {
        "run_id": "r",
        "prompt": {"slug": "label_v3_app_fields", "version": "v1"},
        "vendor": {"name": vendor, "model": f"{vendor}-model"},
        "fixture": {"label_name": parsed.get("label_name", "") if parsed else ""},
        "response": {
            "parsed": parsed,
            "citations": [],
            "usage": {"input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0},
            "latency_ms": 100,
            "raw": {},
        },
        "error": error,
    }


def _base_parsed(**over) -> dict:
    base = {
        "label_name": "Drumcode",
        "ai_reasoning": "none",
        "summary": "techno",
        "confidence": 0.9,
        "country": "Sweden",
        "founded_year": 1996,
        "primary_styles": ["techno"],
        "notable_artists": ["Adam Beyer"],
        "ai_content": "none_detected",
        "status": "active",
        "activity": "steady",
    }
    base.update(over)
    return base


def _fake_deepseek_client(payload: dict):
    client = MagicMock()
    client.chat.completions.create.return_value = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(payload)))],
        usage=SimpleNamespace(prompt_tokens=300, completion_tokens=120),
    )
    return client


def test_filter_parseable_drops_errors_and_nulls():
    cells = [
        _cell("gemini", _base_parsed()),
        _cell("openai", None, error="boom"),
        _cell("tavily_deepseek", None),
    ]
    assert len(_filter_parseable(cells)) == 1


def test_deterministic_median_numeric():
    cells = [
        _cell("gemini", _base_parsed(founded_year=1996, catalog_size_estimate=500)),
        _cell("openai", _base_parsed(founded_year=1996, catalog_size_estimate=600)),
    ]
    merged, prov = _merge_deterministic(cells)
    assert merged["founded_year"] == 1996
    assert merged["catalog_size_estimate"] == 550
    assert prov["catalog_size_estimate"].startswith("median:")


def test_majority_with_unknown_abstention():
    cells = [
        _cell("gemini", _base_parsed(status="active")),
        _cell("openai", _base_parsed(status="unknown")),
        _cell("tavily_deepseek", _base_parsed(status="active")),
    ]
    merged, prov = _merge_deterministic(cells)
    assert merged["status"] == "active"
    assert "majority" in prov["status"] or "only definitive" in prov["status"]


def test_merge_cells_single_source_short_circuit():
    cells = [_cell("gemini", _base_parsed())]
    client = _fake_deepseek_client({})  # should NOT be called
    info, meta = merge_cells(cells, client)
    assert info.label_name == "Drumcode"
    assert meta["source_count"] == 1
    client.chat.completions.create.assert_not_called()


def test_merge_cells_multiple_sources_runs_narrative():
    cells = [
        _cell("gemini", _base_parsed()),
        _cell("openai", _base_parsed(summary="alt")),
    ]
    client = _fake_deepseek_client({
        "tagline": "Tag.",
        "summary": "Merged summary.",
        "ai_reasoning": "merged reasoning",
        "notes": None,
    })
    info, meta = merge_cells(cells, client)
    assert info.summary == "Merged summary."
    assert meta["source_count"] == 2
    assert "deepseek narrative" in meta["field_provenance"]["summary"]


def test_merge_cells_narrative_failure_falls_back():
    cells = [
        _cell("gemini", _base_parsed(confidence=0.9)),
        _cell("openai", _base_parsed(confidence=0.7, summary="LOW")),
    ]
    client = MagicMock()
    client.chat.completions.create.side_effect = RuntimeError("deepseek down")
    info, meta = merge_cells(cells, client)
    assert info.summary == "techno"  # max-confidence cell's summary
    assert meta.get("narrative_fallback") == "max_confidence"


def test_merge_cells_all_failed():
    cells = [
        _cell("gemini", None, error="boom"),
        _cell("openai", None, error="boom"),
    ]
    client = MagicMock()
    info, meta = merge_cells(cells, client)
    assert info.summary == "All vendor sources failed."
    assert meta["all_failed"] is True
    client.chat.completions.create.assert_not_called()
```

- [ ] **Step 2: Run test — expect ImportError**

Run: `PYTHONPATH=src pytest tests/unit/test_label_enrichment_aggregator.py -v`
Expected: collection failure.

- [ ] **Step 3: Port from `experiments/labels/src/lab/aggregate.py`**

Copy verbatim into `src/collector/label_enrichment/aggregator.py`. Swap imports:
- `from .schemas import LabelInfo` (already correct).
- Remove the `from .vendors.pricing import estimate_cost` import — `aggregate.py` imports it but does **not** call it (the cost accounting is on the narrative caller). Confirm by `grep estimate_cost experiments/labels/src/lab/aggregate.py` (returns the import line only). Drop the unused import.

- [ ] **Step 4: Run tests, expect PASS**

Run: `PYTHONPATH=src pytest tests/unit/test_label_enrichment_aggregator.py -v`
Expected: 7 passed.

- [ ] **Step 5: Commit**

```bash
git add src/collector/label_enrichment/aggregator.py tests/unit/test_label_enrichment_aggregator.py
git commit -m "$(cat <<'EOF'
feat(backend): port consensus aggregator into label_enrichment

merge_cells handles: zero-parseable (all_failed payload), single
parseable (skip merge), and multi-vendor (deterministic + DeepSeek
narrative with max-confidence fallback on failure). Provenance strings
are written into the meta.field_provenance dict for the worker to
persist alongside merged.
EOF
)"
```

---

## Phase 3 — Settings

### Task 3.1: Add `LabelEnrichmentWorkerSettings`

**Files:**
- Modify: `src/collector/settings.py`
- Create: `tests/unit/test_label_enrichment_settings.py`

- [ ] **Step 1: Write failing test**

```python
# tests/unit/test_label_enrichment_settings.py
import os

import pytest

from collector.settings import (
    LabelEnrichmentWorkerSettings,
    get_label_enrichment_worker_settings,
    reset_settings_cache,
)


@pytest.fixture(autouse=True)
def _isolate(monkeypatch):
    for key in (
        "GEMINI_API_KEY", "OPENAI_API_KEY", "TAVILY_API_KEY", "DEEPSEEK_API_KEY",
        "AI_FLAG_CONFIDENCE_THRESHOLD",
        "GEMINI_API_KEY_SECRET_ARN", "OPENAI_API_KEY_SECRET_ARN",
        "TAVILY_API_KEY_SECRET_ARN", "DEEPSEEK_API_KEY_SECRET_ARN",
    ):
        monkeypatch.delenv(key, raising=False)
    reset_settings_cache()
    yield
    reset_settings_cache()


def test_settings_resolve_from_direct_env(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "g")
    monkeypatch.setenv("OPENAI_API_KEY", "o")
    monkeypatch.setenv("TAVILY_API_KEY", "t")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "d")
    s = get_label_enrichment_worker_settings()
    assert s.gemini_api_key == "g"
    assert s.openai_api_key == "o"
    assert s.tavily_api_key == "t"
    assert s.deepseek_api_key == "d"
    assert s.ai_flag_confidence_threshold == 0.5
    assert s.request_timeout_s == 120.0


def test_threshold_override(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "x")
    monkeypatch.setenv("OPENAI_API_KEY", "x")
    monkeypatch.setenv("TAVILY_API_KEY", "x")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "x")
    monkeypatch.setenv("AI_FLAG_CONFIDENCE_THRESHOLD", "0.75")
    s = get_label_enrichment_worker_settings()
    assert s.ai_flag_confidence_threshold == 0.75
```

- [ ] **Step 2: Run, expect failure**

Run: `PYTHONPATH=src pytest tests/unit/test_label_enrichment_settings.py -v`
Expected: `ImportError: cannot import name 'LabelEnrichmentWorkerSettings'`.

- [ ] **Step 3: Add the settings class and resolver to `src/collector/settings.py`**

Edit `src/collector/settings.py`:

Add the class after `VendorMatchSettings` (the existing position roughly at line ~200):

```python
class LabelEnrichmentWorkerSettings(_SettingsBase):
    gemini_api_key: str = Field(default="")
    openai_api_key: str = Field(default="")
    tavily_api_key: str = Field(default="")
    deepseek_api_key: str = Field(default="")
    ai_flag_confidence_threshold: float = Field(
        default=0.5, alias="AI_FLAG_CONFIDENCE_THRESHOLD", ge=0.0, le=1.0,
    )
    request_timeout_s: float = Field(
        default=120.0, alias="LABEL_ENRICHMENT_REQUEST_TIMEOUT_S", ge=1.0,
    )
    label_enrichment_queue_url: str = Field(
        default="", alias="LABEL_ENRICHMENT_QUEUE_URL",
    )
```

Add the resolver immediately after `get_search_worker_settings` (which Phase 9 will delete; the function order doesn't matter):

```python
@functools.lru_cache
def get_label_enrichment_worker_settings() -> LabelEnrichmentWorkerSettings:
    gemini = _resolve_simple_secret("GEMINI_API_KEY", "GEMINI_API_KEY_SECRET_ARN")
    openai = _resolve_simple_secret("OPENAI_API_KEY", "OPENAI_API_KEY_SECRET_ARN")
    tavily = _resolve_simple_secret("TAVILY_API_KEY", "TAVILY_API_KEY_SECRET_ARN")
    deepseek = _resolve_simple_secret("DEEPSEEK_API_KEY", "DEEPSEEK_API_KEY_SECRET_ARN")
    return LabelEnrichmentWorkerSettings(
        gemini_api_key=gemini,
        openai_api_key=openai,
        tavily_api_key=tavily,
        deepseek_api_key=deepseek,
    )
```

Add to `reset_settings_cache()`:
```python
    get_label_enrichment_worker_settings.cache_clear()
```

- [ ] **Step 4: Run tests, expect PASS**

Run: `PYTHONPATH=src pytest tests/unit/test_label_enrichment_settings.py -v`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add src/collector/settings.py tests/unit/test_label_enrichment_settings.py
git commit -m "$(cat <<'EOF'
feat(backend): add LabelEnrichmentWorkerSettings

Resolves Gemini/OpenAI/Tavily/DeepSeek API keys via the existing direct-env
> SSM > Secrets Manager precedence (same as PERPLEXITY_API_KEY today).
AI flag projection threshold defaults to 0.5; request timeout to 120s.
EOF
)"
```

---

## Phase 4 — Repository (Aurora Data API)

The repository file is built in five focused tasks so each method is testable in isolation against a mocked Data API client. All tasks edit the same file `src/collector/label_enrichment/repository.py` — keep your editor open on it across tasks.

### Task 4.1: Skeleton + `upsert_label_by_name` + `create_run` + `get_run`

**Files:**
- Create: `src/collector/label_enrichment/repository.py`
- Create: `tests/unit/test_label_enrichment_repository.py`

- [ ] **Step 1: Write failing test**

```python
# tests/unit/test_label_enrichment_repository.py
from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from collector.label_enrichment.repository import (
    LabelEnrichmentRepository,
    RunSpec,
)


def _now():
    return datetime(2026, 5, 18, 21, 0, 0, tzinfo=timezone.utc)


def _repo_with_fake():
    data_api = MagicMock()
    repo = LabelEnrichmentRepository(data_api=data_api, now=_now)
    return repo, data_api


def test_create_run_inserts_with_correct_cells_total():
    repo, data_api = _repo_with_fake()
    data_api.execute.return_value = []  # INSERT returns no rows

    spec = RunSpec(
        prompt_slug="label_v3_app_fields",
        prompt_version="v1",
        vendors=["gemini", "openai", "tavily_deepseek"],
        models={"gemini": "gemini-3-flash-preview", "openai": "gpt-5.4-mini",
                "tavily_deepseek": "deepseek-v4-flash"},
        merge_vendor="deepseek",
        merge_model="deepseek-v4-flash",
        requested_labels=4,
        created_by_user_id="user-1",
    )
    run_id = repo.create_run(spec)

    assert isinstance(run_id, str) and len(run_id) == 36
    sql, params = data_api.execute.call_args[0]
    assert "INSERT INTO clouder_label_enrichment_runs" in sql
    assert params["cells_total"] == 4 * 3
    assert params["requested_labels"] == 4
    assert params["status"] == "queued"


def test_upsert_label_by_name_returns_existing_id():
    repo, data_api = _repo_with_fake()
    data_api.execute.side_effect = [
        [{"id": "existing-id"}],   # SELECT match
    ]
    label_id = repo.upsert_label_by_name("Drumcode")
    assert label_id == "existing-id"


def test_upsert_label_by_name_creates_new_row_when_missing():
    repo, data_api = _repo_with_fake()
    data_api.execute.side_effect = [
        [],                        # SELECT no match
        [],                        # INSERT
    ]
    label_id = repo.upsert_label_by_name("Brand New Label")
    assert isinstance(label_id, str) and len(label_id) == 36
    insert_sql, insert_params = data_api.execute.call_args_list[1][0]
    assert "INSERT INTO clouder_labels" in insert_sql
    assert insert_params["name"] == "Brand New Label"
    assert insert_params["normalized_name"] == "brand new label"


def test_get_run_returns_dict_or_none():
    repo, data_api = _repo_with_fake()
    data_api.execute.return_value = [{
        "id": "r1", "status": "running", "prompt_slug": "label_v3_app_fields",
        "prompt_version": "v1", "vendors": ["gemini"], "models": {"gemini": "x"},
        "merge_vendor": "deepseek", "merge_model": "deepseek-v4-flash",
        "requested_labels": 1, "cells_total": 1, "cells_ok": 0, "cells_error": 0,
        "cost_usd": 0,
    }]
    row = repo.get_run("r1")
    assert row["id"] == "r1"

    data_api.execute.return_value = []
    assert repo.get_run("missing") is None
```

- [ ] **Step 2: Run, expect failure**

Run: `PYTHONPATH=src pytest tests/unit/test_label_enrichment_repository.py -v`
Expected: collection failure.

- [ ] **Step 3: Implement the skeleton with the three methods**

```python
# src/collector/label_enrichment/repository.py
"""Aurora Data API persistence for label enrichment."""

from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Callable, Mapping

from ..data_api import DataAPIClient


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


_NORM_RE = re.compile(r"\s+")


def _normalize_label(name: str) -> str:
    return _NORM_RE.sub(" ", name.strip().lower())


@dataclass(frozen=True)
class RunSpec:
    prompt_slug: str
    prompt_version: str
    vendors: list[str]
    models: dict[str, str]
    merge_vendor: str
    merge_model: str
    requested_labels: int
    created_by_user_id: str | None = None


class LabelEnrichmentRepository:
    def __init__(
        self,
        data_api: DataAPIClient,
        now: Callable[[], datetime] = _utc_now,
    ) -> None:
        self._data_api = data_api
        self._now = now

    # ── labels ──────────────────────────────────────────────────────
    def upsert_label_by_name(self, name: str) -> str:
        normalized = _normalize_label(name)
        rows = self._data_api.execute(
            "SELECT id FROM clouder_labels WHERE normalized_name = :n LIMIT 1",
            {"n": normalized},
        )
        if rows:
            return rows[0]["id"]
        new_id = str(uuid.uuid4())
        ts = self._now()
        self._data_api.execute(
            """
            INSERT INTO clouder_labels (
                id, name, normalized_name, is_ai_suspected,
                created_at, updated_at
            ) VALUES (
                :id, :name, :normalized_name, FALSE, :ts, :ts
            )
            """,
            {
                "id": new_id,
                "name": name.strip(),
                "normalized_name": normalized,
                "ts": ts,
            },
        )
        return new_id

    # ── runs ────────────────────────────────────────────────────────
    def create_run(self, spec: RunSpec) -> str:
        run_id = str(uuid.uuid4())
        ts = self._now()
        self._data_api.execute(
            """
            INSERT INTO clouder_label_enrichment_runs (
                id, status, prompt_slug, prompt_version, vendors, models,
                merge_vendor, merge_model, requested_labels, cells_total,
                cells_ok, cells_error, cost_usd, created_by_user_id, created_at
            ) VALUES (
                :id, :status, :prompt_slug, :prompt_version, :vendors, :models,
                :merge_vendor, :merge_model, :requested_labels, :cells_total,
                0, 0, 0, :created_by_user_id, :created_at
            )
            """,
            {
                "id": run_id,
                "status": "queued",
                "prompt_slug": spec.prompt_slug,
                "prompt_version": spec.prompt_version,
                "vendors": json.dumps(spec.vendors),
                "models": json.dumps(spec.models),
                "merge_vendor": spec.merge_vendor,
                "merge_model": spec.merge_model,
                "requested_labels": spec.requested_labels,
                "cells_total": spec.requested_labels * len(spec.vendors),
                "created_by_user_id": spec.created_by_user_id,
                "created_at": ts,
            },
        )
        return run_id

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        rows = self._data_api.execute(
            """
            SELECT id, status, prompt_slug, prompt_version, vendors, models,
                   merge_vendor, merge_model, requested_labels, cells_total,
                   cells_ok, cells_error, cost_usd, created_by_user_id,
                   created_at, started_at, finished_at
            FROM clouder_label_enrichment_runs
            WHERE id = :id
            LIMIT 1
            """,
            {"id": run_id},
        )
        return rows[0] if rows else None
```

- [ ] **Step 4: Run, expect PASS**

Run: `PYTHONPATH=src pytest tests/unit/test_label_enrichment_repository.py -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add src/collector/label_enrichment/repository.py tests/unit/test_label_enrichment_repository.py
git commit -m "feat(backend): add label_enrichment repository scaffolding (runs + label upsert)"
```

---

### Task 4.2: `insert_cell` (idempotent) + `mark_run_running`

**Files:**
- Modify: `src/collector/label_enrichment/repository.py`
- Modify: `tests/unit/test_label_enrichment_repository.py`

- [ ] **Step 1: Add failing tests**

Append to `tests/unit/test_label_enrichment_repository.py`:

```python
from collector.label_enrichment.vendors.base import VendorResponse
from collector.label_enrichment.schemas import LabelInfo


def _ok_vendor_response() -> VendorResponse:
    info = LabelInfo(
        label_name="Drumcode",
        ai_reasoning="none",
        summary="techno",
        confidence=0.9,
    )
    return VendorResponse(
        parsed=info,
        raw={"foo": "bar"},
        citations=["https://example.com"],
        usage={"input_tokens": 100, "output_tokens": 50, "cost_usd": 0.001},
        latency_ms=1234,
        model="gemini-3-flash-preview",
    )


def test_insert_cell_ok_uses_on_conflict_do_nothing():
    repo, data_api = _repo_with_fake()
    data_api.execute.return_value = []
    resp = _ok_vendor_response()
    repo.insert_cell(run_id="r", label_id="l", vendor="gemini", response=resp)
    sql, params = data_api.execute.call_args[0]
    assert "ON CONFLICT" in sql
    assert "DO NOTHING" in sql
    assert params["status"] == "ok"
    assert params["error"] is None
    assert params["vendor"] == "gemini"
    assert params["model"] == "gemini-3-flash-preview"


def test_insert_cell_error_serialises_error_payload():
    repo, data_api = _repo_with_fake()
    data_api.execute.return_value = []
    resp = VendorResponse(
        parsed=None,
        raw={},
        citations=[],
        usage={"input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0},
        latency_ms=50,
        model="openai-x",
        error="RateLimitError: 429",
    )
    repo.insert_cell(run_id="r", label_id="l", vendor="openai", response=resp)
    _, params = data_api.execute.call_args[0]
    assert params["status"] == "error"
    error_payload = json.loads(params["error"])
    assert error_payload["message"] == "RateLimitError: 429"


def test_mark_run_running_only_flips_queued_to_running():
    repo, data_api = _repo_with_fake()
    data_api.execute.return_value = []
    repo.mark_run_running("r-1")
    sql, params = data_api.execute.call_args[0]
    assert "status = 'running'" in sql
    assert "started_at = :ts" in sql
    assert "WHERE id = :id AND status = 'queued'" in sql
    assert params["id"] == "r-1"
```

Also add `import json` near the top of the test file if not already present.

- [ ] **Step 2: Run, expect failures**

Run: `PYTHONPATH=src pytest tests/unit/test_label_enrichment_repository.py -v`
Expected: 3 new tests fail with `AttributeError: 'LabelEnrichmentRepository' object has no attribute 'insert_cell'` (and similar for `mark_run_running`).

- [ ] **Step 3: Implement on the repository**

Append inside `LabelEnrichmentRepository` (after `get_run`):

```python
    # ── cells ───────────────────────────────────────────────────────
    def insert_cell(
        self,
        *,
        run_id: str,
        label_id: str,
        vendor: str,
        response: "VendorResponse",
    ) -> None:
        from .vendors.base import VendorResponse  # local — avoid cycle

        assert isinstance(response, VendorResponse)
        cell_id = str(uuid.uuid4())
        ts = self._now()
        status = "ok" if response.error is None and response.parsed is not None else "error"
        parsed_payload = (
            response.parsed.model_dump() if response.parsed is not None else None
        )
        error_payload = (
            json.dumps({"message": response.error}) if response.error is not None else None
        )
        self._data_api.execute(
            """
            INSERT INTO clouder_label_enrichment_cells (
                id, run_id, label_id, vendor, model, status,
                parsed, citations, usage, latency_ms, error, created_at
            ) VALUES (
                :id, :run_id, :label_id, :vendor, :model, :status,
                :parsed, :citations, :usage, :latency_ms, :error, :created_at
            )
            ON CONFLICT (run_id, label_id, vendor) DO NOTHING
            """,
            {
                "id": cell_id,
                "run_id": run_id,
                "label_id": label_id,
                "vendor": vendor,
                "model": response.model,
                "status": status,
                "parsed": json.dumps(parsed_payload) if parsed_payload is not None else None,
                "citations": json.dumps(response.citations),
                "usage": json.dumps(response.usage),
                "latency_ms": response.latency_ms,
                "error": error_payload,
                "created_at": ts,
            },
        )

    def mark_run_running(self, run_id: str) -> None:
        """Flip queued → running on first worker pickup. No-op when already running."""
        self._data_api.execute(
            """
            UPDATE clouder_label_enrichment_runs
            SET status = 'running', started_at = :ts
            WHERE id = :id AND status = 'queued'
            """,
            {"id": run_id, "ts": self._now()},
        )
```

Also add the `VendorResponse` import as a forward-ref at the top of the file:

```python
from typing import Any, Callable, Mapping, TYPE_CHECKING
if TYPE_CHECKING:
    from .vendors.base import VendorResponse
```

(Remove the existing `from typing import Any, Callable, Mapping` if you added it earlier — replace with the line above.)

- [ ] **Step 4: Run tests, expect PASS**

Run: `PYTHONPATH=src pytest tests/unit/test_label_enrichment_repository.py -v`
Expected: 7 passed.

- [ ] **Step 5: Commit**

```bash
git add src/collector/label_enrichment/repository.py tests/unit/test_label_enrichment_repository.py
git commit -m "$(cat <<'EOF'
feat(backend): repository.insert_cell + mark_run_running

insert_cell is idempotent via ON CONFLICT (run_id, label_id, vendor)
DO NOTHING so SQS retries do not double-write cells. mark_run_running
flips queued -> running only — concurrent workers race-safe because the
WHERE clause requires status='queued'.
EOF
)"
```

---

### Task 4.3: `upsert_label_info` + `project_ai_suspected` + `get_label_info`

**Files:**
- Modify: `src/collector/label_enrichment/repository.py`
- Modify: `tests/unit/test_label_enrichment_repository.py`

- [ ] **Step 1: Add failing tests**

```python
def test_upsert_label_info_writes_denormalized_columns():
    repo, data_api = _repo_with_fake()
    data_api.execute.return_value = []
    merged = LabelInfo(
        label_name="Drumcode",
        ai_reasoning="none",
        summary="techno",
        confidence=0.9,
        country="Sweden",
        founded_year=1996,
        status="active",
        primary_styles=["techno", "peak-time techno"],
        tagline="Swedish techno powerhouse since 1996.",
        last_release_date="2026-04-01",
    )
    provenance = {"status": "majority(2/3 definitive)"}
    repo.upsert_label_info(
        label_id="lbl-1",
        last_run_id="run-1",
        prompt_slug="label_v3_app_fields",
        prompt_version="v1",
        merged=merged,
        provenance=provenance,
    )
    sql, params = data_api.execute.call_args[0]
    assert "INSERT INTO clouder_label_info" in sql
    assert "ON CONFLICT (label_id) DO UPDATE SET" in sql
    assert params["status"] == "active"
    assert params["country"] == "Sweden"
    assert params["founded_year"] == 1996
    assert params["primary_styles"] == ["techno", "peak-time techno"]
    assert params["tagline"] == "Swedish techno powerhouse since 1996."
    assert params["ai_content"] == "unknown"  # default
    assert params["ai_confidence"] == Decimal("0.90") or float(params["ai_confidence"]) == 0.9
    assert params["last_release_date"] == "2026-04-01"


def test_project_ai_suspected_sets_true_when_confirmed_high_confidence():
    repo, data_api = _repo_with_fake()
    data_api.execute.return_value = []
    merged = LabelInfo(
        label_name="X", ai_reasoning="r", summary="s", confidence=0.8,
        ai_content="confirmed",
    )
    repo.project_ai_suspected("lbl-1", merged, threshold=0.5)
    sql, params = data_api.execute.call_args[0]
    assert "UPDATE clouder_labels" in sql
    assert "is_ai_suspected = :value" in sql
    assert params["value"] is True
    assert params["id"] == "lbl-1"


def test_project_ai_suspected_sets_false_when_none_detected_high_confidence():
    repo, data_api = _repo_with_fake()
    data_api.execute.return_value = []
    merged = LabelInfo(
        label_name="X", ai_reasoning="r", summary="s", confidence=0.6,
        ai_content="none_detected",
    )
    repo.project_ai_suspected("lbl-1", merged, threshold=0.5)
    _, params = data_api.execute.call_args[0]
    assert params["value"] is False


def test_project_ai_suspected_no_op_when_below_threshold():
    repo, data_api = _repo_with_fake()
    merged = LabelInfo(
        label_name="X", ai_reasoning="r", summary="s", confidence=0.3,
        ai_content="confirmed",
    )
    repo.project_ai_suspected("lbl-1", merged, threshold=0.5)
    data_api.execute.assert_not_called()


def test_get_label_info_joins_label_name():
    repo, data_api = _repo_with_fake()
    data_api.execute.return_value = [{
        "label_id": "lbl-1",
        "label_name": "Drumcode",
        "last_run_id": "run-1",
        "prompt_slug": "label_v3_app_fields",
        "prompt_version": "v1",
        "merged": {"label_name": "Drumcode"},
        "provenance": {},
        "ai_content": "none_detected",
        "ai_confidence": 0.9,
        "status": "active",
        "primary_styles": ["techno"],
        "tagline": None, "country": "Sweden",
        "founded_year": 1996, "activity": "steady",
        "last_release_date": None,
        "updated_at": "2026-05-18T21:00:00+00:00",
    }]
    row = repo.get_label_info("lbl-1")
    assert row["label_name"] == "Drumcode"
    sql, _ = data_api.execute.call_args[0]
    assert "JOIN clouder_labels" in sql
```

- [ ] **Step 2: Run, expect failures**

Run: `PYTHONPATH=src pytest tests/unit/test_label_enrichment_repository.py -v`
Expected: 5 new failures.

- [ ] **Step 3: Implement the methods**

Append to `LabelEnrichmentRepository`:

```python
    # ── label_info ──────────────────────────────────────────────────
    def upsert_label_info(
        self,
        *,
        label_id: str,
        last_run_id: str,
        prompt_slug: str,
        prompt_version: str,
        merged: "LabelInfo",
        provenance: Mapping[str, Any],
    ) -> None:
        ts = self._now()
        payload = merged.model_dump()
        self._data_api.execute(
            """
            INSERT INTO clouder_label_info (
                label_id, last_run_id, prompt_slug, prompt_version,
                merged, provenance,
                ai_content, ai_confidence, status, primary_styles,
                tagline, country, founded_year, activity, last_release_date,
                updated_at
            ) VALUES (
                :label_id, :last_run_id, :prompt_slug, :prompt_version,
                :merged, :provenance,
                :ai_content, :ai_confidence, :status, :primary_styles,
                :tagline, :country, :founded_year, :activity, :last_release_date,
                :updated_at
            )
            ON CONFLICT (label_id) DO UPDATE SET
                last_run_id = EXCLUDED.last_run_id,
                prompt_slug = EXCLUDED.prompt_slug,
                prompt_version = EXCLUDED.prompt_version,
                merged = EXCLUDED.merged,
                provenance = EXCLUDED.provenance,
                ai_content = EXCLUDED.ai_content,
                ai_confidence = EXCLUDED.ai_confidence,
                status = EXCLUDED.status,
                primary_styles = EXCLUDED.primary_styles,
                tagline = EXCLUDED.tagline,
                country = EXCLUDED.country,
                founded_year = EXCLUDED.founded_year,
                activity = EXCLUDED.activity,
                last_release_date = EXCLUDED.last_release_date,
                updated_at = EXCLUDED.updated_at
            """,
            {
                "label_id": label_id,
                "last_run_id": last_run_id,
                "prompt_slug": prompt_slug,
                "prompt_version": prompt_version,
                "merged": json.dumps(payload),
                "provenance": json.dumps(dict(provenance)),
                "ai_content": payload.get("ai_content", "unknown"),
                "ai_confidence": Decimal(str(round(payload.get("confidence", 0.0), 2))),
                "status": payload.get("status", "unknown"),
                "primary_styles": list(payload.get("primary_styles") or []),
                "tagline": payload.get("tagline"),
                "country": payload.get("country"),
                "founded_year": payload.get("founded_year"),
                "activity": payload.get("activity"),
                "last_release_date": payload.get("last_release_date"),
                "updated_at": ts,
            },
        )

    def project_ai_suspected(
        self,
        label_id: str,
        merged: "LabelInfo",
        threshold: float,
    ) -> None:
        """Mirror merged.ai_content into clouder_labels.is_ai_suspected when confidence >= threshold."""
        from .schemas import AIContentStatus  # local — avoid cycle at module load

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
            UPDATE clouder_labels
            SET is_ai_suspected = :value, updated_at = :ts
            WHERE id = :id
            """,
            {"value": value, "ts": self._now(), "id": label_id},
        )

    def get_label_info(self, label_id: str) -> dict[str, Any] | None:
        rows = self._data_api.execute(
            """
            SELECT
                li.label_id, cl.name AS label_name, li.last_run_id,
                li.prompt_slug, li.prompt_version,
                li.merged, li.provenance,
                li.ai_content, li.ai_confidence, li.status, li.primary_styles,
                li.tagline, li.country, li.founded_year, li.activity,
                li.last_release_date, li.updated_at
            FROM clouder_label_info li
            JOIN clouder_labels cl ON cl.id = li.label_id
            WHERE li.label_id = :id
            LIMIT 1
            """,
            {"id": label_id},
        )
        return rows[0] if rows else None
```

Add forward refs at top of file (replace the existing TYPE_CHECKING block):
```python
if TYPE_CHECKING:
    from .schemas import LabelInfo
    from .vendors.base import VendorResponse
```

- [ ] **Step 4: Run tests, expect PASS**

Run: `PYTHONPATH=src pytest tests/unit/test_label_enrichment_repository.py -v`
Expected: 12 passed.

- [ ] **Step 5: Commit**

```bash
git add src/collector/label_enrichment/repository.py tests/unit/test_label_enrichment_repository.py
git commit -m "$(cat <<'EOF'
feat(backend): repository.upsert_label_info + project_ai_suspected + get_label_info

upsert_label_info writes the merged jsonb plus the denormalized
columns in one statement; ON CONFLICT (label_id) DO UPDATE handles
re-runs cleanly. project_ai_suspected mirrors the merged ai_content
flag onto clouder_labels.is_ai_suspected so the existing triage UI
keeps working.
EOF
)"
```

---

### Task 4.4: `increment_run_counters` (atomic status flip)

**Files:**
- Modify: `src/collector/label_enrichment/repository.py`
- Modify: `tests/unit/test_label_enrichment_repository.py`

- [ ] **Step 1: Add failing tests**

```python
def test_increment_run_counters_atomic_update_only():
    repo, data_api = _repo_with_fake()
    data_api.execute.return_value = []
    repo.increment_run_counters(
        run_id="r-1",
        ok_delta=2,
        error_delta=1,
        cost_delta=0.03,
    )
    sql, params = data_api.execute.call_args[0]
    assert sql.count("UPDATE clouder_label_enrichment_runs") == 1
    assert "cells_ok = cells_ok + :ok" in sql
    assert "cells_error = cells_error + :err" in sql
    assert "cost_usd = cost_usd + :cost" in sql
    assert "CASE WHEN cells_ok + cells_error + :ok + :err >= cells_total" in sql
    assert "THEN 'completed'" in sql
    assert "ELSE status" in sql
    assert "finished_at = CASE" in sql
    assert params["ok"] == 2
    assert params["err"] == 1
```

- [ ] **Step 2: Run, expect failure**

Run: `PYTHONPATH=src pytest tests/unit/test_label_enrichment_repository.py -v`
Expected: 1 new failure.

- [ ] **Step 3: Implement**

Append to `LabelEnrichmentRepository`:

```python
    def increment_run_counters(
        self,
        *,
        run_id: str,
        ok_delta: int,
        error_delta: int,
        cost_delta: float,
    ) -> None:
        """Atomically bump counters and flip to 'completed' once cells_total is reached.

        Single UPDATE so the (cells_ok + cells_error) check and the status
        flip happen inside one transaction — race-safe across concurrent
        worker invocations.
        """
        ts = self._now()
        self._data_api.execute(
            """
            UPDATE clouder_label_enrichment_runs
            SET
                cells_ok = cells_ok + :ok,
                cells_error = cells_error + :err,
                cost_usd = cost_usd + :cost,
                status = CASE
                    WHEN cells_ok + cells_error + :ok + :err >= cells_total
                    THEN 'completed'
                    ELSE status
                END,
                finished_at = CASE
                    WHEN cells_ok + cells_error + :ok + :err >= cells_total
                    THEN :ts
                    ELSE finished_at
                END
            WHERE id = :id
            """,
            {
                "id": run_id,
                "ok": ok_delta,
                "err": error_delta,
                "cost": Decimal(str(round(cost_delta, 4))),
                "ts": ts,
            },
        )
```

- [ ] **Step 4: Run tests, expect PASS**

Run: `PYTHONPATH=src pytest tests/unit/test_label_enrichment_repository.py -v`
Expected: 13 passed.

- [ ] **Step 5: Commit**

```bash
git add src/collector/label_enrichment/repository.py tests/unit/test_label_enrichment_repository.py
git commit -m "$(cat <<'EOF'
feat(backend): repository.increment_run_counters

Single atomic UPDATE that adds the worker-side delta and flips the run
to 'completed' only when (cells_ok + cells_error) reaches cells_total.
Race-safe across concurrent worker invocations.
EOF
)"
```

---

## Phase 5 — Orchestrator

### Task 5.1: `enrich_label_for_run` + `run_vendors_parallel` + cell-shape helper

**Files:**
- Create: `src/collector/label_enrichment/orchestrator.py`
- Create: `tests/unit/test_label_enrichment_orchestrator.py`

- [ ] **Step 1: Write failing test**

```python
# tests/unit/test_label_enrichment_orchestrator.py
from types import SimpleNamespace
from unittest.mock import MagicMock

from collector.label_enrichment.orchestrator import (
    enrich_label_for_run,
    run_vendors_parallel,
)
from collector.label_enrichment.prompts import (
    PROMPTS, load_builtin_prompts, get_prompt,
)
from collector.label_enrichment.schemas import LabelInfo
from collector.label_enrichment.vendors.base import VendorResponse


def setup_function(_):
    PROMPTS.clear()
    load_builtin_prompts()


def _ok(vendor: str, model: str) -> VendorResponse:
    return VendorResponse(
        parsed=LabelInfo(
            label_name="Drumcode",
            ai_reasoning="none",
            summary="techno",
            confidence=0.9,
        ),
        raw={}, citations=[],
        usage={"input_tokens": 100, "output_tokens": 50, "cost_usd": 0.002},
        latency_ms=200, model=model,
    )


def _err(vendor: str, model: str) -> VendorResponse:
    return VendorResponse(
        parsed=None, raw={}, citations=[],
        usage={"input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0},
        latency_ms=50, model=model, error="boom",
    )


def _make_adapter(name: str, model: str, response: VendorResponse) -> MagicMock:
    adapter = MagicMock()
    adapter.name = name
    adapter.default_model = model
    adapter.run.return_value = response
    return adapter


def test_run_vendors_parallel_returns_one_cell_per_vendor():
    adapters = [
        _make_adapter("gemini", "g", _ok("gemini", "g")),
        _make_adapter("openai", "o", _err("openai", "o")),
    ]
    prompt = get_prompt("label_v3_app_fields")
    cells = run_vendors_parallel(
        adapters=adapters,
        label_name="Drumcode",
        style="techno",
        release_name=None,
        prompt=prompt,
    )
    assert len(cells) == 2
    by_vendor = {c["vendor"]["name"]: c for c in cells}
    assert by_vendor["gemini"]["error"] is None
    assert by_vendor["openai"]["error"] == "boom"
    assert by_vendor["openai"]["response"]["parsed"] is None


def test_enrich_label_for_run_writes_cells_upserts_info_and_increments():
    adapters = [
        _make_adapter("gemini", "g", _ok("gemini", "g")),
        _make_adapter("openai", "o", _ok("openai", "o")),
    ]
    prompt = get_prompt("label_v3_app_fields")
    repo = MagicMock()
    merge_client = MagicMock()
    merge_client.chat.completions.create.return_value = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content='{"tagline":"t","summary":"s","ai_reasoning":"r","notes":null}'))],
        usage=SimpleNamespace(prompt_tokens=200, completion_tokens=80),
    )

    enrich_label_for_run(
        run_id="run-1",
        label_id="lbl-1",
        label_name="Drumcode",
        style="techno",
        release_name=None,
        adapters=adapters,
        merge_client=merge_client,
        merge_model="deepseek-v4-flash",
        prompt=prompt,
        repository=repo,
        ai_flag_threshold=0.5,
    )

    # mark_run_running was called once
    repo.mark_run_running.assert_called_once_with("run-1")
    # insert_cell called exactly once per vendor (the invariant)
    assert repo.insert_cell.call_count == 2
    # upsert_label_info called once
    repo.upsert_label_info.assert_called_once()
    # project_ai_suspected called once
    repo.project_ai_suspected.assert_called_once()
    # increment_run_counters called once with the full deltas
    repo.increment_run_counters.assert_called_once()
    kwargs = repo.increment_run_counters.call_args.kwargs
    assert kwargs["run_id"] == "run-1"
    assert kwargs["ok_delta"] == 2
    assert kwargs["error_delta"] == 0


def test_enrich_label_for_run_counts_mixed_outcomes():
    adapters = [
        _make_adapter("gemini", "g", _ok("gemini", "g")),
        _make_adapter("openai", "o", _err("openai", "o")),
        _make_adapter("tavily_deepseek", "d", _ok("tavily_deepseek", "d")),
    ]
    prompt = get_prompt("label_v3_app_fields")
    repo = MagicMock()
    merge_client = MagicMock()
    merge_client.chat.completions.create.return_value = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content='{"tagline":"t","summary":"s","ai_reasoning":"r","notes":null}'))],
        usage=SimpleNamespace(prompt_tokens=200, completion_tokens=80),
    )
    enrich_label_for_run(
        run_id="run-1",
        label_id="lbl-1",
        label_name="X",
        style="y",
        release_name=None,
        adapters=adapters,
        merge_client=merge_client,
        merge_model="deepseek-v4-flash",
        prompt=prompt,
        repository=repo,
        ai_flag_threshold=0.5,
    )
    kwargs = repo.increment_run_counters.call_args.kwargs
    assert kwargs["ok_delta"] == 2
    assert kwargs["error_delta"] == 1
    # cost = 0.002 + 0.0 + 0.002 + (deepseek narrative cost)
    assert kwargs["cost_delta"] > 0.003
```

- [ ] **Step 2: Run, expect failure**

Run: `PYTHONPATH=src pytest tests/unit/test_label_enrichment_orchestrator.py -v`
Expected: collection failure.

- [ ] **Step 3: Implement**

```python
# src/collector/label_enrichment/orchestrator.py
"""High-level wiring: run vendors in parallel, aggregate, persist."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from .aggregator import merge_cells
from .prompts.base import PromptConfig, render_user
from .repository import LabelEnrichmentRepository
from .vendors.base import VendorAdapter, VendorResponse


def _cell_payload(
    vendor: VendorAdapter,
    response: VendorResponse,
    label_name: str,
) -> dict:
    """Shape mirrors experiments/labels output so aggregator.merge_cells works unchanged."""
    return {
        "vendor": {"name": vendor.name, "model": response.model},
        "fixture": {"label_name": label_name},
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
    label_name: str,
    style: str,
    release_name: str | None,
    prompt: PromptConfig,
) -> list[dict]:
    """Dispatch all adapters concurrently. One call per adapter, one cell per result."""
    user = render_user(prompt, label_name=label_name, style=style, release_name=release_name)
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

    # Preserve original adapter order for deterministic provenance tie-breaks
    by_name = {a.name: r for a, r in results}
    return [_cell_payload(a, by_name[a.name], label_name) for a in adapters]


def enrich_label_for_run(
    *,
    run_id: str,
    label_id: str,
    label_name: str,
    style: str,
    release_name: str | None,
    adapters: list[VendorAdapter],
    merge_client: Any,
    merge_model: str,
    prompt: PromptConfig,
    repository: LabelEnrichmentRepository,
    ai_flag_threshold: float,
) -> None:
    """End-to-end: flip run status, run vendors, persist cells + merged + counters.

    Invariant: writes exactly len(adapters) cell rows per call (ok or error).
    """
    repository.mark_run_running(run_id)

    cells = run_vendors_parallel(
        adapters=adapters,
        label_name=label_name,
        style=style,
        release_name=release_name,
        prompt=prompt,
    )

    ok = 0
    err = 0
    cost = 0.0
    for adapter, cell in zip(adapters, cells):
        # Reconstruct VendorResponse for the repo from the cell payload
        response = _response_from_cell(cell, default_model=adapter.default_model)
        repository.insert_cell(
            run_id=run_id,
            label_id=label_id,
            vendor=adapter.name,
            response=response,
        )
        if cell["error"] is None and cell["response"]["parsed"] is not None:
            ok += 1
        else:
            err += 1
        cost += float(cell["response"]["usage"].get("cost_usd") or 0.0)

    merged_info, meta = merge_cells(cells, merge_client, merge_model)
    cost += float(meta.get("narrative_cost_usd") or 0.0)

    repository.upsert_label_info(
        label_id=label_id,
        last_run_id=run_id,
        prompt_slug=prompt.slug,
        prompt_version=prompt.version,
        merged=merged_info,
        provenance=meta.get("field_provenance") or {},
    )
    repository.project_ai_suspected(label_id, merged_info, ai_flag_threshold)
    repository.increment_run_counters(
        run_id=run_id,
        ok_delta=ok,
        error_delta=err,
        cost_delta=cost,
    )


def _response_from_cell(cell: dict, default_model: str) -> VendorResponse:
    """Rebuild a VendorResponse from a cell payload — used to keep repository's API stable."""
    from .schemas import LabelInfo

    parsed_payload = cell["response"]["parsed"]
    parsed = LabelInfo.model_validate(parsed_payload) if parsed_payload else None
    return VendorResponse(
        parsed=parsed,
        raw={},
        citations=cell["response"].get("citations") or [],
        usage=cell["response"].get("usage") or {
            "input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0,
        },
        latency_ms=cell["response"].get("latency_ms") or 0,
        model=cell["vendor"].get("model") or default_model,
        error=cell.get("error"),
    )
```

- [ ] **Step 4: Run tests, expect PASS**

Run: `PYTHONPATH=src pytest tests/unit/test_label_enrichment_orchestrator.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add src/collector/label_enrichment/orchestrator.py tests/unit/test_label_enrichment_orchestrator.py
git commit -m "$(cat <<'EOF'
feat(backend): label_enrichment orchestrator

enrich_label_for_run wires the parallel vendor calls, deterministic +
narrative merge, and atomic counter update. Upholds the invariant of
exactly len(adapters) cell rows per label (the math that lets
cells_ok + cells_error eventually reach cells_total for a healthy run).
EOF
)"
```

---

### Task 5.2: Vendor-adapter factory (`build_adapters_from_run_config`)

**Files:**
- Modify: `src/collector/label_enrichment/orchestrator.py`
- Modify: `tests/unit/test_label_enrichment_orchestrator.py`

The worker needs to instantiate adapters dynamically from the per-run config + settings. We isolate that wiring in one helper so it can be mocked in worker tests.

- [ ] **Step 1: Add failing test**

```python
def test_build_adapters_from_run_config_returns_three_adapters():
    from collector.label_enrichment.orchestrator import build_adapters_from_run_config
    from collector.label_enrichment.settings_provider import LabelEnrichmentSecrets

    adapters = build_adapters_from_run_config(
        vendor_names=["gemini", "openai", "tavily_deepseek"],
        models={
            "gemini": "gemini-3-flash-preview",
            "openai": "gpt-5.4-mini",
            "tavily_deepseek": "deepseek-v4-flash",
        },
        secrets=LabelEnrichmentSecrets(
            gemini_api_key="g", openai_api_key="o",
            tavily_api_key="t", deepseek_api_key="d",
        ),
        request_timeout_s=30.0,
    )
    names = {a.name for a in adapters}
    assert names == {"gemini", "openai", "tavily_deepseek"}
    by_name = {a.name: a for a in adapters}
    assert by_name["gemini"].default_model == "gemini-3-flash-preview"


def test_build_adapters_rejects_unknown_vendor():
    import pytest
    from collector.label_enrichment.orchestrator import build_adapters_from_run_config
    from collector.label_enrichment.settings_provider import LabelEnrichmentSecrets

    with pytest.raises(ValueError, match="unknown vendor"):
        build_adapters_from_run_config(
            vendor_names=["anthropic"],
            models={"anthropic": "claude-opus"},
            secrets=LabelEnrichmentSecrets(
                gemini_api_key="g", openai_api_key="o",
                tavily_api_key="t", deepseek_api_key="d",
            ),
            request_timeout_s=30.0,
        )
```

- [ ] **Step 2: Run, expect failure**

Run: `PYTHONPATH=src pytest tests/unit/test_label_enrichment_orchestrator.py -v`
Expected: 2 new failures.

- [ ] **Step 3: Create the secrets dataclass and the factory**

Create `src/collector/label_enrichment/settings_provider.py`:

```python
"""Lightweight container so the factory does not depend on settings.py at import time."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class LabelEnrichmentSecrets:
    gemini_api_key: str
    openai_api_key: str
    tavily_api_key: str
    deepseek_api_key: str
```

Append to `src/collector/label_enrichment/orchestrator.py`:

```python
def build_adapters_from_run_config(
    *,
    vendor_names: list[str],
    models: dict[str, str],
    secrets: "LabelEnrichmentSecrets",
    request_timeout_s: float,
) -> list[VendorAdapter]:
    """Instantiate exactly the requested adapters with their per-run models."""
    from .vendors.gemini import GeminiAdapter
    from .vendors.openai_gpt import OpenAIAdapter
    from .vendors.tavily_deepseek import TavilyDeepSeekAdapter

    adapters: list[VendorAdapter] = []
    for name in vendor_names:
        model = models.get(name)
        if not model:
            raise ValueError(f"model missing for vendor {name!r}")
        if name == "gemini":
            adapters.append(GeminiAdapter(
                api_key=secrets.gemini_api_key,
                default_model=model,
                timeout_s=request_timeout_s,
            ))
        elif name == "openai":
            adapters.append(OpenAIAdapter(
                api_key=secrets.openai_api_key,
                default_model=model,
                timeout_s=request_timeout_s,
            ))
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

Add the forward-ref import at the top of `orchestrator.py`:

```python
from .settings_provider import LabelEnrichmentSecrets
```

- [ ] **Step 4: Run tests, expect PASS**

Run: `PYTHONPATH=src pytest tests/unit/test_label_enrichment_orchestrator.py -v`
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add src/collector/label_enrichment/orchestrator.py \
        src/collector/label_enrichment/settings_provider.py \
        tests/unit/test_label_enrichment_orchestrator.py
git commit -m "feat(backend): build_adapters_from_run_config factory + LabelEnrichmentSecrets"
```

---

## Phase 6 — Message + request schemas

### Task 6.1: `LabelEnrichmentMessage` and `EnrichLabelsRequestIn`

**Files:**
- Create: `src/collector/label_enrichment/messages.py`
- Create: `tests/unit/test_label_enrichment_messages.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/unit/test_label_enrichment_messages.py
import pytest
from pydantic import ValidationError

from collector.label_enrichment.messages import (
    EnrichLabelInput,
    EnrichLabelsRequestIn,
    LabelEnrichmentMessage,
)


def test_message_round_trip():
    msg = LabelEnrichmentMessage.model_validate({
        "run_id": "r1", "label_id": "l1",
        "label_name": "Drumcode", "style": "techno",
        "release_name": None,
    })
    assert msg.run_id == "r1"
    assert msg.release_name is None


def test_request_minimal_valid():
    req = EnrichLabelsRequestIn.model_validate({
        "labels": [{"label_name": "Drumcode", "style": "techno"}],
        "vendors": ["gemini"],
        "models": {"gemini": "gemini-3-flash-preview"},
        "prompt_slug": "label_v3_app_fields",
        "prompt_version": "v1",
        "merge_vendor": "deepseek",
        "merge_model": "deepseek-v4-flash",
    })
    assert len(req.labels) == 1
    assert req.vendors == ["gemini"]


def test_request_rejects_unknown_vendor():
    with pytest.raises(ValidationError):
        EnrichLabelsRequestIn.model_validate({
            "labels": [{"label_name": "x", "style": "y"}],
            "vendors": ["anthropic"],
            "models": {"anthropic": "claude"},
            "prompt_slug": "label_v3_app_fields",
            "prompt_version": "v1",
            "merge_vendor": "deepseek",
            "merge_model": "deepseek-v4-flash",
        })


def test_request_rejects_label_list_overflow():
    with pytest.raises(ValidationError):
        EnrichLabelsRequestIn.model_validate({
            "labels": [{"label_name": str(i), "style": "y"} for i in range(101)],
            "vendors": ["gemini"],
            "models": {"gemini": "x"},
            "prompt_slug": "label_v3_app_fields",
            "prompt_version": "v1",
            "merge_vendor": "deepseek",
            "merge_model": "deepseek-v4-flash",
        })


def test_request_rejects_missing_model_for_vendor():
    with pytest.raises(ValidationError, match="model missing for vendor"):
        EnrichLabelsRequestIn.model_validate({
            "labels": [{"label_name": "x", "style": "y"}],
            "vendors": ["gemini", "openai"],
            "models": {"gemini": "g"},  # openai missing
            "prompt_slug": "label_v3_app_fields",
            "prompt_version": "v1",
            "merge_vendor": "deepseek",
            "merge_model": "deepseek-v4-flash",
        })
```

- [ ] **Step 2: Run, expect failure**

Run: `PYTHONPATH=src pytest tests/unit/test_label_enrichment_messages.py -v`
Expected: collection failure.

- [ ] **Step 3: Implement**

```python
# src/collector/label_enrichment/messages.py
"""SQS message + HTTP request schemas for label enrichment."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


SUPPORTED_VENDORS = ("gemini", "openai", "tavily_deepseek")


class LabelEnrichmentMessage(BaseModel):
    """Body of one SQS message — one per label, one Lambda invocation."""

    model_config = ConfigDict(extra="ignore")

    run_id: str = Field(min_length=1)
    label_id: str = Field(min_length=1)
    label_name: str = Field(min_length=1)
    style: str = Field(min_length=1)
    release_name: str | None = None


class EnrichLabelInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label_name: str = Field(min_length=1, max_length=256)
    style: str = Field(min_length=1, max_length=128)
    release_name: str | None = Field(default=None, max_length=256)


class EnrichLabelsRequestIn(BaseModel):
    """POST /admin/labels/enrich body."""

    model_config = ConfigDict(extra="forbid")

    labels: list[EnrichLabelInput] = Field(min_length=1, max_length=100)
    vendors: list[Literal["gemini", "openai", "tavily_deepseek"]] = Field(min_length=1)
    models: dict[str, str]
    prompt_slug: str = Field(min_length=1)
    prompt_version: str = Field(min_length=1)
    merge_vendor: Literal["deepseek"]
    merge_model: str = Field(min_length=1)

    @model_validator(mode="after")
    def _every_vendor_has_a_model(self) -> "EnrichLabelsRequestIn":
        for vendor in self.vendors:
            if vendor not in self.models or not self.models[vendor].strip():
                raise ValueError(f"model missing for vendor {vendor!r}")
        return self
```

- [ ] **Step 4: Run tests, expect PASS**

Run: `PYTHONPATH=src pytest tests/unit/test_label_enrichment_messages.py -v`
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add src/collector/label_enrichment/messages.py tests/unit/test_label_enrichment_messages.py
git commit -m "feat(backend): SQS message + POST request schemas for label enrichment"
```

---

## Phase 7 — API routes

The three new HTTP routes live in their own module `src/collector/label_enrichment/routes.py` so `handler.py` stays small. `handler.py` only adds a dispatch entry and the `_ADMIN_ROUTES` set update.

### Task 7.1: `POST /admin/labels/enrich` route

**Files:**
- Create: `src/collector/label_enrichment/routes.py`
- Modify: `src/collector/handler.py`
- Create: `tests/unit/test_label_enrichment_api.py`

- [ ] **Step 1: Write failing test**

```python
# tests/unit/test_label_enrichment_api.py
import json
from unittest.mock import MagicMock, patch

import pytest

from collector.handler import lambda_handler


def _admin_event(route_key: str, body: dict | None = None, path_params: dict | None = None) -> dict:
    return {
        "routeKey": route_key,
        "body": json.dumps(body) if body is not None else None,
        "pathParameters": path_params or {},
        "requestContext": {
            "authorizer": {"lambda": {"is_admin": True, "user_id": "user-1"}},
        },
    }


def _non_admin_event(route_key: str, body: dict | None = None) -> dict:
    return {
        "routeKey": route_key,
        "body": json.dumps(body) if body is not None else None,
        "pathParameters": {},
        "requestContext": {
            "authorizer": {"lambda": {"is_admin": False, "user_id": "user-2"}},
        },
    }


_VALID_BODY = {
    "labels": [
        {"label_name": "Drumcode", "style": "techno"},
        {"label_name": "Anjunadeep", "style": "deep house"},
    ],
    "vendors": ["gemini", "openai", "tavily_deepseek"],
    "models": {
        "gemini": "gemini-3-flash-preview",
        "openai": "gpt-5.4-mini",
        "tavily_deepseek": "deepseek-v4-flash",
    },
    "prompt_slug": "label_v3_app_fields",
    "prompt_version": "v1",
    "merge_vendor": "deepseek",
    "merge_model": "deepseek-v4-flash",
}


@pytest.fixture
def patched_deps(monkeypatch):
    repo = MagicMock()
    repo.upsert_label_by_name.side_effect = lambda name: f"lbl-{name.lower().replace(' ', '-')}"
    repo.create_run.return_value = "run-1"
    sqs_client = MagicMock()
    monkeypatch.setattr(
        "collector.label_enrichment.routes._build_repository",
        lambda: repo,
    )
    monkeypatch.setattr(
        "collector.label_enrichment.routes._build_sqs_client",
        lambda: sqs_client,
    )
    monkeypatch.setenv("LABEL_ENRICHMENT_QUEUE_URL", "https://sqs.example/q")
    yield repo, sqs_client


def test_post_enrich_returns_202_and_enqueues_one_message_per_label(patched_deps):
    repo, sqs = patched_deps
    resp = lambda_handler(_admin_event("POST /admin/labels/enrich", _VALID_BODY), None)
    assert resp["statusCode"] == 202
    body = json.loads(resp["body"])
    assert body["run_id"] == "run-1"
    assert body["queued_labels"] == 2
    assert sqs.send_message.call_count == 2
    repo.create_run.assert_called_once()
    spec = repo.create_run.call_args[0][0]
    assert spec.requested_labels == 2
    assert spec.created_by_user_id == "user-1"


def test_post_enrich_rejects_non_admin(patched_deps):
    resp = lambda_handler(_non_admin_event("POST /admin/labels/enrich", _VALID_BODY), None)
    assert resp["statusCode"] == 403


def test_post_enrich_rejects_invalid_body(patched_deps):
    bad = {**_VALID_BODY, "labels": []}
    resp = lambda_handler(_admin_event("POST /admin/labels/enrich", bad), None)
    assert resp["statusCode"] == 400
```

- [ ] **Step 2: Run, expect failures (route not yet wired)**

Run: `PYTHONPATH=src pytest tests/unit/test_label_enrichment_api.py -v`
Expected: tests fail with 404 (route not registered).

- [ ] **Step 3: Implement `routes.py`**

```python
# src/collector/label_enrichment/routes.py
"""HTTP handlers for label enrichment.

The handlers stay framework-agnostic: they accept the API Gateway event
dict and return a (status, body) tuple. `collector.handler` wraps them
in the shared _json_response shape.
"""

from __future__ import annotations

import json
import os
from typing import Any, Mapping

from pydantic import ValidationError as PydanticValidationError

from ..data_api import create_default_data_api_client
from ..errors import ValidationError
from .messages import EnrichLabelsRequestIn
from .repository import LabelEnrichmentRepository, RunSpec


def _build_repository() -> LabelEnrichmentRepository:
    client = create_default_data_api_client()
    if client is None:
        raise RuntimeError("Aurora Data API not configured")
    return LabelEnrichmentRepository(data_api=client)


def _build_sqs_client():
    import boto3
    return boto3.client("sqs")


def _queue_url() -> str:
    url = os.environ.get("LABEL_ENRICHMENT_QUEUE_URL", "").strip()
    if not url:
        raise RuntimeError("LABEL_ENRICHMENT_QUEUE_URL is required")
    return url


def _extract_user_id(event: Mapping[str, Any]) -> str | None:
    rc = event.get("requestContext")
    if not isinstance(rc, Mapping):
        return None
    authz = rc.get("authorizer")
    if not isinstance(authz, Mapping):
        return None
    ctx = authz.get("lambda")
    if isinstance(ctx, Mapping):
        return ctx.get("user_id")
    return None


def handle_post_enrich(event: Mapping[str, Any]) -> tuple[int, dict]:
    body_raw = event.get("body") or "{}"
    try:
        body = json.loads(body_raw)
    except json.JSONDecodeError as exc:
        raise ValidationError(f"invalid JSON body: {exc}")
    try:
        req = EnrichLabelsRequestIn.model_validate(body)
    except PydanticValidationError as exc:
        raise ValidationError(exc.errors()[0]["msg"]) from exc

    repo = _build_repository()
    sqs = _build_sqs_client()
    queue_url = _queue_url()

    label_ids: list[tuple[str, str, str, str | None]] = []
    for item in req.labels:
        lid = repo.upsert_label_by_name(item.label_name)
        label_ids.append((lid, item.label_name, item.style, item.release_name))

    spec = RunSpec(
        prompt_slug=req.prompt_slug,
        prompt_version=req.prompt_version,
        vendors=list(req.vendors),
        models=dict(req.models),
        merge_vendor=req.merge_vendor,
        merge_model=req.merge_model,
        requested_labels=len(req.labels),
        created_by_user_id=_extract_user_id(event),
    )
    run_id = repo.create_run(spec)

    for lid, name, style, release in label_ids:
        msg = {
            "run_id": run_id,
            "label_id": lid,
            "label_name": name,
            "style": style,
            "release_name": release,
        }
        sqs.send_message(QueueUrl=queue_url, MessageBody=json.dumps(msg))

    return 202, {"run_id": run_id, "queued_labels": len(req.labels)}


def handle_get_run(event: Mapping[str, Any]) -> tuple[int, dict]:
    path = event.get("pathParameters") or {}
    run_id = (path.get("run_id") or "").strip()
    if not run_id:
        raise ValidationError("run_id is required")
    repo = _build_repository()
    row = repo.get_run(run_id)
    if row is None:
        return 404, {"error_code": "not_found", "message": "run not found"}
    return 200, row


def handle_get_label(event: Mapping[str, Any]) -> tuple[int, dict]:
    path = event.get("pathParameters") or {}
    label_id = (path.get("label_id") or "").strip()
    if not label_id:
        raise ValidationError("label_id is required")
    repo = _build_repository()
    row = repo.get_label_info(label_id)
    if row is None:
        return 404, {"error_code": "not_found", "message": "label info not found"}
    return 200, row
```

(The user ID is extracted by `_extract_user_id` defined locally in this same module — no extra imports needed.)

- [ ] **Step 4: Wire routes into `handler.py`**

In `src/collector/handler.py`:

1. Extend `_ADMIN_ROUTES`:
```python
_ADMIN_ROUTES = frozenset({
    "POST /collect_bp_releases",
    "POST /admin/beatport/ingest",
    "GET /admin/coverage",
    "GET /admin/runs",
    "GET /tracks/spotify-not-found",
    "POST /admin/labels/enrich",
    "GET /admin/labels/enrich-runs/{run_id}",
    "GET /admin/labels/{label_id}",
})
```

2. Add to `_route` (after the existing dispatch lines, before `_LIST_ROUTES` check):
```python
    if route_key == "POST /admin/labels/enrich":
        from .label_enrichment.routes import handle_post_enrich
        status, body = handle_post_enrich(event)
        return _json_response(status, body, correlation_id)
    if route_key == "GET /admin/labels/enrich-runs/{run_id}":
        from .label_enrichment.routes import handle_get_run
        status, body = handle_get_run(event)
        return _json_response(status, body, correlation_id)
    if route_key == "GET /admin/labels/{label_id}":
        from .label_enrichment.routes import handle_get_label
        status, body = handle_get_label(event)
        return _json_response(status, body, correlation_id)
```

- [ ] **Step 5: Run tests, expect PASS**

Run: `PYTHONPATH=src pytest tests/unit/test_label_enrichment_api.py -v`
Expected: 3 passed.

- [ ] **Step 6: Commit**

```bash
git add src/collector/label_enrichment/routes.py src/collector/handler.py tests/unit/test_label_enrichment_api.py
git commit -m "$(cat <<'EOF'
feat(backend): POST /admin/labels/enrich route

Validates body via EnrichLabelsRequestIn, upserts labels by
normalized name, creates a run row, enqueues one SQS message per
label, returns 202 with the run_id and queued_labels count. Admin
gate enforced via existing _ADMIN_ROUTES set.
EOF
)"
```

---

### Task 7.2: `GET /admin/labels/enrich-runs/{run_id}` + `GET /admin/labels/{label_id}`

The handlers were authored in Task 7.1's routes.py; this task adds tests so both endpoints have direct coverage.

**Files:**
- Modify: `tests/unit/test_label_enrichment_api.py`

- [ ] **Step 1: Add failing tests**

```python
def test_get_enrich_run_returns_row(patched_deps):
    repo, _ = patched_deps
    repo.get_run.return_value = {
        "id": "run-1", "status": "running", "cells_total": 6,
        "cells_ok": 3, "cells_error": 0,
    }
    resp = lambda_handler(
        _admin_event(
            "GET /admin/labels/enrich-runs/{run_id}",
            path_params={"run_id": "run-1"},
        ),
        None,
    )
    assert resp["statusCode"] == 200
    body = json.loads(resp["body"])
    assert body["id"] == "run-1"


def test_get_enrich_run_404(patched_deps):
    repo, _ = patched_deps
    repo.get_run.return_value = None
    resp = lambda_handler(
        _admin_event(
            "GET /admin/labels/enrich-runs/{run_id}",
            path_params={"run_id": "nope"},
        ),
        None,
    )
    assert resp["statusCode"] == 404


def test_get_label_info_returns_row(patched_deps):
    repo, _ = patched_deps
    repo.get_label_info.return_value = {
        "label_id": "lbl-1", "label_name": "Drumcode",
        "merged": {"label_name": "Drumcode"},
        "status": "active", "ai_content": "none_detected",
    }
    resp = lambda_handler(
        _admin_event(
            "GET /admin/labels/{label_id}",
            path_params={"label_id": "lbl-1"},
        ),
        None,
    )
    assert resp["statusCode"] == 200
    body = json.loads(resp["body"])
    assert body["label_name"] == "Drumcode"


def test_get_label_info_404(patched_deps):
    repo, _ = patched_deps
    repo.get_label_info.return_value = None
    resp = lambda_handler(
        _admin_event(
            "GET /admin/labels/{label_id}",
            path_params={"label_id": "lbl-9"},
        ),
        None,
    )
    assert resp["statusCode"] == 404
```

- [ ] **Step 2: Run, expect PASS (the routes already exist)**

Run: `PYTHONPATH=src pytest tests/unit/test_label_enrichment_api.py -v`
Expected: 7 passed total.

- [ ] **Step 3: Commit**

```bash
git add tests/unit/test_label_enrichment_api.py
git commit -m "test(backend): cover GET /admin/labels/* endpoints"
```

---

## Phase 8 — Worker Lambda handler

### Task 8.1: `label_enrichment_handler.lambda_handler`

**Files:**
- Create: `src/collector/label_enrichment_handler.py`
- Create: `tests/unit/test_label_enrichment_worker.py`

- [ ] **Step 1: Write failing test**

```python
# tests/unit/test_label_enrichment_worker.py
import json
from unittest.mock import MagicMock, patch

import pytest

from collector.label_enrichment_handler import lambda_handler


def _sqs_event(body: dict) -> dict:
    return {"Records": [{"body": json.dumps(body)}]}


def _run_row() -> dict:
    return {
        "id": "run-1",
        "status": "running",
        "prompt_slug": "label_v3_app_fields",
        "prompt_version": "v1",
        "vendors": ["gemini"],
        "models": {"gemini": "gemini-3-flash-preview"},
        "merge_vendor": "deepseek",
        "merge_model": "deepseek-v4-flash",
        "cells_total": 1,
        "cells_ok": 0,
        "cells_error": 0,
    }


@pytest.fixture
def worker_patches(monkeypatch):
    repo = MagicMock()
    repo.get_run.return_value = _run_row()

    monkeypatch.setattr(
        "collector.label_enrichment_handler._build_repository",
        lambda: repo,
    )

    settings_obj = MagicMock(
        gemini_api_key="g", openai_api_key="o",
        tavily_api_key="t", deepseek_api_key="d",
        request_timeout_s=30.0,
        ai_flag_confidence_threshold=0.5,
    )
    monkeypatch.setattr(
        "collector.label_enrichment_handler.get_label_enrichment_worker_settings",
        lambda: settings_obj,
    )

    enrich_calls: list[dict] = []

    def fake_enrich(**kwargs):
        enrich_calls.append(kwargs)

    monkeypatch.setattr(
        "collector.label_enrichment_handler.enrich_label_for_run",
        fake_enrich,
    )

    # Don't actually build adapters
    monkeypatch.setattr(
        "collector.label_enrichment_handler.build_adapters_from_run_config",
        lambda **_: [MagicMock(name="gemini")],
    )

    yield repo, enrich_calls


def test_worker_dispatches_orchestrator(worker_patches):
    repo, enrich_calls = worker_patches
    event = _sqs_event({
        "run_id": "run-1", "label_id": "lbl-1",
        "label_name": "Drumcode", "style": "techno", "release_name": None,
    })
    result = lambda_handler(event, None)
    assert result == {"processed": 1}
    assert len(enrich_calls) == 1
    call = enrich_calls[0]
    assert call["run_id"] == "run-1"
    assert call["label_id"] == "lbl-1"
    assert call["label_name"] == "Drumcode"
    assert call["ai_flag_threshold"] == 0.5


def test_worker_drops_invalid_message(worker_patches):
    repo, enrich_calls = worker_patches
    event = _sqs_event({"run_id": "", "label_id": "x", "label_name": "y", "style": "z"})
    result = lambda_handler(event, None)
    assert result == {"processed": 0}
    assert enrich_calls == []


def test_worker_raises_when_run_missing(worker_patches):
    repo, _ = worker_patches
    repo.get_run.return_value = None
    event = _sqs_event({
        "run_id": "missing", "label_id": "lbl-1",
        "label_name": "x", "style": "y",
    })
    with pytest.raises(RuntimeError, match="run not found"):
        lambda_handler(event, None)
```

- [ ] **Step 2: Run, expect failure**

Run: `PYTHONPATH=src pytest tests/unit/test_label_enrichment_worker.py -v`
Expected: collection failure (module does not exist).

- [ ] **Step 3: Implement the handler**

```python
# src/collector/label_enrichment_handler.py
"""SQS-driven Lambda that enriches a single label per invocation."""

from __future__ import annotations

import json
from typing import Any, Mapping

from pydantic import ValidationError as PydanticValidationError

from .data_api import create_default_data_api_client
from .label_enrichment.messages import LabelEnrichmentMessage
from .label_enrichment.orchestrator import (
    build_adapters_from_run_config,
    enrich_label_for_run,
)
from .label_enrichment.prompts import get_prompt, load_builtin_prompts
from .label_enrichment.repository import LabelEnrichmentRepository
from .label_enrichment.settings_provider import LabelEnrichmentSecrets
from .logging_utils import log_event
from .settings import get_label_enrichment_worker_settings

try:
    from openai import OpenAI
except ImportError:  # pragma: no cover — module imported lazily in tests
    OpenAI = None  # type: ignore[assignment]


def _build_repository() -> LabelEnrichmentRepository:
    client = create_default_data_api_client()
    if client is None:
        raise RuntimeError("Aurora Data API not configured")
    return LabelEnrichmentRepository(data_api=client)


def _build_merge_client(api_key: str, timeout_s: float):
    if OpenAI is None:
        raise RuntimeError("openai SDK not installed")
    return OpenAI(api_key=api_key, base_url="https://api.deepseek.com", timeout=timeout_s)


def lambda_handler(event: Mapping[str, Any], context: Any) -> dict[str, Any]:
    del context
    records = event.get("Records") or []
    if not isinstance(records, list):
        return {"processed": 0}

    log_event("INFO", "label_enrichment_worker_invoked", sqs_record_count=len(records))
    load_builtin_prompts()

    settings = get_label_enrichment_worker_settings()
    repository = _build_repository()
    secrets = LabelEnrichmentSecrets(
        gemini_api_key=settings.gemini_api_key,
        openai_api_key=settings.openai_api_key,
        tavily_api_key=settings.tavily_api_key,
        deepseek_api_key=settings.deepseek_api_key,
    )
    merge_client = _build_merge_client(settings.deepseek_api_key, settings.request_timeout_s)

    processed = 0
    for index, record in enumerate(records):
        if not isinstance(record, Mapping):
            continue
        body = record.get("body")
        if not isinstance(body, str):
            continue
        try:
            msg = LabelEnrichmentMessage.model_validate_json(body)
        except PydanticValidationError as exc:
            log_event(
                "ERROR",
                "label_enrichment_message_invalid",
                sqs_record_index=index,
                error_message=str(exc)[:500],
            )
            continue

        run_row = repository.get_run(msg.run_id)
        if run_row is None:
            raise RuntimeError(f"run not found: {msg.run_id}")

        vendors = list(run_row.get("vendors") or [])
        models = dict(run_row.get("models") or {})
        adapters = build_adapters_from_run_config(
            vendor_names=vendors,
            models=models,
            secrets=secrets,
            request_timeout_s=settings.request_timeout_s,
        )
        prompt = get_prompt(run_row["prompt_slug"])

        enrich_label_for_run(
            run_id=msg.run_id,
            label_id=msg.label_id,
            label_name=msg.label_name,
            style=msg.style,
            release_name=msg.release_name,
            adapters=adapters,
            merge_client=merge_client,
            merge_model=run_row["merge_model"],
            prompt=prompt,
            repository=repository,
            ai_flag_threshold=settings.ai_flag_confidence_threshold,
        )
        processed += 1
        log_event(
            "INFO",
            "label_enrichment_completed",
            run_id=msg.run_id,
            label_id=msg.label_id,
            label_name=msg.label_name,
        )

    return {"processed": processed}
```

- [ ] **Step 4: Run tests, expect PASS**

Run: `PYTHONPATH=src pytest tests/unit/test_label_enrichment_worker.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add src/collector/label_enrichment_handler.py tests/unit/test_label_enrichment_worker.py
git commit -m "$(cat <<'EOF'
feat(backend): label_enrichment_handler SQS worker

One Lambda invocation per label (batch_size=1). Loads run config from
the runs row, builds adapters from settings + run config, dispatches
the orchestrator. Catastrophic errors (missing run, DB) re-raise so the
SQS message redrives; validation errors drop the message.
EOF
)"
```

---

## Phase 9 — Remove old label-search code

⚠️ **Order:** every task above this phase must be done and committed first, otherwise the tree won't compile while the old code is mid-deletion. Each task in this phase is one focused commit so the working tree stays green between tasks.

### Task 9.1: Delete the `search/` package + perplexity providers + search_handler

**Files:**
- Delete: `src/collector/search/` (whole directory)
- Delete: `src/collector/providers/perplexity/` (whole directory)
- Delete: `src/collector/search_handler.py`
- Delete tests:
  - `tests/unit/test_entity_search_message.py` (legacy)
  - `tests/unit/test_ai_flag_propagation.py`
  - any `tests/unit/test_perplexity_*.py`
  - any `tests/unit/test_search_handler*.py`
  - any `tests/unit/test_search_prompts*.py`

- [ ] **Step 1: Inventory the tests that target removed code**

Run: `grep -lE "search_handler|search\.prompts|perplexity|propagate_ai_flag|EntitySearchMessage|LabelSearchMessage|save_search_result|find_labels_needing_search" tests/unit/ tests/integration/`
Expected: the list of test files coupled to removed code. Delete each one.

- [ ] **Step 2: Delete the packages and files**

```bash
git rm -r src/collector/search/
git rm -r src/collector/providers/perplexity/
git rm src/collector/search_handler.py
git rm tests/unit/test_entity_search_message.py
git rm tests/unit/test_ai_flag_propagation.py
# delete any other test files surfaced by Step 1
```

- [ ] **Step 3: Sanity-check that no other source still imports them**

Run: `grep -rE "from .search|collector\.search_handler|providers\.perplexity" src/ tests/`
Expected: empty output.

- [ ] **Step 4: Commit**

```bash
git add -A
git commit -m "$(cat <<'EOF'
chore(backend): drop legacy Perplexity label-search package

Removes src/collector/search/, src/collector/providers/perplexity/, the
search_handler Lambda entrypoint, and the tests that targeted them.
The new label_enrichment subsystem (Phases 1-8) replaces them.
EOF
)"
```

---

### Task 9.2: Trim `schemas.py`, `repositories.py`, `db_models.py`, `providers/registry.py`, `settings.py`

**Files:**
- Modify: `src/collector/schemas.py`
- Modify: `src/collector/repositories.py`
- Modify: `src/collector/db_models.py`
- Modify: `src/collector/providers/registry.py`
- Modify: `src/collector/settings.py`
- Modify: `src/collector/worker_handler.py`

- [ ] **Step 1: Drop the search bits from `schemas.py`**

In `src/collector/schemas.py`, remove:
- `LabelSearchMessage` class (lines ~80-100 originally)
- `EntitySearchMessage` class (lines ~103-118)
- `coerce_search_message` function (lines ~187-210)
- the `search_label_count` field on `AdminIngestRequestIn` (line ~158) and its validation refs in `_validate_range_constraints` if any

The `validation_error_message` helper itself is shared and must stay.

- [ ] **Step 2: Drop the search bits from `repositories.py`**

In `src/collector/repositories.py`, remove:
- `_AI_SUSPECTED_TABLES` mapping
- `find_labels_needing_search`
- `update_entity_is_ai_suspected`
- `save_search_result`

(All three are in the "# ── AI Search methods ──" section beginning around line 851.)

- [ ] **Step 3: Drop the search ORM model**

In `src/collector/db_models.py`, remove the `AISearchResult` class (the `__tablename__ = "ai_search_results"` one).

- [ ] **Step 4: Drop the perplexity entries in `providers/registry.py`**

In `src/collector/providers/registry.py`, remove:
- `_build_perplexity_label`
- `_build_perplexity_artist`
- the `"perplexity_label": _build_perplexity_label` and `"perplexity_artist": _build_perplexity_artist` entries in `_BUILDERS`
- the `get_enricher_for_prompt` function

- [ ] **Step 5: Drop the search-related settings**

In `src/collector/settings.py`, remove:
- the `SearchWorkerSettings` class
- the `get_search_worker_settings` function
- the `get_search_worker_settings.cache_clear()` call inside `reset_settings_cache()`
- the `ai_search_enabled` and `ai_search_queue_url` fields on `ApiSettings`
- the `ai_search_queue_url` field on `WorkerSettings`

- [ ] **Step 6: Drop the stale import in `worker_handler.py`**

In `src/collector/worker_handler.py`, remove:
```python
from .search.prompts import get_latest as get_latest_prompt
```
(grep confirmed it is imported but unused.)

- [ ] **Step 7: Run the full unit suite to catch fallout**

Run: `PYTHONPATH=src pytest tests/unit -q`
Expected: all pass. If a test fails because it imports a removed symbol, delete that test (it was already in Task 9.1's inventory; double-check).

- [ ] **Step 8: Commit**

```bash
git add src/collector/schemas.py src/collector/repositories.py \
        src/collector/db_models.py src/collector/providers/registry.py \
        src/collector/settings.py src/collector/worker_handler.py
git commit -m "$(cat <<'EOF'
chore(backend): drop search-related symbols from shared modules

schemas.py loses EntitySearchMessage / LabelSearchMessage /
coerce_search_message and the search_label_count ingest field.
repositories.py drops save_search_result / find_labels_needing_search /
update_entity_is_ai_suspected. db_models drops AISearchResult ORM.
registry drops perplexity_* entries and get_enricher_for_prompt.
settings drops SearchWorkerSettings. The is_ai_suspected column stays
because the frontend triage UI still reads it (the new pipeline
re-populates it via project_ai_suspected).
EOF
)"
```

---

### Task 9.3: Trim `_enqueue_label_search` and ingest auto-trigger out of `handler.py`

**Files:**
- Modify: `src/collector/handler.py`

- [ ] **Step 1: Locate and remove**

In `src/collector/handler.py`:

1. Remove the import:
```python
from .search.prompts import get_latest as get_latest_prompt
```

2. Remove the `search_label_count` field from `_IngestParams` (frozen dataclass around line 165).

3. Remove the auto-enqueue block in `_run_beatport_ingest` (search for `if params.search_label_count` — surrounding ~10 lines that call `_enqueue_label_search`):
```python
search_enqueued = 0
if params.search_label_count and settings.ai_search_enabled:
    search_enqueued = _enqueue_label_search(...)
```

4. Remove `"search_labels_enqueued": search_enqueued,` from the response dict.

5. Remove the entire `_enqueue_label_search` helper function (around lines 836-930).

6. Remove the `search_label_count=request.search_label_count` argument passed into `_IngestParams` in both `_handle_collect` and `_handle_admin_ingest`.

- [ ] **Step 2: Re-run handler tests**

Run: `PYTHONPATH=src pytest tests/unit/test_handler_admin_gating.py tests/unit/test_admin_schemas.py -v`
Expected: all pass. If any test asserts on `search_labels_enqueued` or `search_label_count`, fix it in place.

- [ ] **Step 3: Commit**

```bash
git add src/collector/handler.py tests/unit/
git commit -m "$(cat <<'EOF'
chore(backend): remove auto-enqueue of label search from ingest

The new label-enrichment pipeline is explicitly triggered via
POST /admin/labels/enrich. Beatport ingest no longer fires off
label searches as a side-effect.
EOF
)"
```

---

## Phase 10 — Terraform

The infra changes split across many files. Each task is one focused commit so a partial deploy fails fast.

### Task 10.1: Remove old `ai_search` infra resources

**Files:**
- Modify: `infra/lambda.tf`, `infra/sqs.tf`, `infra/iam.tf`, `infra/alarms.tf`, `infra/variables.tf`, `infra/outputs.tf`, `infra/main.tf`, `infra/logging.tf`

- [ ] **Step 1: Remove from `infra/lambda.tf`**

Delete the entire `# ── AI Search worker ──` block:
- `resource "aws_lambda_function" "ai_search_worker"`
- `resource "aws_lambda_event_source_mapping" "ai_search_queue"`

Remove the API Lambda's two env-var lines (search for `AI_SEARCH_ENABLED` and `AI_SEARCH_QUEUE_URL` inside the `aws_lambda_function.collector` and `aws_lambda_function.canonicalization_worker` resources — delete those two keys from each `environment.variables` block).

- [ ] **Step 2: Remove from `infra/sqs.tf`**

Delete:
- `resource "aws_sqs_queue" "ai_search_dlq"`
- `resource "aws_sqs_queue" "ai_search"`

- [ ] **Step 3: Remove from `infra/iam.tf`**

Find and delete every IAM statement referencing `aws_sqs_queue.ai_search.arn` or `aws_cloudwatch_log_group.ai_search_worker.arn` or `var.perplexity_api_key_secret_arn` / `var.perplexity_api_key_ssm_parameter`. Use `grep -n "ai_search\|perplexity" infra/iam.tf` to find the lines.

- [ ] **Step 4: Remove from `infra/alarms.tf`**

Delete:
- The `ai_search` entry from the `for_each` map in the shared lambda-errors alarm (line ~16).
- `resource "aws_cloudwatch_metric_alarm" "ai_search_throttles"` (lines ~76-100).

- [ ] **Step 5: Remove from `infra/logging.tf`**

Delete the `aws_cloudwatch_log_group` for the ai_search worker if a dedicated one is declared (grep `ai_search` to find it).

- [ ] **Step 6: Remove from `infra/variables.tf`**

Delete these variable blocks (grep them by name):
- `ai_search_enabled`
- `ai_search_worker_lambda_timeout_seconds`
- `ai_search_worker_lambda_memory_mb`
- `ai_search_batch_size`
- `ai_search_worker_reserved_concurrency`
- `ai_search_queue_visibility_timeout_seconds`
- `ai_search_queue_retention_seconds`
- `perplexity_api_key_secret_arn`
- `perplexity_api_key_ssm_parameter`

- [ ] **Step 7: Remove from `infra/outputs.tf`**

Delete `output "ai_search_worker_lambda_function_name"`.

- [ ] **Step 8: Remove from `infra/main.tf` locals**

Delete these three locals:
```hcl
ai_search_worker_lambda_name = "${local.name_prefix}-ai-search-worker"
ai_search_queue_name         = "${local.name_prefix}-ai-search"
ai_search_dlq_name           = "${local.name_prefix}-ai-search-dlq"
```

- [ ] **Step 9: Validate**

Run: `cd infra && terraform validate`
Expected: `Success! The configuration is valid.`

- [ ] **Step 10: Commit**

```bash
cd ..
git add infra/
git commit -m "$(cat <<'EOF'
chore(infra): remove ai_search_worker resources

Drops the Lambda, SQS queue + DLQ, alarms, IAM statements, variables,
locals, outputs, and API-Lambda env vars for the discontinued
Perplexity-only pipeline.
EOF
)"
```

---

### Task 10.2: Add label-enrichment SQS queue + DLQ

**Files:**
- Modify: `infra/sqs.tf`
- Modify: `infra/main.tf`
- Modify: `infra/variables.tf`

- [ ] **Step 1: Add locals to `infra/main.tf`**

In the `locals { ... }` block:
```hcl
label_enrichment_worker_lambda_name = "${local.name_prefix}-label-enricher-worker"
label_enrichment_queue_name         = "${local.name_prefix}-label-enrichment"
label_enrichment_dlq_name           = "${local.name_prefix}-label-enrichment-dlq"
```

- [ ] **Step 2: Add variables to `infra/variables.tf`**

```hcl
variable "label_enrichment_queue_visibility_timeout_seconds" {
  description = "SQS visibility timeout in seconds (worker timeout + buffer)."
  type        = number
  default     = 1000
}

variable "label_enrichment_queue_retention_seconds" {
  description = "SQS message retention in seconds."
  type        = number
  default     = 345600
}

variable "label_enrichment_queue_max_receive_count" {
  description = "SQS receives before message moves to DLQ."
  type        = number
  default     = 3
}
```

- [ ] **Step 3: Add the queues to `infra/sqs.tf`**

```hcl
resource "aws_sqs_queue" "label_enrichment_dlq" {
  name                      = local.label_enrichment_dlq_name
  message_retention_seconds = var.label_enrichment_queue_retention_seconds
}

resource "aws_sqs_queue" "label_enrichment" {
  name                       = local.label_enrichment_queue_name
  visibility_timeout_seconds = var.label_enrichment_queue_visibility_timeout_seconds
  message_retention_seconds  = var.label_enrichment_queue_retention_seconds

  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.label_enrichment_dlq.arn
    maxReceiveCount     = var.label_enrichment_queue_max_receive_count
  })
}
```

- [ ] **Step 4: Validate**

Run: `cd infra && terraform validate`
Expected: success.

- [ ] **Step 5: Commit**

```bash
cd ..
git add infra/main.tf infra/variables.tf infra/sqs.tf
git commit -m "feat(infra): label_enrichment SQS queue + DLQ"
```

---

### Task 10.3: Add the worker Lambda + event source mapping

**Files:**
- Modify: `infra/lambda.tf`
- Modify: `infra/variables.tf`
- Modify: `infra/logging.tf`

- [ ] **Step 1: Add variables**

```hcl
variable "label_enrichment_worker_lambda_timeout_seconds" {
  description = "Lambda timeout. Default 900s (15min) — single label, ThreadPool inside, vendor latency budget."
  type        = number
  default     = 900
}

variable "label_enrichment_worker_lambda_memory_mb" {
  description = "Lambda memory MB."
  type        = number
  default     = 1024
}

variable "label_enrichment_worker_reserved_concurrency" {
  description = "Max parallel Lambda invocations. Caps cross-label parallelism."
  type        = number
  default     = 10
}

variable "label_enrichment_batch_size" {
  description = "SQS batch size. Keep at 1 — one label per invocation, ThreadPool fans out vendors."
  type        = number
  default     = 1
}

variable "gemini_api_key_secret_arn" {
  description = "Secrets Manager ARN for the Gemini API key."
  type        = string
  default     = ""
}

variable "openai_api_key_secret_arn" {
  description = "Secrets Manager ARN for the OpenAI API key."
  type        = string
  default     = ""
}

variable "tavily_api_key_secret_arn" {
  description = "Secrets Manager ARN for the Tavily API key."
  type        = string
  default     = ""
}

variable "deepseek_api_key_secret_arn" {
  description = "Secrets Manager ARN for the DeepSeek API key."
  type        = string
  default     = ""
}

variable "ai_flag_confidence_threshold" {
  description = "Minimum merged.confidence required to project ai_content onto is_ai_suspected."
  type        = number
  default     = 0.5
}
```

- [ ] **Step 2: Add the CloudWatch log group**

In `infra/logging.tf`, append:
```hcl
resource "aws_cloudwatch_log_group" "label_enricher_worker" {
  name              = "/aws/lambda/${local.label_enrichment_worker_lambda_name}"
  retention_in_days = var.log_retention_days
}
```

- [ ] **Step 3: Add the Lambda + event source mapping in `infra/lambda.tf`**

```hcl
# ── Label enrichment worker ──────────────────────────────────────

resource "aws_lambda_function" "label_enricher_worker" {
  function_name = local.label_enrichment_worker_lambda_name
  role          = aws_iam_role.collector_lambda.arn
  runtime       = "python3.12"
  handler       = "collector.label_enrichment_handler.lambda_handler"
  filename      = local.lambda_zip_file
  timeout       = var.label_enrichment_worker_lambda_timeout_seconds
  memory_size   = var.label_enrichment_worker_lambda_memory_mb

  reserved_concurrent_executions = var.enable_lambda_reserved_concurrency ? var.label_enrichment_worker_reserved_concurrency : -1

  source_code_hash = filebase64sha256(local.lambda_zip_file)

  environment {
    variables = {
      GEMINI_API_KEY_SECRET_ARN     = var.gemini_api_key_secret_arn
      OPENAI_API_KEY_SECRET_ARN     = var.openai_api_key_secret_arn
      TAVILY_API_KEY_SECRET_ARN     = var.tavily_api_key_secret_arn
      DEEPSEEK_API_KEY_SECRET_ARN   = var.deepseek_api_key_secret_arn
      LABEL_ENRICHMENT_QUEUE_URL    = aws_sqs_queue.label_enrichment.url
      AI_FLAG_CONFIDENCE_THRESHOLD  = tostring(var.ai_flag_confidence_threshold)
      AURORA_CLUSTER_ARN            = aws_rds_cluster.aurora.arn
      AURORA_SECRET_ARN             = try(aws_rds_cluster.aurora.master_user_secret[0].secret_arn, "")
      AURORA_DATABASE               = var.aurora_database_name
      LOG_LEVEL                     = "INFO"
    }
  }

  depends_on = [
    aws_cloudwatch_log_group.label_enricher_worker,
  ]
}

resource "aws_lambda_event_source_mapping" "label_enrichment_queue" {
  event_source_arn = aws_sqs_queue.label_enrichment.arn
  function_name    = aws_lambda_function.label_enricher_worker.arn
  batch_size       = var.label_enrichment_batch_size
}
```

- [ ] **Step 4: Add the queue URL env var on the API Lambda**

In `infra/lambda.tf`, find `aws_lambda_function.collector` and add to its `environment.variables`:
```hcl
LABEL_ENRICHMENT_QUEUE_URL = aws_sqs_queue.label_enrichment.url
```

- [ ] **Step 5: Validate**

Run: `cd infra && terraform validate`
Expected: success.

- [ ] **Step 6: Commit**

```bash
cd ..
git add infra/lambda.tf infra/variables.tf infra/logging.tf
git commit -m "$(cat <<'EOF'
feat(infra): label_enricher_worker Lambda + event source mapping

Lambda config: 15-min timeout (vendor latency budget), 1024 MB memory,
batch_size=1 (one label per invocation, ThreadPool fans out vendors).
Reads four vendor API keys from Secrets Manager via _resolve_simple_secret.
API Lambda gains LABEL_ENRICHMENT_QUEUE_URL env var to send messages.
EOF
)"
```

---

### Task 10.4: IAM, alarms, outputs

**Files:**
- Modify: `infra/iam.tf`, `infra/alarms.tf`, `infra/outputs.tf`, `infra/api_gateway.tf`

- [ ] **Step 1: IAM — let the worker receive from the queue and read secrets**

In `infra/iam.tf`, find the existing `aws_iam_policy_document.collector_lambda` (or the per-statement document used by the shared role) and append the following statements (style-matched to the existing SQS-receive blocks):

```hcl
statement {
  sid     = "AllowReceiveLabelEnrichmentQueue"
  actions = [
    "sqs:ReceiveMessage",
    "sqs:DeleteMessage",
    "sqs:GetQueueAttributes",
    "sqs:ChangeMessageVisibility",
  ]
  resources = [aws_sqs_queue.label_enrichment.arn]
}

statement {
  sid     = "AllowSendLabelEnrichmentQueue"
  actions = ["sqs:SendMessage"]
  resources = [aws_sqs_queue.label_enrichment.arn]
}

statement {
  sid = "AllowGetLabelEnrichmentSecrets"
  actions = ["secretsmanager:GetSecretValue"]
  resources = compact([
    var.gemini_api_key_secret_arn,
    var.openai_api_key_secret_arn,
    var.tavily_api_key_secret_arn,
    var.deepseek_api_key_secret_arn,
  ])
}
```

Wrap the secrets statement with `dynamic "statement" { for_each = ... }` if the existing file uses dynamic blocks (look at the `perplexity_api_key_secret_arn` removed block as a template).

- [ ] **Step 2: Alarms — throttles + DLQ depth**

In `infra/alarms.tf`:

1. Add `label_enricher = aws_lambda_function.label_enricher_worker.function_name` to the shared `for_each` map (the one that currently lists each worker).

2. Append:
```hcl
resource "aws_cloudwatch_metric_alarm" "label_enricher_throttles" {
  count = var.enable_lambda_reserved_concurrency ? 1 : 0

  alarm_name          = "${aws_lambda_function.label_enricher_worker.function_name}-throttles"
  namespace           = "AWS/Lambda"
  metric_name         = "Throttles"
  statistic           = "Sum"
  period              = 60
  evaluation_periods  = 5
  threshold           = 1
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "notBreaching"
  alarm_description   = "label_enricher throttled — reserved concurrency saturated"
  alarm_actions       = var.alarm_action_arns
  dimensions = {
    FunctionName = aws_lambda_function.label_enricher_worker.function_name
  }
}

resource "aws_cloudwatch_metric_alarm" "label_enrichment_dlq_depth" {
  alarm_name          = "${aws_sqs_queue.label_enrichment_dlq.name}-depth"
  namespace           = "AWS/SQS"
  metric_name         = "ApproximateNumberOfMessagesVisible"
  statistic           = "Maximum"
  period              = 300
  evaluation_periods  = 1
  threshold           = 1
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "notBreaching"
  alarm_description   = "label_enrichment DLQ has messages — worker is failing repeatedly"
  alarm_actions       = var.alarm_action_arns
  dimensions = {
    QueueName = aws_sqs_queue.label_enrichment_dlq.name
  }
}
```

- [ ] **Step 3: Outputs**

In `infra/outputs.tf`:
```hcl
output "label_enricher_worker_lambda_function_name" {
  description = "Name of the label-enrichment worker Lambda."
  value       = aws_lambda_function.label_enricher_worker.function_name
}

output "label_enrichment_queue_url" {
  description = "URL of the label-enrichment SQS queue."
  value       = aws_sqs_queue.label_enrichment.url
}
```

- [ ] **Step 4: API Gateway routes**

In `infra/api_gateway.tf`, append (mirroring the style of the existing `list_labels` route):

```hcl
resource "aws_apigatewayv2_route" "labels_enrich_post" {
  api_id             = aws_apigatewayv2_api.collector.id
  route_key          = "POST /admin/labels/enrich"
  target             = "integrations/${aws_apigatewayv2_integration.collector_lambda.id}"
  authorization_type = "CUSTOM"
  authorizer_id      = aws_apigatewayv2_authorizer.jwt.id
}

resource "aws_apigatewayv2_route" "labels_enrich_runs_get" {
  api_id             = aws_apigatewayv2_api.collector.id
  route_key          = "GET /admin/labels/enrich-runs/{run_id}"
  target             = "integrations/${aws_apigatewayv2_integration.collector_lambda.id}"
  authorization_type = "CUSTOM"
  authorizer_id      = aws_apigatewayv2_authorizer.jwt.id
}

resource "aws_apigatewayv2_route" "labels_get_info" {
  api_id             = aws_apigatewayv2_api.collector.id
  route_key          = "GET /admin/labels/{label_id}"
  target             = "integrations/${aws_apigatewayv2_integration.collector_lambda.id}"
  authorization_type = "CUSTOM"
  authorizer_id      = aws_apigatewayv2_authorizer.jwt.id
}
```

- [ ] **Step 5: Validate**

Run: `cd infra && terraform validate && terraform fmt -recursive`
Expected: success; `terraform fmt` returns 0 with no diffs.

- [ ] **Step 6: Commit**

```bash
cd ..
git add infra/
git commit -m "$(cat <<'EOF'
feat(infra): label_enricher IAM, alarms, outputs, API routes

Worker IAM: SQS receive on label_enrichment, Secrets Manager Get on
the four vendor key ARNs. API Lambda IAM: SQS SendMessage on the same
queue. Alarms: per-Lambda throttles + DLQ depth. Outputs expose
function name and queue URL. API Gateway: three new routes for the
admin enrich flow.
EOF
)"
```

---

## Phase 11 — Packaging, OpenAPI, integration test

### Task 11.1: Update Lambda packaging dependencies

**Files:**
- Modify: `src/collector/requirements.txt`

- [ ] **Step 1: Edit requirements**

Open `src/collector/requirements.txt`. Add (alphabetically):
```
google-genai>=0.4.0
httpx>=0.27.0
openai>=1.50.0
```

Remove any `urllib3` pin that was added solely for the old Perplexity HTTP path (grep `urllib3` first; keep if shared with another library — `botocore` already pulls a compatible version).

- [ ] **Step 2: Rebuild the Lambda zip**

Run: `bash scripts/package_lambda.sh`
Expected: produces a fresh `lambda.zip` containing the new SDKs. The shell script's tail prints zipped size — should be under 50 MB compressed and under 250 MB unpacked.

- [ ] **Step 3: Smoke-import in the packaged interpreter**

Run:
```bash
cd /tmp && unzip -q /Users/roman/Projects/clouder-projects/clouder-core/.claude/worktrees/collect_info/lambda.zip -d lambda_pkg
cd lambda_pkg
python3 -c "from google import genai; from openai import OpenAI; import httpx; print('ok')"
```
Expected: prints `ok`. Then `cd .. && rm -rf lambda_pkg` to clean up.

- [ ] **Step 4: Commit**

```bash
git add src/collector/requirements.txt
git commit -m "$(cat <<'EOF'
build(backend): add google-genai, openai, httpx to Lambda deps

google-genai for Gemini, openai for OpenAI + DeepSeek (the SDK is
OpenAI-compatible), httpx for Tavily. urllib-based Perplexity client
is gone, so its pin is dropped if it was added for that path.
EOF
)"
```

---

### Task 11.2: Regenerate OpenAPI

**Files:**
- Modify: `scripts/generate_openapi.py`
- Regenerate: `docs/api/openapi.yaml`

- [ ] **Step 1: Add the three routes to `ROUTES`**

In `scripts/generate_openapi.py`, before `ROUTES: list[dict[str, Any]] = [...]`, add the request/response shapes:

```python
LABEL_ENRICH_REQUEST = {
    "type": "object",
    "required": ["labels", "vendors", "models", "prompt_slug",
                 "prompt_version", "merge_vendor", "merge_model"],
    "properties": {
        "labels": {
            "type": "array",
            "minItems": 1,
            "maxItems": 100,
            "items": {
                "type": "object",
                "required": ["label_name", "style"],
                "properties": {
                    "label_name": {"type": "string", "minLength": 1, "maxLength": 256},
                    "style": {"type": "string", "minLength": 1, "maxLength": 128},
                    "release_name": {"type": ["string", "null"], "maxLength": 256},
                },
                "additionalProperties": False,
            },
        },
        "vendors": {
            "type": "array",
            "minItems": 1,
            "items": {"type": "string", "enum": ["gemini", "openai", "tavily_deepseek"]},
        },
        "models": {
            "type": "object",
            "additionalProperties": {"type": "string"},
        },
        "prompt_slug": {"type": "string", "minLength": 1},
        "prompt_version": {"type": "string", "minLength": 1},
        "merge_vendor": {"type": "string", "enum": ["deepseek"]},
        "merge_model": {"type": "string", "minLength": 1},
    },
    "additionalProperties": False,
}

LABEL_ENRICH_ACCEPTED_RESPONSE = {
    "type": "object",
    "required": ["run_id", "queued_labels"],
    "properties": {
        "run_id": {"type": "string", "format": "uuid"},
        "queued_labels": {"type": "integer", "minimum": 1},
    },
}

LABEL_ENRICH_RUN_RESPONSE = {
    "type": "object",
    "required": ["id", "status", "cells_total", "cells_ok", "cells_error"],
    "properties": {
        "id": {"type": "string", "format": "uuid"},
        "status": {"type": "string", "enum": ["queued", "running", "completed", "failed"]},
        "prompt_slug": {"type": "string"},
        "prompt_version": {"type": "string"},
        "vendors": {"type": "array", "items": {"type": "string"}},
        "models": {"type": "object", "additionalProperties": {"type": "string"}},
        "merge_vendor": {"type": "string"},
        "merge_model": {"type": "string"},
        "requested_labels": {"type": "integer"},
        "cells_total": {"type": "integer"},
        "cells_ok": {"type": "integer"},
        "cells_error": {"type": "integer"},
        "cost_usd": {"type": "number"},
        "created_at": {"type": "string", "format": "date-time"},
        "started_at": {"type": ["string", "null"], "format": "date-time"},
        "finished_at": {"type": ["string", "null"], "format": "date-time"},
    },
}

LABEL_INFO_RESPONSE = {
    "type": "object",
    "required": ["label_id", "label_name", "merged", "status",
                 "ai_content", "ai_confidence", "updated_at"],
    "properties": {
        "label_id": {"type": "string", "format": "uuid"},
        "label_name": {"type": "string"},
        "last_run_id": {"type": "string", "format": "uuid"},
        "prompt_slug": {"type": "string"},
        "prompt_version": {"type": "string"},
        "merged": {"type": "object"},
        "provenance": {"type": "object"},
        "ai_content": {"type": "string"},
        "ai_confidence": {"type": "number"},
        "status": {"type": "string"},
        "primary_styles": {"type": "array", "items": {"type": "string"}},
        "tagline": {"type": ["string", "null"]},
        "country": {"type": ["string", "null"]},
        "founded_year": {"type": ["integer", "null"]},
        "activity": {"type": ["string", "null"]},
        "last_release_date": {"type": ["string", "null"], "format": "date"},
        "updated_at": {"type": "string", "format": "date-time"},
    },
}
```

Append to the `ROUTES` list:

```python
    {
        "method": "post",
        "path": "/admin/labels/enrich",
        "summary": "Trigger multi-vendor enrichment for a list of labels.",
        "request_body": LABEL_ENRICH_REQUEST,
        "responses": {
            "202": {"description": "Run created.", "schema": LABEL_ENRICH_ACCEPTED_RESPONSE},
            "400": {"description": "Validation error.", "schema": ERROR_RESPONSE},
            "403": {"description": "Admin required.", "schema": ERROR_RESPONSE},
        },
    },
    {
        "method": "get",
        "path": "/admin/labels/enrich-runs/{run_id}",
        "summary": "Read a single enrichment run.",
        "path_params": [
            {"name": "run_id", "in": "path", "required": True,
             "schema": {"type": "string", "format": "uuid"}},
        ],
        "responses": {
            "200": {"description": "Run row.", "schema": LABEL_ENRICH_RUN_RESPONSE},
            "404": {"description": "Not found.", "schema": ERROR_RESPONSE},
            "403": {"description": "Admin required.", "schema": ERROR_RESPONSE},
        },
    },
    {
        "method": "get",
        "path": "/admin/labels/{label_id}",
        "summary": "Read the merged enrichment record for a single label.",
        "path_params": [
            {"name": "label_id", "in": "path", "required": True,
             "schema": {"type": "string", "format": "uuid"}},
        ],
        "responses": {
            "200": {"description": "Label info.", "schema": LABEL_INFO_RESPONSE},
            "404": {"description": "Not found.", "schema": ERROR_RESPONSE},
            "403": {"description": "Admin required.", "schema": ERROR_RESPONSE},
        },
    },
```

(If the existing `ROUTES` items use a different field shape than `request_body`/`responses`, mirror that shape — open the file and copy an existing entry's structure verbatim, then substitute the schemas above into the matching keys.)

- [ ] **Step 2: Regenerate**

Run: `PYTHONPATH=src .venv/bin/python scripts/generate_openapi.py`
Expected: rewrites `docs/api/openapi.yaml`.

- [ ] **Step 3: Diff-check**

Run: `git diff docs/api/openapi.yaml | head -200`
Expected: the diff contains exactly three new path entries (`/admin/labels/enrich`, `/admin/labels/enrich-runs/{run_id}`, `/admin/labels/{label_id}`) plus their schemas. No unrelated route changes.

- [ ] **Step 4: Commit**

```bash
git add scripts/generate_openapi.py docs/api/openapi.yaml
git commit -m "$(cat <<'EOF'
docs(api): regenerate openapi.yaml with three label-enrichment routes

POST /admin/labels/enrich, GET /admin/labels/enrich-runs/{run_id},
GET /admin/labels/{label_id}. Frontend schema.d.ts will be
regenerated on the SPA side as a follow-up.
EOF
)"
```

---

### Task 11.3: End-to-end integration test

**Files:**
- Create: `tests/integration/test_label_enrichment_e2e.py`

This exercises POST → SQS-stub → worker → DB rows. It uses an in-memory `FakeDataApi` (or whatever the integration suite uses today) plus stub vendor adapters returning canned `VendorResponse`s.

- [ ] **Step 1: Locate the existing integration harness**

Run: `ls tests/integration/ && grep -l "ClouderRepository\|create_clouder_repository" tests/integration/*.py | head -5`
Expected: shows the harness layout. Inspect one existing integration test to see how Aurora is stood up (real DB? a fixture? a stub?). Adopt the same pattern.

- [ ] **Step 2: Write the test**

```python
# tests/integration/test_label_enrichment_e2e.py
"""End-to-end: POST /admin/labels/enrich → SQS stub → worker → DB.

Real DB writes go through the existing integration repository (or a
FakeDataApi if the suite doesn't stand up Aurora — see comment in
Step 1 for how this is normally wired).
"""

import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from collector.handler import lambda_handler as api_handler
from collector.label_enrichment_handler import lambda_handler as worker_handler
from collector.label_enrichment.schemas import LabelInfo
from collector.label_enrichment.vendors.base import VendorResponse


def _admin_event(body: dict) -> dict:
    return {
        "routeKey": "POST /admin/labels/enrich",
        "body": json.dumps(body),
        "pathParameters": {},
        "requestContext": {
            "authorizer": {"lambda": {"is_admin": True, "user_id": "user-1"}},
        },
    }


def _stub_vendor_response(vendor: str) -> VendorResponse:
    return VendorResponse(
        parsed=LabelInfo(
            label_name="Drumcode",
            ai_reasoning="none",
            summary="Swedish techno",
            confidence=0.9,
            country="Sweden",
            founded_year=1996,
            status="active",
            primary_styles=["techno"],
        ),
        raw={}, citations=[],
        usage={"input_tokens": 100, "output_tokens": 50, "cost_usd": 0.002},
        latency_ms=200, model=f"{vendor}-model",
    )


@pytest.fixture
def repo_and_sqs(monkeypatch):
    """Wire repository + SQS to a shared stub so the API & worker see the same state."""
    captured_messages: list[str] = []

    class FakeSqs:
        def send_message(self, *, QueueUrl, MessageBody):
            captured_messages.append(MessageBody)

    real_repo = MagicMock()
    real_repo.upsert_label_by_name.side_effect = lambda name: f"lbl-{name.lower().replace(' ', '-')}"
    real_repo.create_run.return_value = "run-1"

    run_state = {
        "id": "run-1",
        "status": "queued",
        "prompt_slug": "label_v3_app_fields",
        "prompt_version": "v1",
        "vendors": ["gemini", "openai", "tavily_deepseek"],
        "models": {
            "gemini": "gemini-3-flash-preview",
            "openai": "gpt-5.4-mini",
            "tavily_deepseek": "deepseek-v4-flash",
        },
        "merge_vendor": "deepseek",
        "merge_model": "deepseek-v4-flash",
        "cells_total": 3,
        "cells_ok": 0, "cells_error": 0,
    }
    real_repo.get_run.return_value = run_state

    monkeypatch.setattr(
        "collector.label_enrichment.routes._build_repository", lambda: real_repo,
    )
    monkeypatch.setattr(
        "collector.label_enrichment.routes._build_sqs_client", lambda: FakeSqs(),
    )
    monkeypatch.setattr(
        "collector.label_enrichment_handler._build_repository", lambda: real_repo,
    )
    monkeypatch.setenv("LABEL_ENRICHMENT_QUEUE_URL", "https://sqs.example/q")

    # Stub vendor factory in the worker
    def fake_adapters(*, vendor_names, models, secrets, request_timeout_s):
        adapters = []
        for v in vendor_names:
            a = MagicMock()
            a.name = v
            a.default_model = models[v]
            a.run.return_value = _stub_vendor_response(v)
            adapters.append(a)
        return adapters

    monkeypatch.setattr(
        "collector.label_enrichment_handler.build_adapters_from_run_config",
        fake_adapters,
    )

    # Stub merge client
    merge = MagicMock()
    merge.chat.completions.create.return_value = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps({
            "tagline": "Swedish techno powerhouse.",
            "summary": "Established techno label.",
            "ai_reasoning": "No AI signals.",
            "notes": None,
        })))],
        usage=SimpleNamespace(prompt_tokens=200, completion_tokens=80),
    )
    monkeypatch.setattr(
        "collector.label_enrichment_handler._build_merge_client", lambda *a, **k: merge,
    )

    # Stub settings
    monkeypatch.setattr(
        "collector.label_enrichment_handler.get_label_enrichment_worker_settings",
        lambda: MagicMock(
            gemini_api_key="g", openai_api_key="o",
            tavily_api_key="t", deepseek_api_key="d",
            request_timeout_s=30.0,
            ai_flag_confidence_threshold=0.5,
        ),
    )
    yield real_repo, captured_messages


def test_e2e_post_then_worker_writes_full_chain(repo_and_sqs):
    real_repo, captured_messages = repo_and_sqs

    # 1) POST creates the run + enqueues messages
    body = {
        "labels": [{"label_name": "Drumcode", "style": "techno"}],
        "vendors": ["gemini", "openai", "tavily_deepseek"],
        "models": {
            "gemini": "gemini-3-flash-preview",
            "openai": "gpt-5.4-mini",
            "tavily_deepseek": "deepseek-v4-flash",
        },
        "prompt_slug": "label_v3_app_fields",
        "prompt_version": "v1",
        "merge_vendor": "deepseek",
        "merge_model": "deepseek-v4-flash",
    }
    resp = api_handler(_admin_event(body), None)
    assert resp["statusCode"] == 202
    assert len(captured_messages) == 1

    # 2) Worker processes the message
    sqs_event = {"Records": [{"body": captured_messages[0]}]}
    result = worker_handler(sqs_event, None)
    assert result == {"processed": 1}

    # 3) Repository was driven correctly
    real_repo.mark_run_running.assert_called_once_with("run-1")
    assert real_repo.insert_cell.call_count == 3
    real_repo.upsert_label_info.assert_called_once()
    real_repo.project_ai_suspected.assert_called_once()
    real_repo.increment_run_counters.assert_called_once()

    counters = real_repo.increment_run_counters.call_args.kwargs
    assert counters["ok_delta"] == 3
    assert counters["error_delta"] == 0
    assert counters["cost_delta"] > 0.0
```

- [ ] **Step 2: Run the test**

Run: `PYTHONPATH=src pytest tests/integration/test_label_enrichment_e2e.py -v`
Expected: 1 passed.

- [ ] **Step 3: Commit**

```bash
git add tests/integration/test_label_enrichment_e2e.py
git commit -m "$(cat <<'EOF'
test(backend): end-to-end label enrichment integration test

POST -> SQS-stub -> worker -> repository chain with stub vendors.
Verifies the invariant (3 cell inserts), label_info upsert,
is_ai_suspected projection, and atomic counter update.
EOF
)"
```

---

## Spec coverage map

| Spec section | Task(s) |
|---|---|
| Async via SQS architecture | 7.1, 8.1 |
| Concurrency (ThreadPool in worker) | 5.1 |
| Removal — code (`search/`, `providers/perplexity/`, `search_handler.py`) | 9.1 |
| Removal — code (schemas/repositories/db_models/registry/settings trim) | 9.2 |
| Removal — code (`_enqueue_label_search`, `search_label_count`) | 9.3 |
| Removal — infra | 10.1 |
| Removal — DB | 1.1 |
| New schemas (`LabelInfo`, `AISignal`, enums) | 2.2 |
| Prompt registry + label_v2_facts + label_v3_app_fields | 2.3 |
| Vendor adapters (base, gemini, openai, tavily_deepseek) + pricing | 2.4, 2.5, 2.6, 2.7 |
| Aggregator (`merge_cells`) | 2.8 |
| Repository (`create_run`, `mark_run_running`, `insert_cell`, `upsert_label_info`, `project_ai_suspected`, `increment_run_counters`, `get_run`, `get_label_info`, `upsert_label_by_name`) | 4.1, 4.2, 4.3, 4.4 |
| Orchestrator (`enrich_label_for_run`, invariant) | 5.1 |
| Vendor factory | 5.2 |
| Settings (`LabelEnrichmentWorkerSettings`) | 3.1 |
| API `POST /admin/labels/enrich` | 7.1 |
| API `GET /admin/labels/enrich-runs/{run_id}` | 7.1, 7.2 |
| API `GET /admin/labels/{label_id}` | 7.1, 7.2 |
| Worker Lambda handler | 8.1 |
| Three new tables migration | 1.2 |
| Infra additions (SQS, Lambda, IAM, alarms, vars, outputs, locals, routes) | 10.2, 10.3, 10.4 |
| Packaging (`requirements.txt`) | 11.1 |
| OpenAPI regeneration | 11.2 |
| Integration test | 11.3 |
| Invariant `cells_ok + cells_error → cells_total` | 4.4, 5.1, 8.1 |
| `is_ai_suspected` column kept + repopulated | 4.3, 5.1 |

---

## Execution notes

- All commits land on `worktree-collect_info`. Do not merge to `main` until the user explicitly asks; this plan ends with a clean branch state ready for PR.
- Per-task tests must pass before committing that task. The full `pytest tests/unit -q` should be green after Task 9.3 (the last code-removal step).
- Terraform commits in Phase 10 should not be applied to AWS as part of the plan — only `terraform validate` runs. Deploy is a separate human action.
- The frontend's `schema.d.ts` regen is intentionally deferred — the SPA is out of scope per the spec.


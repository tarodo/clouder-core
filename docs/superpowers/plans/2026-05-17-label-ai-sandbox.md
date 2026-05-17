# Label AI Sandbox Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the local-only label-enrichment sandbox at `experiments/labels/` so that `python -m lab run` executes a `prompts × vendors × fixtures` matrix and emits a side-by-side markdown report. Production code under `src/collector/` is not touched.

**Architecture:** Self-contained Python package `lab` under `experiments/labels/src/lab/` with isolated `pyproject.toml`. Three vendor adapters (Anthropic Claude, xAI Grok, Perplexity sonar) implement a common `VendorAdapter` protocol; three starter prompts (`label_v1_baseline`, `label_v2_facts`, `label_v3_ai_focus`) register against a `PROMPTS` dict and share a base `LabelInfo` Pydantic schema. A thread-pool runner persists each cell as JSON; a separate `report.py` reads the cells and writes markdown. Tests mock SDK clients — no live API calls in the suite.

**Tech Stack:** Python 3.12, `pydantic>=2`, `pydantic-settings`, `anthropic`, `openai` (against xAI base URL), `httpx`, `typer`, `PyYAML`, `python-dotenv`, `pytest`.

**Spec:** `docs/superpowers/specs/2026-05-17-label-ai-sandbox-design.md` (commit `dfbd0b0`).

---

## File Structure

```
experiments/labels/
  README.md
  pyproject.toml
  .env.example
  .gitignore
  fixtures.yaml
  src/lab/
    __init__.py
    cli.py                       # typer entrypoint
    config.py                    # pydantic-settings env loader
    runner.py                    # matrix orchestration + threading
    report.py                    # markdown report generator
    schemas.py                   # LabelInfo, AISignal, enums, Fixture
    fixtures.py                  # fixtures.yaml loader
    prompts/
      __init__.py                # PROMPTS dict, register()
      base.py                    # PromptConfig dataclass + render()
      label_v1_baseline.py
      label_v2_facts.py
      label_v3_ai_focus.py
    vendors/
      __init__.py                # VENDORS dict, register()
      base.py                    # VendorAdapter protocol + VendorResponse
      pricing.py                 # per-model $/Mtok table + estimate()
      anthropic_claude.py
      xai_grok.py
      perplexity_sonar.py
  tests/
    __init__.py
    conftest.py                  # shared fixtures (tmp dirs, sample cells)
    test_schemas.py
    test_fixtures_loader.py
    test_prompts.py
    test_pricing.py
    test_vendor_anthropic.py
    test_vendor_grok.py
    test_vendor_perplexity.py
    test_config.py
    test_runner.py
    test_report.py
    test_cli.py
  outputs/                       # .gitignored, created at runtime
  reports/                       # .gitignored, created at runtime
```

Each file has one responsibility. `schemas.py` holds data models only; `runner.py` is the only place that orchestrates threading; vendor adapters never touch fixtures or prompts directly — they receive `(system, user, schema, model)`.

---

## Conventions for the Engineer

- Run every test command from `experiments/labels/`. The package's `pyproject.toml` sets `pythonpath = ["src"]` and `testpaths = ["tests"]`.
- All git commits use Conventional Commits with scope `experiments`. Project hooks reject other formats. Use the heredoc form for any multi-line body:
  ```bash
  git commit -m "$(cat <<'EOF'
  feat(experiments): subject line
  
  Optional body.
  EOF
  )"
  ```
- Never add `Co-Authored-By: Claude` trailers — the `caveman-commit` hook strips them and blocks the commit.
- Do not modify `src/collector/`, `infra/`, the root `pyproject.toml`, or any production file in this work.

---

## Task 1: Scaffold the sandbox skeleton

**Files:**
- Create: `experiments/labels/pyproject.toml`
- Create: `experiments/labels/.gitignore`
- Create: `experiments/labels/.env.example`
- Create: `experiments/labels/src/lab/__init__.py`
- Create: `experiments/labels/src/lab/prompts/__init__.py`
- Create: `experiments/labels/src/lab/vendors/__init__.py`
- Create: `experiments/labels/tests/__init__.py`

- [ ] **Step 1: Create `pyproject.toml`**

```toml
[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[project]
name = "clouder-label-lab"
version = "0.1.0"
description = "Local sandbox for comparing AI vendors/prompts on label enrichment"
requires-python = ">=3.12"
dependencies = [
    "anthropic>=0.39",
    "openai>=1.40",
    "httpx>=0.27",
    "pydantic>=2.6",
    "pydantic-settings>=2.2",
    "typer>=0.12",
    "PyYAML>=6.0",
    "python-dotenv>=1.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "pytest-mock>=3.12",
]

[project.scripts]
lab = "lab.cli:app"

[tool.setuptools.packages.find]
where = ["src"]

[tool.pytest.ini_options]
pythonpath = ["src"]
testpaths = ["tests"]
addopts = "-q"
```

- [ ] **Step 2: Create `.gitignore`**

```
.env
.venv/
__pycache__/
*.egg-info/
outputs/
reports/
.pytest_cache/
```

- [ ] **Step 3: Create `.env.example`**

```
ANTHROPIC_API_KEY=
XAI_API_KEY=
PERPLEXITY_API_KEY=

LAB_ANTHROPIC_MODEL=claude-sonnet-4-6
LAB_XAI_MODEL=grok-4
LAB_PERPLEXITY_MODEL=sonar

LAB_CONCURRENCY=4
LAB_REQUEST_TIMEOUT=60
```

- [ ] **Step 4: Create empty package init files**

Write a single empty line to each of:
- `src/lab/__init__.py`
- `src/lab/prompts/__init__.py`
- `src/lab/vendors/__init__.py`
- `tests/__init__.py`

- [ ] **Step 5: Verify install works**

```bash
cd experiments/labels
python3.12 -m venv .venv
.venv/bin/pip install -e ".[dev]"
.venv/bin/pytest --collect-only
```

Expected: `no tests ran in 0.0Xs` (no errors). If pytest can import the empty package, the layout is correct.

- [ ] **Step 6: Commit**

```bash
git add experiments/labels/pyproject.toml experiments/labels/.gitignore experiments/labels/.env.example experiments/labels/src experiments/labels/tests
git commit -m "chore(experiments): scaffold label AI sandbox"
```

---

## Task 2: LabelInfo schema and enums

**Files:**
- Create: `experiments/labels/src/lab/schemas.py`
- Create: `experiments/labels/tests/test_schemas.py`

- [ ] **Step 1: Write failing test**

`tests/test_schemas.py`:

```python
from lab.schemas import (
    ActivityLevel,
    AIContentStatus,
    AISignal,
    AISignalKind,
    LabelInfo,
)


def test_label_info_minimal_valid():
    info = LabelInfo(
        label_name="Drumcode",
        ai_reasoning="No AI signals found in available sources.",
        summary="Swedish techno label founded 1996 by Adam Beyer.",
        confidence=0.9,
    )
    assert info.label_name == "Drumcode"
    assert info.activity == ActivityLevel.UNKNOWN
    assert info.ai_content == AIContentStatus.UNKNOWN
    assert info.aliases == []
    assert info.notable_artists == []


def test_label_info_full():
    info = LabelInfo(
        label_name="NeuroBeats AI",
        country="US",
        founded_year=2023,
        catalog_size_estimate=412,
        releases_last_12_months=388,
        activity=ActivityLevel.FIRE_HOSE,
        ai_content=AIContentStatus.CONFIRMED,
        ai_signals=[
            AISignal(
                kind=AISignalKind.VOLUME,
                description="388 releases in 12 months from 4 artists",
                source_url="https://example.com/catalog",
            ),
        ],
        ai_reasoning="Volume + named tool credits.",
        summary="Heavy AI signals.",
        confidence=0.85,
    )
    assert info.activity == ActivityLevel.FIRE_HOSE
    assert info.ai_signals[0].kind == AISignalKind.VOLUME


def test_confidence_bounds():
    import pytest
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        LabelInfo(
            label_name="x",
            ai_reasoning="x",
            summary="x",
            confidence=1.5,
        )
```

- [ ] **Step 2: Run, expect import error**

```bash
.venv/bin/pytest tests/test_schemas.py -v
```

Expected: `ModuleNotFoundError: No module named 'lab.schemas'`.

- [ ] **Step 3: Implement `schemas.py`**

```python
"""Data models for the label sandbox."""

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

- [ ] **Step 4: Run, expect pass**

```bash
.venv/bin/pytest tests/test_schemas.py -v
```

Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add experiments/labels/src/lab/schemas.py experiments/labels/tests/test_schemas.py
git commit -m "feat(experiments): add LabelInfo schema"
```

---

## Task 3: Fixtures loader

**Files:**
- Create: `experiments/labels/fixtures.yaml`
- Create: `experiments/labels/src/lab/fixtures.py`
- Create: `experiments/labels/tests/test_fixtures_loader.py`
- Modify: `experiments/labels/src/lab/schemas.py` (add `Fixture` model)

- [ ] **Step 1: Add `Fixture` model to `schemas.py`**

Append to `experiments/labels/src/lab/schemas.py`:

```python
class GroundTruth(BaseModel):
    founded_year: int | None = None
    country: str | None = None
    parent_label: str | None = None
    ai_content_expected: AIContentStatus | None = None


class Fixture(BaseModel):
    id: str
    label_name: str
    style: str
    release_name: str | None = None
    ground_truth: GroundTruth | None = None


class FixturesFile(BaseModel):
    fixtures: list[Fixture]
```

- [ ] **Step 2: Write the starter `fixtures.yaml`**

```yaml
fixtures:
  - id: anjunadeep
    label_name: Anjunadeep
    style: progressive house
    release_name: null
    ground_truth:
      founded_year: 2005
      country: UK
      parent_label: Anjunabeats
      ai_content_expected: none_detected

  - id: drumcode
    label_name: Drumcode
    style: techno
    release_name: null
    ground_truth:
      founded_year: 1996
      country: Sweden
      ai_content_expected: none_detected

  - id: hessle-audio
    label_name: Hessle Audio
    style: bass / UK garage
    release_name: null
    ground_truth:
      founded_year: 2007
      country: UK
      ai_content_expected: none_detected

  - id: wisdom-teeth
    label_name: Wisdom Teeth
    style: bass / UK garage
    release_name: K-LONE - Cape Cira
    ground_truth: null

  - id: obscure-niche-2
    label_name: Pessimist Productions
    style: drum and bass
    release_name: null
    ground_truth: null

  - id: ambiguous-trap
    label_name: Vision
    style: drum and bass
    release_name: null
    ground_truth: null

  - id: synthetic-ai-trap
    label_name: NeuroBeats AI
    style: lofi
    release_name: null
    ground_truth:
      ai_content_expected: confirmed

  - id: suno-style-label
    label_name: Endless AI Records
    style: ambient
    release_name: null
    ground_truth:
      ai_content_expected: suspected
```

- [ ] **Step 3: Write failing loader test**

`tests/test_fixtures_loader.py`:

```python
from pathlib import Path

import pytest

from lab.fixtures import load_fixtures
from lab.schemas import AIContentStatus


def test_load_starter_fixtures():
    path = Path(__file__).resolve().parents[1] / "fixtures.yaml"
    fixtures = load_fixtures(path)
    by_id = {f.id: f for f in fixtures}
    assert "anjunadeep" in by_id
    assert by_id["anjunadeep"].style == "progressive house"
    assert by_id["anjunadeep"].ground_truth.country == "UK"
    assert by_id["wisdom-teeth"].release_name == "K-LONE - Cape Cira"
    assert by_id["wisdom-teeth"].ground_truth is None
    assert by_id["synthetic-ai-trap"].ground_truth.ai_content_expected == (
        AIContentStatus.CONFIRMED
    )


def test_load_rejects_duplicate_ids(tmp_path):
    p = tmp_path / "f.yaml"
    p.write_text(
        "fixtures:\n"
        "  - id: a\n    label_name: A\n    style: x\n"
        "  - id: a\n    label_name: B\n    style: y\n"
    )
    with pytest.raises(ValueError, match="duplicate"):
        load_fixtures(p)
```

- [ ] **Step 4: Run, expect import error**

```bash
.venv/bin/pytest tests/test_fixtures_loader.py -v
```

Expected: `ModuleNotFoundError: No module named 'lab.fixtures'`.

- [ ] **Step 5: Implement `fixtures.py`**

```python
"""Load and validate fixtures.yaml."""

from __future__ import annotations

from pathlib import Path

import yaml

from .schemas import Fixture, FixturesFile


def load_fixtures(path: Path) -> list[Fixture]:
    with path.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    parsed = FixturesFile.model_validate(data)

    seen: set[str] = set()
    for fixture in parsed.fixtures:
        if fixture.id in seen:
            raise ValueError(f"duplicate fixture id: {fixture.id!r}")
        seen.add(fixture.id)
    return parsed.fixtures
```

- [ ] **Step 6: Run, expect pass**

```bash
.venv/bin/pytest tests/test_fixtures_loader.py -v
```

Expected: 2 passed.

- [ ] **Step 7: Commit**

```bash
git add experiments/labels/fixtures.yaml experiments/labels/src/lab/fixtures.py experiments/labels/src/lab/schemas.py experiments/labels/tests/test_fixtures_loader.py
git commit -m "feat(experiments): add fixtures loader and starter set"
```

---

## Task 4: Prompt base and registry

**Files:**
- Create: `experiments/labels/src/lab/prompts/base.py`
- Modify: `experiments/labels/src/lab/prompts/__init__.py`
- Create: `experiments/labels/tests/test_prompts.py`

- [ ] **Step 1: Write failing tests**

`tests/test_prompts.py`:

```python
import pytest

from lab.prompts.base import PromptConfig, render_user
from lab.schemas import LabelInfo


def _make_prompt(slug: str = "demo", version: str = "v1") -> PromptConfig:
    return PromptConfig(
        slug=slug,
        version=version,
        description="demo prompt",
        system="you research labels",
        user_template='Research "{label_name}" in style "{style}".{release_block}',
        schema=LabelInfo,
    )


def test_render_user_without_release():
    cfg = _make_prompt()
    out = render_user(cfg, label_name="Drumcode", style="techno", release_name=None)
    assert out == 'Research "Drumcode" in style "techno".'


def test_render_user_with_release():
    cfg = _make_prompt()
    out = render_user(
        cfg,
        label_name="Wisdom Teeth",
        style="bass",
        release_name="K-LONE - Cape Cira",
    )
    assert out == (
        'Research "Wisdom Teeth" in style "bass".\n'
        'Recent release: K-LONE - Cape Cira'
    )


def test_registry_register_and_get():
    from lab.prompts import PROMPTS, register, get_prompt

    PROMPTS.clear()
    cfg = _make_prompt(slug="demo_a", version="v1")
    register(cfg)
    assert get_prompt("demo_a") is cfg


def test_registry_rejects_duplicate():
    from lab.prompts import PROMPTS, register

    PROMPTS.clear()
    register(_make_prompt(slug="demo_b", version="v1"))
    with pytest.raises(ValueError, match="already registered"):
        register(_make_prompt(slug="demo_b", version="v1"))
```

- [ ] **Step 2: Run, expect import error**

```bash
.venv/bin/pytest tests/test_prompts.py -v
```

Expected: `ModuleNotFoundError: No module named 'lab.prompts.base'`.

- [ ] **Step 3: Implement `prompts/base.py`**

```python
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

- [ ] **Step 4: Implement `prompts/__init__.py`**

```python
"""Prompt registry."""

from __future__ import annotations

from .base import PromptConfig

PROMPTS: dict[str, PromptConfig] = {}


def register(cfg: PromptConfig) -> None:
    if cfg.slug in PROMPTS:
        raise ValueError(f"prompt {cfg.slug!r} already registered")
    PROMPTS[cfg.slug] = cfg


def get_prompt(slug: str) -> PromptConfig:
    if slug not in PROMPTS:
        raise KeyError(f"prompt {slug!r} not found")
    return PROMPTS[slug]
```

- [ ] **Step 5: Run, expect pass**

```bash
.venv/bin/pytest tests/test_prompts.py -v
```

Expected: 4 passed.

- [ ] **Step 6: Commit**

```bash
git add experiments/labels/src/lab/prompts experiments/labels/tests/test_prompts.py
git commit -m "feat(experiments): add prompt registry and base"
```

---

## Task 5: Three starter prompts

**Files:**
- Create: `experiments/labels/src/lab/prompts/label_v1_baseline.py`
- Create: `experiments/labels/src/lab/prompts/label_v2_facts.py`
- Create: `experiments/labels/src/lab/prompts/label_v3_ai_focus.py`
- Modify: `experiments/labels/src/lab/prompts/__init__.py`
- Modify: `experiments/labels/tests/test_prompts.py` (add registration smoke test)

- [ ] **Step 1: Implement `label_v1_baseline.py`** — port of the production prompt onto the new schema

```python
"""label_v1_baseline — port of the production label prompt onto the new schema."""

from __future__ import annotations

from . import register
from .base import PromptConfig
from ..schemas import LabelInfo

SYSTEM = (
    "You are a music industry research assistant. Your task is to search "
    "for information about a specific music record label and produce a "
    "structured analysis.\n"
    "Rules:\n"
    "- Search the web for real, factual information about the label.\n"
    "- Estimate catalog_size_estimate, roster_size_estimate, and "
    "releases_last_12_months as integers based on what you find; leave null "
    "if you cannot tell.\n"
    "- founded_year is the year the label was established.\n"
    "- For ai_content: look for evidence of AI-generated music in their "
    "catalog (releases by known AI music generators, suspiciously high "
    "release volumes from unknown artists, mentions of AI in press).\n"
    "- Set confidence based on how much verifiable info you found "
    "(0.0 = guessing, 1.0 = fully verified).\n"
    "- If you cannot find the label at all, leave nullable fields null "
    "and confidence near 0."
)

USER_TEMPLATE = (
    'Research the music record label "{label_name}" that releases '
    '"{style}" music.{release_block}\n'
    "Return structured information about:\n"
    "1. How big this label is (catalog size, number of artists, market "
    "presence)\n"
    "2. How old this label is (founding year, history)\n"
    "3. Whether this label has AI-generated releases in its catalog"
)


register(
    PromptConfig(
        slug="label_v1_baseline",
        version="v1",
        description="Port of the production prompt onto the new schema.",
        system=SYSTEM,
        user_template=USER_TEMPLATE,
        schema=LabelInfo,
    )
)
```

- [ ] **Step 2: Implement `label_v2_facts.py`**

```python
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

- [ ] **Step 3: Implement `label_v3_ai_focus.py`**

```python
"""label_v3_ai_focus — label_v2_facts plus a structured AI-assessment section."""

from __future__ import annotations

from . import register
from .base import PromptConfig
from .label_v2_facts import SYSTEM as V2_SYSTEM, USER_TEMPLATE as V2_USER
from ..schemas import LabelInfo

AI_BLOCK = (
    "\n\nAI-content assessment — required steps:\n"
    "1. Check release cadence. Greater than 60 releases per 12 months "
    "from fewer than 5 artists is a volume signal.\n"
    "2. Check artist names. Generic or algorithmically-generated names "
    "('John Smith 47', 'Lofi Producer X') are a name signal.\n"
    "3. Check press and interviews for explicit AI tool credits "
    "('made with Suno', 'Udio', etc.).\n"
    "4. Check cover art. Stylistically identical AI-generated artwork "
    "across releases is a cover signal.\n"
    "5. Populate ai_signals[] with one entry per finding, each with "
    "kind, description, source_url.\n"
    "6. Set ai_content:\n"
    "   - confirmed: explicit credit or the label publicly markets AI "
    "tracks\n"
    "   - suspected: >=2 signals from steps 1-4 with sources\n"
    "   - none_detected: searched but found nothing\n"
    "   - unknown: could not search effectively\n"
    "7. ai_reasoning: 1-3 sentences citing the signals."
)


register(
    PromptConfig(
        slug="label_v3_ai_focus",
        version="v1",
        description="Facts-discipline plus structured AI assessment.",
        system=V2_SYSTEM + AI_BLOCK,
        user_template=V2_USER,
        schema=LabelInfo,
    )
)
```

- [ ] **Step 4: Make `prompts/__init__.py` auto-import the prompt modules**

Replace the contents of `src/lab/prompts/__init__.py` with:

```python
"""Prompt registry."""

from __future__ import annotations

from .base import PromptConfig

PROMPTS: dict[str, PromptConfig] = {}


def register(cfg: PromptConfig) -> None:
    if cfg.slug in PROMPTS:
        raise ValueError(f"prompt {cfg.slug!r} already registered")
    PROMPTS[cfg.slug] = cfg


def get_prompt(slug: str) -> PromptConfig:
    if slug not in PROMPTS:
        raise KeyError(f"prompt {slug!r} not found")
    return PROMPTS[slug]


def load_builtin_prompts() -> None:
    """Import the built-in prompt modules so they self-register."""
    from . import label_v1_baseline  # noqa: F401
    from . import label_v2_facts  # noqa: F401
    from . import label_v3_ai_focus  # noqa: F401
```

- [ ] **Step 5: Add registration smoke test**

Append to `tests/test_prompts.py`:

```python
def test_builtin_prompts_register():
    from lab.prompts import PROMPTS, load_builtin_prompts

    PROMPTS.clear()
    load_builtin_prompts()
    assert set(PROMPTS) == {
        "label_v1_baseline",
        "label_v2_facts",
        "label_v3_ai_focus",
    }
    # v3 extends v2's system prompt
    assert "AI-content assessment" in PROMPTS["label_v3_ai_focus"].system
    assert "AI-content assessment" not in PROMPTS["label_v2_facts"].system
```

- [ ] **Step 6: Run, expect pass**

```bash
.venv/bin/pytest tests/test_prompts.py -v
```

Expected: 5 passed.

- [ ] **Step 7: Commit**

```bash
git add experiments/labels/src/lab/prompts experiments/labels/tests/test_prompts.py
git commit -m "feat(experiments): add three starter prompts"
```

---

## Task 6: Vendor adapter base + pricing

**Files:**
- Create: `experiments/labels/src/lab/vendors/base.py`
- Create: `experiments/labels/src/lab/vendors/pricing.py`
- Modify: `experiments/labels/src/lab/vendors/__init__.py`
- Create: `experiments/labels/tests/test_pricing.py`

- [ ] **Step 1: Implement `vendors/base.py`**

```python
"""Vendor adapter protocol and response container."""

from __future__ import annotations

from dataclasses import dataclass, field
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

- [ ] **Step 2: Write failing pricing test**

`tests/test_pricing.py`:

```python
import pytest

from lab.vendors.pricing import estimate_cost


def test_estimate_anthropic_sonnet():
    # Pricing assumption: Sonnet 4.6 ≈ $3 / Mtok input, $15 / Mtok output
    cost = estimate_cost("claude-sonnet-4-6", input_tokens=1000, output_tokens=500)
    assert cost == pytest.approx(0.003 + 0.0075, rel=1e-3)


def test_estimate_unknown_model_returns_zero():
    cost = estimate_cost("does-not-exist", input_tokens=1000, output_tokens=500)
    assert cost == 0.0


def test_estimate_zero_tokens():
    assert estimate_cost("claude-sonnet-4-6", 0, 0) == 0.0
```

- [ ] **Step 3: Run, expect import error**

```bash
.venv/bin/pytest tests/test_pricing.py -v
```

Expected: `ModuleNotFoundError: No module named 'lab.vendors.pricing'`.

- [ ] **Step 4: Implement `vendors/pricing.py`**

```python
"""Approximate per-model pricing in USD per million tokens.

Values are informational only. Outdated entries are tolerable.
Update by editing the PRICING table.
"""

from __future__ import annotations

# (model_id -> (input_usd_per_mtok, output_usd_per_mtok))
PRICING: dict[str, tuple[float, float]] = {
    # Anthropic Claude
    "claude-sonnet-4-6": (3.0, 15.0),
    "claude-opus-4-7":   (15.0, 75.0),
    "claude-haiku-4-5-20251001": (0.80, 4.0),

    # xAI Grok
    "grok-4": (5.0, 15.0),
    "grok-2": (2.0, 10.0),

    # Perplexity
    "sonar":     (1.0, 1.0),
    "sonar-pro": (3.0, 15.0),
}


def estimate_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    if model not in PRICING:
        return 0.0
    in_rate, out_rate = PRICING[model]
    return (input_tokens / 1_000_000) * in_rate + (output_tokens / 1_000_000) * out_rate
```

- [ ] **Step 5: Implement `vendors/__init__.py`**

```python
"""Vendor registry."""

from __future__ import annotations

from .base import VendorAdapter, VendorResponse

VENDORS: dict[str, VendorAdapter] = {}


def register(adapter: VendorAdapter) -> None:
    if adapter.name in VENDORS:
        raise ValueError(f"vendor {adapter.name!r} already registered")
    VENDORS[adapter.name] = adapter


def get_vendor(name: str) -> VendorAdapter:
    if name not in VENDORS:
        raise KeyError(f"vendor {name!r} not found")
    return VENDORS[name]
```

- [ ] **Step 6: Run, expect pass**

```bash
.venv/bin/pytest tests/test_pricing.py -v
```

Expected: 3 passed.

- [ ] **Step 7: Commit**

```bash
git add experiments/labels/src/lab/vendors experiments/labels/tests/test_pricing.py
git commit -m "feat(experiments): add vendor adapter base and pricing"
```

---

## Task 7: Anthropic Claude adapter

**Files:**
- Create: `experiments/labels/src/lab/vendors/anthropic_claude.py`
- Create: `experiments/labels/tests/test_vendor_anthropic.py`

The adapter calls the Claude Messages API with a single tool whose `input_schema` matches the requested Pydantic schema. The model is instructed to return its answer by invoking that tool. We pull the parsed object out of the first `tool_use` block. Web search is enabled with the built-in `web_search` server tool.

- [ ] **Step 1: Write failing test**

`tests/test_vendor_anthropic.py`:

```python
from types import SimpleNamespace

import pytest

from lab.schemas import LabelInfo
from lab.vendors.anthropic_claude import AnthropicClaudeAdapter


def _mock_response(parsed_dict: dict) -> SimpleNamespace:
    """Mimic an anthropic.types.Message with a tool_use block."""
    tool_use = SimpleNamespace(
        type="tool_use",
        name="emit_label_info",
        input=parsed_dict,
    )
    return SimpleNamespace(
        content=[tool_use],
        usage=SimpleNamespace(input_tokens=400, output_tokens=300),
        model="claude-sonnet-4-6",
        stop_reason="tool_use",
    )


def _valid_payload() -> dict:
    return {
        "label_name": "Drumcode",
        "ai_reasoning": "No AI signals.",
        "summary": "Swedish techno label founded 1996.",
        "confidence": 0.9,
    }


def test_run_parses_tool_use(mocker):
    fake_client = mocker.MagicMock()
    fake_client.messages.create.return_value = _mock_response(_valid_payload())

    adapter = AnthropicClaudeAdapter(
        api_key="sk-test",
        default_model="claude-sonnet-4-6",
        client=fake_client,
    )
    resp = adapter.run(
        system="sys",
        user="usr",
        schema=LabelInfo,
    )

    assert resp.error is None
    assert isinstance(resp.parsed, LabelInfo)
    assert resp.parsed.label_name == "Drumcode"
    assert resp.model == "claude-sonnet-4-6"
    assert resp.usage["input_tokens"] == 400
    assert resp.usage["output_tokens"] == 300
    assert resp.usage["cost_usd"] > 0
    fake_client.messages.create.assert_called_once()
    call = fake_client.messages.create.call_args.kwargs
    assert call["system"] == "sys"
    assert call["messages"][0]["content"] == "usr"
    assert any(t.get("name") == "web_search" for t in call["tools"])
    assert any(t.get("name") == "emit_label_info" for t in call["tools"])


def test_run_uses_model_override(mocker):
    fake_client = mocker.MagicMock()
    fake_client.messages.create.return_value = _mock_response(_valid_payload())
    adapter = AnthropicClaudeAdapter(
        api_key="sk-test",
        default_model="claude-sonnet-4-6",
        client=fake_client,
    )
    adapter.run(system="s", user="u", schema=LabelInfo, model="claude-opus-4-7")
    call = fake_client.messages.create.call_args.kwargs
    assert call["model"] == "claude-opus-4-7"


def test_run_returns_error_on_exception(mocker):
    fake_client = mocker.MagicMock()
    fake_client.messages.create.side_effect = RuntimeError("boom")
    adapter = AnthropicClaudeAdapter(
        api_key="sk-test",
        default_model="claude-sonnet-4-6",
        client=fake_client,
    )
    resp = adapter.run(system="s", user="u", schema=LabelInfo)
    assert resp.parsed is None
    assert "boom" in resp.error
    assert resp.usage["cost_usd"] == 0.0


def test_run_returns_error_when_no_tool_use(mocker):
    fake_client = mocker.MagicMock()
    text_block = SimpleNamespace(type="text", text="no tool call")
    fake_client.messages.create.return_value = SimpleNamespace(
        content=[text_block],
        usage=SimpleNamespace(input_tokens=1, output_tokens=1),
        model="claude-sonnet-4-6",
        stop_reason="end_turn",
    )
    adapter = AnthropicClaudeAdapter(
        api_key="sk-test",
        default_model="claude-sonnet-4-6",
        client=fake_client,
    )
    resp = adapter.run(system="s", user="u", schema=LabelInfo)
    assert resp.parsed is None
    assert "no tool_use" in resp.error.lower()
```

- [ ] **Step 2: Run, expect import error**

```bash
.venv/bin/pytest tests/test_vendor_anthropic.py -v
```

Expected: `ModuleNotFoundError: No module named 'lab.vendors.anthropic_claude'`.

- [ ] **Step 3: Implement `anthropic_claude.py`**

```python
"""Anthropic Claude adapter."""

from __future__ import annotations

import time
from typing import Any, Type

from pydantic import BaseModel

from .base import VendorResponse
from .pricing import estimate_cost


class AnthropicClaudeAdapter:
    name = "anthropic"
    supports_web_search = True

    def __init__(
        self,
        api_key: str,
        default_model: str,
        timeout_s: float = 60.0,
        client: Any | None = None,
    ) -> None:
        self.default_model = default_model
        self._timeout = timeout_s
        if client is not None:
            self._client = client
        else:
            from anthropic import Anthropic

            self._client = Anthropic(api_key=api_key, timeout=timeout_s)

    def run(
        self,
        system: str,
        user: str,
        schema: Type[BaseModel],
        model: str | None = None,
    ) -> VendorResponse:
        chosen_model = model or self.default_model
        emit_tool = {
            "name": "emit_label_info",
            "description": (
                "Return the requested label info by invoking this tool exactly "
                "once with the full structured payload."
            ),
            "input_schema": schema.model_json_schema(),
        }
        web_search_tool = {
            "type": "web_search_20250305",
            "name": "web_search",
            "max_uses": 5,
        }

        started = time.monotonic()
        try:
            response = self._client.messages.create(
                model=chosen_model,
                max_tokens=4096,
                system=system,
                messages=[{"role": "user", "content": user}],
                tools=[web_search_tool, emit_tool],
            )
        except Exception as exc:  # noqa: BLE001 — adapter contract: never raise
            return VendorResponse(
                parsed=None,
                raw={},
                citations=[],
                usage={"input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0},
                latency_ms=int((time.monotonic() - started) * 1000),
                model=chosen_model,
                error=f"{type(exc).__name__}: {exc}",
            )

        latency_ms = int((time.monotonic() - started) * 1000)
        input_tokens = getattr(response.usage, "input_tokens", 0)
        output_tokens = getattr(response.usage, "output_tokens", 0)
        cost = estimate_cost(chosen_model, input_tokens, output_tokens)

        parsed: BaseModel | None = None
        citations: list[str] = []
        for block in response.content:
            if getattr(block, "type", None) == "tool_use" and getattr(block, "name", "") == "emit_label_info":
                parsed = schema.model_validate(block.input)
            elif getattr(block, "type", None) == "web_search_tool_result":
                for item in getattr(block, "content", []) or []:
                    url = getattr(item, "url", None) or (item.get("url") if isinstance(item, dict) else None)
                    if url:
                        citations.append(url)

        error: str | None = None
        if parsed is None:
            error = "no tool_use(emit_label_info) block in response"

        return VendorResponse(
            parsed=parsed,
            raw=_to_dict(response),
            citations=citations,
            usage={
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "cost_usd": cost,
            },
            latency_ms=latency_ms,
            model=chosen_model,
            error=error,
        )


def _to_dict(obj: Any) -> dict:
    """Best-effort serialization for the `raw` field. SDK objects vary in shape."""
    if hasattr(obj, "model_dump"):
        return obj.model_dump()
    if hasattr(obj, "__dict__"):
        return {k: getattr(obj, k) for k in vars(obj) if not k.startswith("_")}
    return {"repr": repr(obj)}
```

- [ ] **Step 4: Run, expect pass**

```bash
.venv/bin/pytest tests/test_vendor_anthropic.py -v
```

Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add experiments/labels/src/lab/vendors/anthropic_claude.py experiments/labels/tests/test_vendor_anthropic.py
git commit -m "feat(experiments): add Anthropic Claude adapter"
```

---

## Task 8: xAI Grok adapter

**Files:**
- Create: `experiments/labels/src/lab/vendors/xai_grok.py`
- Create: `experiments/labels/tests/test_vendor_grok.py`

Grok is OpenAI-compatible. We use the `openai` SDK pointed at `https://api.x.ai/v1`, ask for `response_format=json_schema`, and enable Live Search via `extra_body`.

- [ ] **Step 1: Write failing test**

`tests/test_vendor_grok.py`:

```python
import json
from types import SimpleNamespace

import pytest

from lab.schemas import LabelInfo
from lab.vendors.xai_grok import XAIGrokAdapter


def _valid_payload_json() -> str:
    return json.dumps(
        {
            "label_name": "Drumcode",
            "ai_reasoning": "No AI signals.",
            "summary": "Swedish techno label.",
            "confidence": 0.9,
        }
    )


def _mock_response(content: str) -> SimpleNamespace:
    choice = SimpleNamespace(
        message=SimpleNamespace(content=content),
        finish_reason="stop",
    )
    usage = SimpleNamespace(prompt_tokens=400, completion_tokens=300, total_tokens=700)
    return SimpleNamespace(
        choices=[choice],
        usage=usage,
        model="grok-4",
        citations=["https://example.com/a", "https://example.com/b"],
    )


def test_run_parses_json_content(mocker):
    fake_client = mocker.MagicMock()
    fake_client.chat.completions.create.return_value = _mock_response(_valid_payload_json())

    adapter = XAIGrokAdapter(
        api_key="xai-test",
        default_model="grok-4",
        client=fake_client,
    )
    resp = adapter.run(system="sys", user="usr", schema=LabelInfo)

    assert resp.error is None
    assert resp.parsed.label_name == "Drumcode"
    assert resp.citations == ["https://example.com/a", "https://example.com/b"]
    assert resp.usage["input_tokens"] == 400
    assert resp.usage["output_tokens"] == 300
    assert resp.usage["cost_usd"] > 0

    call = fake_client.chat.completions.create.call_args.kwargs
    assert call["model"] == "grok-4"
    assert call["messages"][0]["role"] == "system"
    assert call["messages"][0]["content"] == "sys"
    assert call["messages"][1]["content"] == "usr"
    assert call["response_format"]["type"] == "json_schema"
    assert "search_parameters" in call["extra_body"]
    assert call["extra_body"]["search_parameters"]["mode"] == "on"


def test_run_returns_error_on_bad_json(mocker):
    fake_client = mocker.MagicMock()
    fake_client.chat.completions.create.return_value = _mock_response("not json")
    adapter = XAIGrokAdapter(api_key="x", default_model="grok-4", client=fake_client)
    resp = adapter.run(system="s", user="u", schema=LabelInfo)
    assert resp.parsed is None
    assert resp.error is not None


def test_run_returns_error_on_exception(mocker):
    fake_client = mocker.MagicMock()
    fake_client.chat.completions.create.side_effect = RuntimeError("boom")
    adapter = XAIGrokAdapter(api_key="x", default_model="grok-4", client=fake_client)
    resp = adapter.run(system="s", user="u", schema=LabelInfo)
    assert resp.parsed is None
    assert "boom" in resp.error
```

- [ ] **Step 2: Run, expect import error**

```bash
.venv/bin/pytest tests/test_vendor_grok.py -v
```

Expected: `ModuleNotFoundError: No module named 'lab.vendors.xai_grok'`.

- [ ] **Step 3: Implement `xai_grok.py`**

```python
"""xAI Grok adapter via the OpenAI-compatible API."""

from __future__ import annotations

import json
import time
from typing import Any, Type

from pydantic import BaseModel, ValidationError

from .base import VendorResponse
from .pricing import estimate_cost


class XAIGrokAdapter:
    name = "xai"
    supports_web_search = True

    def __init__(
        self,
        api_key: str,
        default_model: str,
        timeout_s: float = 60.0,
        client: Any | None = None,
    ) -> None:
        self.default_model = default_model
        self._timeout = timeout_s
        if client is not None:
            self._client = client
        else:
            from openai import OpenAI

            self._client = OpenAI(
                api_key=api_key,
                base_url="https://api.x.ai/v1",
                timeout=timeout_s,
            )

    def run(
        self,
        system: str,
        user: str,
        schema: Type[BaseModel],
        model: str | None = None,
    ) -> VendorResponse:
        chosen_model = model or self.default_model
        json_schema = {
            "name": "label_info",
            "schema": schema.model_json_schema(),
            "strict": True,
        }

        started = time.monotonic()
        try:
            response = self._client.chat.completions.create(
                model=chosen_model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                response_format={"type": "json_schema", "json_schema": json_schema},
                extra_body={
                    "search_parameters": {
                        "mode": "on",
                        "return_citations": True,
                    }
                },
            )
        except Exception as exc:  # noqa: BLE001
            return VendorResponse(
                parsed=None,
                raw={},
                citations=[],
                usage={"input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0},
                latency_ms=int((time.monotonic() - started) * 1000),
                model=chosen_model,
                error=f"{type(exc).__name__}: {exc}",
            )

        latency_ms = int((time.monotonic() - started) * 1000)
        usage = response.usage
        input_tokens = getattr(usage, "prompt_tokens", 0) or 0
        output_tokens = getattr(usage, "completion_tokens", 0) or 0
        cost = estimate_cost(chosen_model, input_tokens, output_tokens)

        content = response.choices[0].message.content or ""
        citations = list(getattr(response, "citations", []) or [])

        parsed: BaseModel | None = None
        error: str | None = None
        try:
            parsed = schema.model_validate_json(content)
        except (json.JSONDecodeError, ValidationError, ValueError) as exc:
            error = f"parse error: {type(exc).__name__}: {exc}"

        return VendorResponse(
            parsed=parsed,
            raw={"content": content, "citations": citations},
            citations=citations,
            usage={
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "cost_usd": cost,
            },
            latency_ms=latency_ms,
            model=chosen_model,
            error=error,
        )
```

- [ ] **Step 4: Run, expect pass**

```bash
.venv/bin/pytest tests/test_vendor_grok.py -v
```

Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add experiments/labels/src/lab/vendors/xai_grok.py experiments/labels/tests/test_vendor_grok.py
git commit -m "feat(experiments): add xAI Grok adapter"
```

---

## Task 9: Perplexity sonar adapter

**Files:**
- Create: `experiments/labels/src/lab/vendors/perplexity_sonar.py`
- Create: `experiments/labels/tests/test_vendor_perplexity.py`

- [ ] **Step 1: Write failing test**

`tests/test_vendor_perplexity.py`:

```python
import json

import httpx
import pytest

from lab.schemas import LabelInfo
from lab.vendors.perplexity_sonar import PerplexitySonarAdapter


def _valid_payload() -> dict:
    return {
        "label_name": "Drumcode",
        "ai_reasoning": "No AI signals.",
        "summary": "Swedish techno label.",
        "confidence": 0.9,
    }


def _api_body(content_obj: dict, citations: list[str]) -> dict:
    return {
        "choices": [
            {
                "message": {"content": json.dumps(content_obj)},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 410, "completion_tokens": 280, "total_tokens": 690},
        "model": "sonar",
        "citations": citations,
    }


def test_run_parses_response():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/chat/completions"
        body = json.loads(request.content)
        assert body["model"] == "sonar"
        assert body["messages"][0]["role"] == "system"
        return httpx.Response(
            200,
            json=_api_body(_valid_payload(), ["https://example.com/x"]),
        )

    transport = httpx.MockTransport(handler)
    client = httpx.Client(transport=transport, base_url="https://api.perplexity.ai")
    adapter = PerplexitySonarAdapter(
        api_key="pplx-test",
        default_model="sonar",
        client=client,
    )
    resp = adapter.run(system="s", user="u", schema=LabelInfo)

    assert resp.error is None
    assert resp.parsed.label_name == "Drumcode"
    assert resp.citations == ["https://example.com/x"]
    assert resp.usage["input_tokens"] == 410
    assert resp.usage["output_tokens"] == 280
    assert resp.usage["cost_usd"] > 0
    assert resp.model == "sonar"


def test_run_returns_error_on_http_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="server error")

    transport = httpx.MockTransport(handler)
    client = httpx.Client(transport=transport, base_url="https://api.perplexity.ai")
    adapter = PerplexitySonarAdapter(
        api_key="pplx-test",
        default_model="sonar",
        client=client,
    )
    resp = adapter.run(system="s", user="u", schema=LabelInfo)
    assert resp.parsed is None
    assert resp.error is not None


def test_run_returns_error_on_bad_json():
    def handler(request: httpx.Request) -> httpx.Response:
        body = {
            "choices": [{"message": {"content": "not json"}}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1},
            "model": "sonar",
        }
        return httpx.Response(200, json=body)

    transport = httpx.MockTransport(handler)
    client = httpx.Client(transport=transport, base_url="https://api.perplexity.ai")
    adapter = PerplexitySonarAdapter(
        api_key="pplx-test",
        default_model="sonar",
        client=client,
    )
    resp = adapter.run(system="s", user="u", schema=LabelInfo)
    assert resp.parsed is None
    assert "parse error" in resp.error.lower()
```

- [ ] **Step 2: Run, expect import error**

```bash
.venv/bin/pytest tests/test_vendor_perplexity.py -v
```

Expected: `ModuleNotFoundError: No module named 'lab.vendors.perplexity_sonar'`.

- [ ] **Step 3: Implement `perplexity_sonar.py`**

```python
"""Perplexity sonar adapter via httpx."""

from __future__ import annotations

import json
import time
from typing import Type

import httpx
from pydantic import BaseModel, ValidationError

from .base import VendorResponse
from .pricing import estimate_cost


class PerplexitySonarAdapter:
    name = "perplexity"
    supports_web_search = True

    def __init__(
        self,
        api_key: str,
        default_model: str,
        timeout_s: float = 60.0,
        client: httpx.Client | None = None,
    ) -> None:
        self.default_model = default_model
        self._api_key = api_key
        self._timeout = timeout_s
        self._client = client or httpx.Client(
            base_url="https://api.perplexity.ai",
            timeout=timeout_s,
        )

    def run(
        self,
        system: str,
        user: str,
        schema: Type[BaseModel],
        model: str | None = None,
    ) -> VendorResponse:
        chosen_model = model or self.default_model
        payload = {
            "model": chosen_model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "response_format": {
                "type": "json_schema",
                "json_schema": {"schema": schema.model_json_schema()},
            },
            "temperature": 0.1,
        }

        started = time.monotonic()
        try:
            response = self._client.post(
                "/chat/completions",
                json=payload,
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                },
            )
            response.raise_for_status()
        except (httpx.HTTPError, httpx.HTTPStatusError) as exc:
            return VendorResponse(
                parsed=None,
                raw={},
                citations=[],
                usage={"input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0},
                latency_ms=int((time.monotonic() - started) * 1000),
                model=chosen_model,
                error=f"{type(exc).__name__}: {exc}",
            )

        latency_ms = int((time.monotonic() - started) * 1000)
        body = response.json()

        usage = body.get("usage", {}) or {}
        input_tokens = int(usage.get("prompt_tokens") or 0)
        output_tokens = int(usage.get("completion_tokens") or 0)
        cost = estimate_cost(chosen_model, input_tokens, output_tokens)
        citations = list(body.get("citations") or [])

        try:
            content = body["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            return VendorResponse(
                parsed=None,
                raw=body,
                citations=citations,
                usage={
                    "input_tokens": input_tokens,
                    "output_tokens": output_tokens,
                    "cost_usd": cost,
                },
                latency_ms=latency_ms,
                model=chosen_model,
                error=f"malformed response: {exc}",
            )

        parsed: BaseModel | None = None
        error: str | None = None
        try:
            parsed = schema.model_validate_json(content)
        except (json.JSONDecodeError, ValidationError, ValueError) as exc:
            error = f"parse error: {type(exc).__name__}: {exc}"

        return VendorResponse(
            parsed=parsed,
            raw=body,
            citations=citations,
            usage={
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "cost_usd": cost,
            },
            latency_ms=latency_ms,
            model=chosen_model,
            error=error,
        )
```

- [ ] **Step 4: Run, expect pass**

```bash
.venv/bin/pytest tests/test_vendor_perplexity.py -v
```

Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add experiments/labels/src/lab/vendors/perplexity_sonar.py experiments/labels/tests/test_vendor_perplexity.py
git commit -m "feat(experiments): add Perplexity sonar adapter"
```

---

## Task 10: Config loader

**Files:**
- Create: `experiments/labels/src/lab/config.py`
- Create: `experiments/labels/tests/test_config.py`

- [ ] **Step 1: Write failing test**

`tests/test_config.py`:

```python
import pytest

from lab.config import Settings, available_vendor_names


def test_settings_defaults(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("XAI_API_KEY", raising=False)
    monkeypatch.delenv("PERPLEXITY_API_KEY", raising=False)
    s = Settings()
    assert s.anthropic_model == "claude-sonnet-4-6"
    assert s.xai_model == "grok-4"
    assert s.perplexity_model == "sonar"
    assert s.concurrency == 4
    assert s.request_timeout == 60


def test_available_vendor_names(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")
    monkeypatch.delenv("XAI_API_KEY", raising=False)
    monkeypatch.setenv("PERPLEXITY_API_KEY", "y")
    s = Settings()
    assert available_vendor_names(s) == ["anthropic", "perplexity"]
```

- [ ] **Step 2: Run, expect import error**

```bash
.venv/bin/pytest tests/test_config.py -v
```

Expected: `ModuleNotFoundError: No module named 'lab.config'`.

- [ ] **Step 3: Implement `config.py`**

```python
"""Environment-driven configuration."""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    anthropic_api_key: str | None = None
    xai_api_key: str | None = None
    perplexity_api_key: str | None = None

    anthropic_model: str = "claude-sonnet-4-6"
    xai_model: str = "grok-4"
    perplexity_model: str = "sonar"

    concurrency: int = 4
    request_timeout: int = 60

    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="",
        env_nested_delimiter=None,
        extra="ignore",
    )


def available_vendor_names(s: Settings) -> list[str]:
    """Return the vendors for which an API key is configured."""
    out: list[str] = []
    if s.anthropic_api_key:
        out.append("anthropic")
    if s.xai_api_key:
        out.append("xai")
    if s.perplexity_api_key:
        out.append("perplexity")
    return out
```

Note: `pydantic-settings` maps `ANTHROPIC_API_KEY` → `anthropic_api_key`, `LAB_CONCURRENCY` would not match. We rename the env vars in `.env.example` to drop the `LAB_` prefix so that `pydantic-settings` picks them up by default.

- [ ] **Step 4: Fix `.env.example` env names to match the loader**

Replace `.env.example` with:

```
ANTHROPIC_API_KEY=
XAI_API_KEY=
PERPLEXITY_API_KEY=

ANTHROPIC_MODEL=claude-sonnet-4-6
XAI_MODEL=grok-4
PERPLEXITY_MODEL=sonar

CONCURRENCY=4
REQUEST_TIMEOUT=60
```

- [ ] **Step 5: Run, expect pass**

```bash
.venv/bin/pytest tests/test_config.py -v
```

Expected: 2 passed.

- [ ] **Step 6: Commit**

```bash
git add experiments/labels/src/lab/config.py experiments/labels/.env.example experiments/labels/tests/test_config.py
git commit -m "feat(experiments): add settings loader"
```

---

## Task 11: Matrix runner

**Files:**
- Create: `experiments/labels/src/lab/runner.py`
- Create: `experiments/labels/tests/conftest.py`
- Create: `experiments/labels/tests/test_runner.py`

The runner orchestrates the matrix, persists each cell as JSON, and writes a manifest. Tests use stub vendors that return canned responses — no live network.

- [ ] **Step 1: Add shared fixtures in `tests/conftest.py`**

```python
"""Shared test helpers."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Type

from pydantic import BaseModel

from lab.schemas import Fixture, LabelInfo
from lab.vendors.base import VendorResponse


@dataclass
class StubVendor:
    name: str
    default_model: str = "stub-model"
    supports_web_search: bool = True

    def __post_init__(self) -> None:
        self.calls: list[tuple[str, str, str]] = []

    def run(
        self,
        system: str,
        user: str,
        schema: Type[BaseModel],
        model: str | None = None,
    ) -> VendorResponse:
        chosen = model or self.default_model
        self.calls.append((system, user, chosen))
        parsed = schema.model_validate(
            {
                "label_name": "Stubbed",
                "ai_reasoning": f"stub from {self.name}",
                "summary": f"stub summary from {self.name}",
                "confidence": 0.5,
            }
        )
        return VendorResponse(
            parsed=parsed,
            raw={"stub": True, "vendor": self.name},
            citations=["https://stub"],
            usage={"input_tokens": 10, "output_tokens": 20, "cost_usd": 0.0001},
            latency_ms=12,
            model=chosen,
            error=None,
        )


def make_fixture(id: str, label: str, style: str = "techno") -> Fixture:
    return Fixture(id=id, label_name=label, style=style)
```

- [ ] **Step 2: Write failing runner test**

`tests/test_runner.py`:

```python
import json
from pathlib import Path

import pytest

from lab.prompts import load_builtin_prompts, PROMPTS
from lab.runner import RunSpec, run_matrix
from tests.conftest import StubVendor, make_fixture


@pytest.fixture(autouse=True)
def _prompts_loaded():
    PROMPTS.clear()
    load_builtin_prompts()


def test_run_matrix_writes_cells_and_manifest(tmp_path):
    vendors = [StubVendor("anthropic"), StubVendor("xai")]
    fixtures = [make_fixture("drumcode", "Drumcode"), make_fixture("anjuna", "Anjunadeep", "progressive house")]
    prompts = ["label_v1_baseline", "label_v2_facts"]

    spec = RunSpec(
        prompts=prompts,
        vendors=vendors,
        fixtures=fixtures,
        outputs_root=tmp_path,
        concurrency=2,
    )
    result = run_matrix(spec)

    expected_cells = len(prompts) * len(vendors) * len(fixtures)
    assert result.totals["cells"] == expected_cells
    assert result.totals["ok"] == expected_cells
    assert result.totals["error"] == 0

    run_dir = tmp_path / result.run_id
    cell_files = sorted(p.name for p in run_dir.glob("*.json") if p.name != "manifest.json")
    assert len(cell_files) == expected_cells

    sample = json.loads((run_dir / cell_files[0]).read_text())
    assert sample["run_id"] == result.run_id
    assert "rendered_user_prompt" in sample
    assert sample["response"]["parsed"]["label_name"] == "Stubbed"

    manifest = json.loads((run_dir / "manifest.json").read_text())
    assert manifest["run_id"] == result.run_id
    assert {p["slug"] for p in manifest["prompts"]} == set(prompts)
    assert {v["name"] for v in manifest["vendors"]} == {"anthropic", "xai"}
    assert sorted(manifest["fixtures"]) == ["anjuna", "drumcode"]


def test_run_matrix_filters_subset(tmp_path):
    vendors = [StubVendor("anthropic")]
    fixtures = [make_fixture("drumcode", "Drumcode")]
    prompts = ["label_v2_facts"]

    spec = RunSpec(
        prompts=prompts,
        vendors=vendors,
        fixtures=fixtures,
        outputs_root=tmp_path,
        concurrency=1,
    )
    result = run_matrix(spec)
    assert result.totals["cells"] == 1
    cell = next((tmp_path / result.run_id).glob("label_v2_facts__anthropic__drumcode.json"))
    payload = json.loads(cell.read_text())
    assert payload["prompt"]["slug"] == "label_v2_facts"
    assert payload["vendor"]["name"] == "anthropic"


def test_run_matrix_records_vendor_error(tmp_path):
    class FailingVendor(StubVendor):
        def run(self, system, user, schema, model=None):
            from lab.vendors.base import VendorResponse
            return VendorResponse(
                parsed=None,
                raw={},
                citations=[],
                usage={"input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0},
                latency_ms=5,
                model=model or self.default_model,
                error="simulated failure",
            )

    spec = RunSpec(
        prompts=["label_v1_baseline"],
        vendors=[FailingVendor("xai")],
        fixtures=[make_fixture("drumcode", "Drumcode")],
        outputs_root=tmp_path,
        concurrency=1,
    )
    result = run_matrix(spec)
    assert result.totals["ok"] == 0
    assert result.totals["error"] == 1
    cell = next((tmp_path / result.run_id).glob("*.json"))
    payload = json.loads(cell.read_text())
    assert payload["error"] == "simulated failure"
    assert payload["response"]["parsed"] is None
```

- [ ] **Step 3: Run, expect import error**

```bash
.venv/bin/pytest tests/test_runner.py -v
```

Expected: `ModuleNotFoundError: No module named 'lab.runner'`.

- [ ] **Step 4: Implement `runner.py`**

```python
"""Matrix runner: prompts × vendors × fixtures → JSON cells + manifest."""

from __future__ import annotations

import json
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from pydantic import BaseModel

from .prompts import PROMPTS, get_prompt
from .prompts.base import render_user
from .schemas import Fixture
from .vendors.base import VendorAdapter, VendorResponse


@dataclass
class RunSpec:
    prompts: list[str]
    vendors: list[VendorAdapter]
    fixtures: list[Fixture]
    outputs_root: Path
    concurrency: int = 4


@dataclass
class RunResult:
    run_id: str
    totals: dict


def run_matrix(spec: RunSpec) -> RunResult:
    run_id = _new_run_id()
    run_dir = spec.outputs_root / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    cells: list[_Cell] = []
    for prompt_slug in spec.prompts:
        prompt = get_prompt(prompt_slug)
        for vendor in spec.vendors:
            for fixture in spec.fixtures:
                cells.append(_Cell(prompt_slug=prompt_slug, vendor=vendor, fixture=fixture))

    started = datetime.now(timezone.utc)
    ok = 0
    err = 0
    cost_total = 0.0

    with ThreadPoolExecutor(max_workers=max(1, spec.concurrency)) as pool:
        future_to_cell = {pool.submit(_execute_cell, c, run_id, run_dir): c for c in cells}
        total = len(cells)
        done = 0
        for fut in as_completed(future_to_cell):
            cell = future_to_cell[fut]
            done += 1
            try:
                resp: VendorResponse = fut.result()
            except Exception as exc:  # noqa: BLE001 — defensive
                err += 1
                print(f"[{done}/{total}] {cell.label()} ... crashed: {exc}")
                continue
            cost_total += float(resp.usage.get("cost_usd") or 0.0)
            if resp.error is None and resp.parsed is not None:
                ok += 1
                status = "ok"
            else:
                err += 1
                status = f"error: {resp.error}"
            print(
                f"[{done}/{total}] {cell.label()} ... {status} "
                f"({resp.latency_ms}ms, ${resp.usage.get('cost_usd', 0):.4f})"
            )

    finished = datetime.now(timezone.utc)
    manifest = {
        "run_id": run_id,
        "started_at": started.isoformat(),
        "finished_at": finished.isoformat(),
        "prompts": [
            {"slug": p, "version": get_prompt(p).version} for p in spec.prompts
        ],
        "vendors": [
            {"name": v.name, "model": v.default_model} for v in spec.vendors
        ],
        "fixtures": [f.id for f in spec.fixtures],
        "totals": {
            "cells": len(cells),
            "ok": ok,
            "error": err,
            "cost_usd": round(cost_total, 4),
        },
    }
    (run_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    return RunResult(run_id=run_id, totals=manifest["totals"])


@dataclass
class _Cell:
    prompt_slug: str
    vendor: VendorAdapter
    fixture: Fixture

    def label(self) -> str:
        return f"{self.prompt_slug} × {self.vendor.name} × {self.fixture.id}"

    def file_name(self) -> str:
        return f"{self.prompt_slug}__{self.vendor.name}__{self.fixture.id}.json"


def _execute_cell(cell: _Cell, run_id: str, run_dir: Path) -> VendorResponse:
    prompt = get_prompt(cell.prompt_slug)
    model = prompt.vendor_overrides.get(cell.vendor.name)
    user = render_user(
        prompt,
        label_name=cell.fixture.label_name,
        style=cell.fixture.style,
        release_name=cell.fixture.release_name,
    )
    resp = cell.vendor.run(system=prompt.system, user=user, schema=prompt.schema, model=model)
    payload = {
        "run_id": run_id,
        "prompt": {"slug": prompt.slug, "version": prompt.version},
        "vendor": {"name": cell.vendor.name, "model": resp.model},
        "fixture": cell.fixture.model_dump(),
        "rendered_user_prompt": user,
        "response": {
            "parsed": resp.parsed.model_dump() if resp.parsed is not None else None,
            "citations": resp.citations,
            "usage": resp.usage,
            "latency_ms": resp.latency_ms,
            "raw": _safe(resp.raw),
        },
        "error": resp.error,
    }
    (run_dir / cell.file_name()).write_text(
        json.dumps(payload, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8",
    )
    return resp


def _safe(obj):
    """Drop Authorization-like fields from raw responses before persisting."""
    if isinstance(obj, dict):
        return {
            k: "<masked>" if k.lower() in {"authorization", "api-key", "x-api-key"} else _safe(v)
            for k, v in obj.items()
        }
    if isinstance(obj, list):
        return [_safe(v) for v in obj]
    return obj


def _new_run_id() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:4]
```

- [ ] **Step 5: Run, expect pass**

```bash
.venv/bin/pytest tests/test_runner.py -v
```

Expected: 3 passed.

- [ ] **Step 6: Commit**

```bash
git add experiments/labels/src/lab/runner.py experiments/labels/tests/conftest.py experiments/labels/tests/test_runner.py
git commit -m "feat(experiments): add matrix runner"
```

---

## Task 12: Markdown report generator

**Files:**
- Create: `experiments/labels/src/lab/report.py`
- Create: `experiments/labels/tests/test_report.py`

The report reads `outputs/<run_id>/`, groups cells by fixture, and writes `reports/<run_id>.md` with three sections: summary, per-fixture side-by-side tables, full-response details. Missing fields render as `—`. Ground truth produces `✓` / `✗` annotations.

- [ ] **Step 1: Write failing test**

`tests/test_report.py`:

```python
import json
from pathlib import Path


def _write_cell(run_dir: Path, prompt: str, vendor: str, fixture_id: str, parsed: dict, error: str | None = None) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "run_id": run_dir.name,
        "prompt": {"slug": prompt, "version": "v1"},
        "vendor": {"name": vendor, "model": f"{vendor}-model"},
        "fixture": {
            "id": fixture_id,
            "label_name": parsed.get("label_name", fixture_id),
            "style": "techno",
            "release_name": None,
            "ground_truth": {"founded_year": 1996, "country": "Sweden", "parent_label": None, "ai_content_expected": "none_detected"}
            if fixture_id == "drumcode"
            else None,
        },
        "rendered_user_prompt": "...",
        "response": {
            "parsed": None if error else parsed,
            "citations": ["https://example.com"],
            "usage": {"input_tokens": 100, "output_tokens": 200, "cost_usd": 0.001},
            "latency_ms": 1234,
            "raw": {},
        },
        "error": error,
    }
    (run_dir / f"{prompt}__{vendor}__{fixture_id}.json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def _write_manifest(run_dir: Path, ok: int, err: int, cost: float) -> None:
    manifest = {
        "run_id": run_dir.name,
        "started_at": "2026-05-17T10:00:00+00:00",
        "finished_at": "2026-05-17T10:01:00+00:00",
        "prompts": [{"slug": "label_v1_baseline", "version": "v1"}, {"slug": "label_v2_facts", "version": "v1"}],
        "vendors": [{"name": "anthropic", "model": "claude-sonnet-4-6"}, {"name": "xai", "model": "grok-4"}],
        "fixtures": ["drumcode"],
        "totals": {"cells": ok + err, "ok": ok, "error": err, "cost_usd": cost},
    }
    (run_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def test_build_report_renders_sections(tmp_path):
    from lab.report import build_report

    run_dir = tmp_path / "outputs" / "20260517-100000-abcd"
    reports_dir = tmp_path / "reports"

    _write_cell(run_dir, "label_v1_baseline", "anthropic", "drumcode",
                {"label_name": "Drumcode", "founded_year": 1996, "country": "Sweden",
                 "ai_content": "none_detected", "ai_reasoning": "—",
                 "summary": "Techno label.", "confidence": 0.9, "notable_artists": ["Adam Beyer"]})
    _write_cell(run_dir, "label_v1_baseline", "xai", "drumcode",
                {"label_name": "Drumcode", "founded_year": 1995, "country": "Sweden",
                 "ai_content": "none_detected", "ai_reasoning": "—",
                 "summary": "Techno label.", "confidence": 0.7, "notable_artists": []})
    _write_cell(run_dir, "label_v2_facts", "anthropic", "drumcode",
                {"label_name": "Drumcode", "founded_year": 1996, "country": "Sweden",
                 "ai_content": "none_detected", "ai_reasoning": "—",
                 "summary": "Techno label, with sourced facts.", "confidence": 0.95,
                 "notable_artists": ["Adam Beyer", "Joel Mull"]})
    _write_cell(run_dir, "label_v2_facts", "xai", "drumcode",
                {}, error="simulated failure")

    _write_manifest(run_dir, ok=3, err=1, cost=0.0041)

    out_path = build_report(run_dir, reports_dir)
    text = out_path.read_text(encoding="utf-8")

    assert out_path.name.startswith("20260517-100000-abcd")
    assert "## Summary" in text
    assert "ok: 3" in text
    assert "error: 1" in text
    assert "## Fixture: drumcode" in text
    # ground truth check: 1996 matches → ✓; 1995 → ✗
    assert "1996 ✓" in text
    assert "1995 ✗" in text
    # error cell rendered as em dash + error
    assert "simulated failure" in text
    # details section present
    assert "<details>" in text
    # missing field renders as em dash (xai v1 has no notable artists set; the cell parsed has empty list)
    assert "—" in text
```

- [ ] **Step 2: Run, expect import error**

```bash
.venv/bin/pytest tests/test_report.py -v
```

Expected: `ModuleNotFoundError: No module named 'lab.report'`.

- [ ] **Step 3: Implement `report.py`**

```python
"""Markdown report generator."""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Any

# Fields shown in the per-fixture side-by-side table, in order
TABLE_FIELDS: list[str] = [
    "founded_year",
    "country",
    "parent_label",
    "catalog_size_estimate",
    "releases_last_12_months",
    "activity",
    "ai_content",
    "confidence",
    "notable_artists",
]

EMPTY = "—"


def build_report(run_dir: Path, reports_dir: Path) -> Path:
    reports_dir.mkdir(parents=True, exist_ok=True)
    run_id = run_dir.name
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))

    cells = _load_cells(run_dir)
    cells_by_fixture = defaultdict(list)
    for cell in cells:
        cells_by_fixture[cell["fixture"]["id"]].append(cell)

    lines: list[str] = []
    lines.append(f"# Run report — `{run_id}`")
    lines.append("")
    lines.extend(_summary_section(manifest, cells))
    for fixture_id in sorted(cells_by_fixture):
        lines.extend(_fixture_section(fixture_id, cells_by_fixture[fixture_id]))
    lines.extend(_details_section(cells))

    out_path = reports_dir / f"{run_id}.md"
    out_path.write_text("\n".join(lines), encoding="utf-8")
    return out_path


def _load_cells(run_dir: Path) -> list[dict]:
    cells = []
    for path in sorted(run_dir.glob("*.json")):
        if path.name == "manifest.json":
            continue
        cells.append(json.loads(path.read_text(encoding="utf-8")))
    return cells


def _summary_section(manifest: dict, cells: list[dict]) -> list[str]:
    totals = manifest["totals"]
    by_vendor_latency: dict[str, list[int]] = defaultdict(list)
    by_vendor_cost: dict[str, float] = defaultdict(float)
    for cell in cells:
        v = cell["vendor"]["name"]
        by_vendor_latency[v].append(int(cell["response"]["latency_ms"]))
        by_vendor_cost[v] += float(cell["response"]["usage"].get("cost_usd") or 0.0)
    rows = []
    rows.append("## Summary")
    rows.append("")
    rows.append(f"- cells: {totals['cells']}")
    rows.append(f"- ok: {totals['ok']}")
    rows.append(f"- error: {totals['error']}")
    rows.append(f"- total cost: ${totals['cost_usd']:.4f}")
    rows.append("")
    rows.append("| Vendor | Mean latency (ms) | Total cost (USD) |")
    rows.append("| --- | --- | --- |")
    for v in sorted(by_vendor_latency):
        mean = sum(by_vendor_latency[v]) / len(by_vendor_latency[v])
        rows.append(f"| {v} | {mean:.0f} | {by_vendor_cost[v]:.4f} |")
    rows.append("")
    return rows


def _fixture_section(fixture_id: str, cells: list[dict]) -> list[str]:
    if not cells:
        return []
    first = cells[0]
    label_name = first["fixture"]["label_name"]
    style = first["fixture"]["style"]
    truth = first["fixture"].get("ground_truth") or {}

    rows = []
    rows.append(f"## Fixture: {fixture_id}")
    rows.append("")
    rows.append(f"**{label_name}** — {style}")
    if truth:
        bits = [f"{k}={v}" for k, v in truth.items() if v is not None]
        if bits:
            rows.append(f"_Ground truth:_ {', '.join(bits)}")
    rows.append("")

    headers = ["field"] + [f"{c['prompt']['slug']} / {c['vendor']['name']}" for c in cells]
    rows.append("| " + " | ".join(headers) + " |")
    rows.append("| " + " | ".join(["---"] * len(headers)) + " |")
    for field in TABLE_FIELDS:
        row_cells = [field]
        for cell in cells:
            row_cells.append(_render_cell_field(cell, field, truth))
        rows.append("| " + " | ".join(row_cells) + " |")
    rows.append("")
    return rows


def _render_cell_field(cell: dict, field: str, truth: dict) -> str:
    if cell["error"] or cell["response"]["parsed"] is None:
        return f"error: {cell['error'] or 'no parse'}"
    parsed = cell["response"]["parsed"]
    raw_value = parsed.get(field, None)
    if raw_value is None or raw_value == [] or raw_value == "":
        rendered = EMPTY
    elif isinstance(raw_value, list):
        rendered = ", ".join(str(v) for v in raw_value)
    else:
        rendered = str(raw_value)

    # Ground-truth annotation
    expected = None
    if field == "founded_year":
        expected = truth.get("founded_year")
    elif field == "country":
        expected = truth.get("country")
    elif field == "parent_label":
        expected = truth.get("parent_label")
    elif field == "ai_content":
        expected = truth.get("ai_content_expected")
    if expected is not None and rendered != EMPTY:
        rendered += " ✓" if str(raw_value) == str(expected) else " ✗"
    return rendered


def _details_section(cells: list[dict]) -> list[str]:
    rows: list[str] = ["## Full responses", ""]
    for cell in cells:
        title = (
            f"{cell['fixture']['id']} — {cell['prompt']['slug']} / "
            f"{cell['vendor']['name']} ({cell['vendor']['model']})"
        )
        rows.append("<details>")
        rows.append(f"<summary>{title}</summary>")
        rows.append("")
        if cell["error"] or cell["response"]["parsed"] is None:
            rows.append(f"**error:** {cell['error'] or 'no parse'}")
        else:
            parsed = cell["response"]["parsed"]
            summary = parsed.get("summary") or EMPTY
            artists = parsed.get("notable_artists") or []
            reasoning = parsed.get("ai_reasoning") or EMPTY
            rows.append(f"**summary:** {summary}")
            rows.append("")
            rows.append(f"**notable artists:** {', '.join(artists) if artists else EMPTY}")
            rows.append("")
            rows.append(f"**ai_reasoning:** {reasoning}")
        rows.append("")
        rows.append("</details>")
        rows.append("")
    return rows
```

- [ ] **Step 4: Run, expect pass**

```bash
.venv/bin/pytest tests/test_report.py -v
```

Expected: 1 passed.

- [ ] **Step 5: Commit**

```bash
git add experiments/labels/src/lab/report.py experiments/labels/tests/test_report.py
git commit -m "feat(experiments): add markdown report generator"
```

---

## Task 13: CLI

**Files:**
- Create: `experiments/labels/src/lab/cli.py`
- Create: `experiments/labels/tests/test_cli.py`

The CLI wires runner + report together. Subcommands:
- `run [--prompts ...] [--vendors ...] [--fixtures ...] [--concurrency N]`
- `list prompts | vendors | fixtures`
- `report <run_id>`

- [ ] **Step 1: Write failing test**

`tests/test_cli.py`:

```python
import json
from pathlib import Path

from typer.testing import CliRunner

from lab.cli import app


runner = CliRunner()


def test_list_prompts():
    result = runner.invoke(app, ["list", "prompts"])
    assert result.exit_code == 0
    assert "label_v1_baseline" in result.stdout
    assert "label_v2_facts" in result.stdout
    assert "label_v3_ai_focus" in result.stdout


def test_list_fixtures():
    result = runner.invoke(app, ["list", "fixtures"])
    assert result.exit_code == 0
    assert "drumcode" in result.stdout
    assert "anjunadeep" in result.stdout


def test_run_with_stub_vendors(tmp_path, monkeypatch):
    """End-to-end CLI exercise. Replaces vendor builder with stubs so no API is hit."""
    from tests.conftest import StubVendor
    import lab.cli as cli_mod

    monkeypatch.setattr(
        cli_mod,
        "build_vendors",
        lambda settings, names: [StubVendor("anthropic")],
    )
    monkeypatch.setattr(cli_mod, "OUTPUTS_ROOT", tmp_path / "outputs")
    monkeypatch.setattr(cli_mod, "REPORTS_ROOT", tmp_path / "reports")

    result = runner.invoke(app, [
        "run",
        "--prompts", "label_v1_baseline",
        "--vendors", "anthropic",
        "--fixtures", "drumcode",
        "--concurrency", "1",
    ])
    assert result.exit_code == 0, result.stdout

    run_dirs = list((tmp_path / "outputs").iterdir())
    assert len(run_dirs) == 1
    manifest = json.loads((run_dirs[0] / "manifest.json").read_text())
    assert manifest["totals"]["ok"] == 1
    assert manifest["totals"]["error"] == 0

    report_files = list((tmp_path / "reports").glob("*.md"))
    assert len(report_files) == 1
    assert "label_v1_baseline" in report_files[0].read_text()
```

- [ ] **Step 2: Run, expect import error**

```bash
.venv/bin/pytest tests/test_cli.py -v
```

Expected: `ModuleNotFoundError: No module named 'lab.cli'`.

- [ ] **Step 3: Implement `cli.py`**

```python
"""`lab` CLI."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Iterable

import typer

from .config import Settings, available_vendor_names
from .fixtures import load_fixtures
from .prompts import PROMPTS, load_builtin_prompts
from .report import build_report
from .runner import RunSpec, run_matrix
from .vendors.anthropic_claude import AnthropicClaudeAdapter
from .vendors.base import VendorAdapter
from .vendors.perplexity_sonar import PerplexitySonarAdapter
from .vendors.xai_grok import XAIGrokAdapter

ROOT = Path(__file__).resolve().parents[3]  # experiments/labels/
FIXTURES_PATH = ROOT / "fixtures.yaml"
OUTPUTS_ROOT = ROOT / "outputs"
REPORTS_ROOT = ROOT / "reports"

app = typer.Typer(help="Local sandbox for label AI experiments.")
list_app = typer.Typer(help="List registered prompts, vendors, or fixtures.")
app.add_typer(list_app, name="list")


def build_vendors(settings: Settings, names: list[str]) -> list[VendorAdapter]:
    adapters: list[VendorAdapter] = []
    if "anthropic" in names and settings.anthropic_api_key:
        adapters.append(AnthropicClaudeAdapter(
            api_key=settings.anthropic_api_key,
            default_model=settings.anthropic_model,
            timeout_s=settings.request_timeout,
        ))
    if "xai" in names and settings.xai_api_key:
        adapters.append(XAIGrokAdapter(
            api_key=settings.xai_api_key,
            default_model=settings.xai_model,
            timeout_s=settings.request_timeout,
        ))
    if "perplexity" in names and settings.perplexity_api_key:
        adapters.append(PerplexitySonarAdapter(
            api_key=settings.perplexity_api_key,
            default_model=settings.perplexity_model,
            timeout_s=settings.request_timeout,
        ))
    return adapters


def _parse_csv(value: str | None) -> list[str] | None:
    if not value:
        return None
    return [v.strip() for v in value.split(",") if v.strip()]


@app.command()
def run(
    prompts: str = typer.Option(None, "--prompts", help="Comma-separated prompt slugs"),
    vendors: str = typer.Option(None, "--vendors", help="Comma-separated vendor names"),
    fixtures: str = typer.Option(None, "--fixtures", help="Comma-separated fixture ids"),
    concurrency: int = typer.Option(None, "--concurrency", help="Override LAB concurrency"),
) -> None:
    """Run the prompts × vendors × fixtures matrix."""
    load_builtin_prompts()
    settings = Settings()

    selected_prompts = _parse_csv(prompts) or sorted(PROMPTS)
    for slug in selected_prompts:
        if slug not in PROMPTS:
            typer.echo(f"unknown prompt: {slug}", err=True)
            raise typer.Exit(2)

    all_vendor_names = available_vendor_names(settings)
    if not all_vendor_names:
        typer.echo("no API keys configured; nothing to do", err=True)
        raise typer.Exit(2)
    selected_vendor_names = _parse_csv(vendors) or all_vendor_names
    missing = [n for n in selected_vendor_names if n not in all_vendor_names]
    if missing:
        typer.echo(f"vendors without API keys: {', '.join(missing)} (skipping)")
    selected_vendor_names = [n for n in selected_vendor_names if n in all_vendor_names]
    vendor_adapters = build_vendors(settings, selected_vendor_names)
    if not vendor_adapters:
        typer.echo("no usable vendors after filtering", err=True)
        raise typer.Exit(2)

    all_fixtures = load_fixtures(FIXTURES_PATH)
    selected_fixture_ids = _parse_csv(fixtures)
    selected_fixtures = (
        [f for f in all_fixtures if f.id in selected_fixture_ids]
        if selected_fixture_ids
        else all_fixtures
    )
    if not selected_fixtures:
        typer.echo("no fixtures selected", err=True)
        raise typer.Exit(2)

    spec = RunSpec(
        prompts=selected_prompts,
        vendors=vendor_adapters,
        fixtures=selected_fixtures,
        outputs_root=OUTPUTS_ROOT,
        concurrency=concurrency or settings.concurrency,
    )
    result = run_matrix(spec)
    out_path = build_report(OUTPUTS_ROOT / result.run_id, REPORTS_ROOT)
    typer.echo(f"run_id: {result.run_id}")
    typer.echo(f"report: {out_path}")


@app.command()
def report(run_id: str) -> None:
    """Regenerate the report from an existing run directory."""
    run_dir = OUTPUTS_ROOT / run_id
    if not run_dir.exists():
        typer.echo(f"no such run: {run_id}", err=True)
        raise typer.Exit(2)
    out_path = build_report(run_dir, REPORTS_ROOT)
    typer.echo(str(out_path))


@list_app.command("prompts")
def list_prompts() -> None:
    load_builtin_prompts()
    for slug in sorted(PROMPTS):
        cfg = PROMPTS[slug]
        typer.echo(f"{slug}/{cfg.version} — {cfg.description}")


@list_app.command("vendors")
def list_vendors() -> None:
    settings = Settings()
    names = available_vendor_names(settings)
    if not names:
        typer.echo("no vendors configured (no API keys in .env)")
        return
    for name in names:
        typer.echo(name)


@list_app.command("fixtures")
def list_fixtures() -> None:
    for f in load_fixtures(FIXTURES_PATH):
        gt = "with ground_truth" if f.ground_truth else "no ground_truth"
        rel = f", release={f.release_name}" if f.release_name else ""
        typer.echo(f"{f.id} — {f.label_name} / {f.style} ({gt}){rel}")


if __name__ == "__main__":
    app()
```

- [ ] **Step 4: Run, expect pass**

```bash
.venv/bin/pytest tests/test_cli.py -v
```

Expected: 3 passed.

- [ ] **Step 5: Run the full suite**

```bash
.venv/bin/pytest
```

Expected: all tests pass (~25–30 tests).

- [ ] **Step 6: Commit**

```bash
git add experiments/labels/src/lab/cli.py experiments/labels/tests/test_cli.py
git commit -m "feat(experiments): add lab CLI"
```

---

## Task 14: README

**Files:**
- Create: `experiments/labels/README.md`

- [ ] **Step 1: Write the README**

```markdown
# Label AI Sandbox

Local-only experiment harness for comparing AI vendors and prompts on the
"music label info enrichment" task. Production code under `src/collector/`
is not touched by this directory.

Design spec: `docs/superpowers/specs/2026-05-17-label-ai-sandbox-design.md`

## Setup

```bash
cd experiments/labels
python3.12 -m venv .venv
.venv/bin/pip install -e ".[dev]"
cp .env.example .env
# edit .env and add your API keys (any subset is fine; missing vendors are skipped)
```

## Run

```bash
# full matrix
.venv/bin/lab run

# subset
.venv/bin/lab run --prompts label_v2_facts --vendors anthropic --fixtures drumcode

# inspect
.venv/bin/lab list prompts
.venv/bin/lab list vendors
.venv/bin/lab list fixtures

# regenerate report only
.venv/bin/lab report <run_id>
```

Outputs land in:
- `outputs/<run_id>/<prompt>__<vendor>__<fixture>.json` — one raw cell each
- `outputs/<run_id>/manifest.json` — what was run
- `reports/<run_id>.md` — side-by-side markdown report

`outputs/` and `reports/` are gitignored.

## Tests

```bash
.venv/bin/pytest
```

All tests use mocked SDK clients. No live API call.

## Adding a prompt

1. Create `src/lab/prompts/label_<slug>.py`
2. `register(PromptConfig(...))` in the module
3. Import it from `load_builtin_prompts()` in `src/lab/prompts/__init__.py`

## Adding a vendor

1. Create `src/lab/vendors/<vendor>.py` implementing the `VendorAdapter` protocol
2. Add it to `build_vendors()` in `src/lab/cli.py`
3. Add an `<VENDOR>_API_KEY` entry to `.env.example` and `Settings` in `config.py`
```

- [ ] **Step 2: Commit**

```bash
git add experiments/labels/README.md
git commit -m "docs(experiments): add label sandbox README"
```

---

## Final verification

- [ ] **Step 1: Run the whole suite from the sandbox**

```bash
cd experiments/labels
.venv/bin/pytest
```

Expected: all green.

- [ ] **Step 2: Smoke the CLI without making API calls**

```bash
.venv/bin/lab list prompts
.venv/bin/lab list fixtures
.venv/bin/lab list vendors   # may print "no vendors configured" if .env is empty
```

Expected: prints registered prompts/fixtures; vendors lists whichever keys are present.

- [ ] **Step 3: Confirm production untouched**

```bash
git diff --stat main -- src/ infra/ alembic/
```

Expected: empty output. Production tree was not modified.

---

## Self-Review Checklist (already applied)

- Spec sections 3, 4, 5, 6, 7, 8, 9, 10 are each implemented by at least one task above.
- No `TBD` / `TODO` / `implement later` placeholders.
- Types and method signatures are consistent across tasks: `VendorAdapter.run(system, user, schema, model)` matches the protocol in Task 6 and every adapter in Tasks 7–9; the runner in Task 11 calls it with those exact kwargs.
- `LabelInfo` requires `ai_reasoning`, `summary`, `confidence` — every test fixture and stub provides them.
- The stub vendor in `tests/conftest.py` and the failing-vendor stub in Task 11 both return a `VendorResponse` matching the protocol.
- Pricing table keys (`claude-sonnet-4-6`, `grok-4`, `sonar`) match the default models in `Settings`.
- Section 11 of the spec (Out of Scope) is respected — no LLM-as-judge, no caching, no CI, no web UI.

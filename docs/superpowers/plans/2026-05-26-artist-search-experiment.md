# Artist Search Experiment — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a local-only sandbox (`experiments/artists/`) that runs an `artist_v1` prompt across AI vendors, parses results into an `ArtistInfo` schema, and produces side-by-side + consensus markdown reports — mirroring `experiments/labels/`.

**Architecture:** Self-contained Python package `artlab` (CLI entry point `artlab`), sibling of the proven `lab` package. Schema-agnostic infrastructure (vendor adapters, pricing, runner, fixtures loader) is copied verbatim; schema-coupled modules (`schemas`, `prompts`, `aggregate`, `report`, `config`, `cli`) are adapted for artists. All tests mock vendor SDKs — no live API calls.

**Tech Stack:** Python ≥3.12, pydantic v2, pydantic-settings, typer, PyYAML, pytest + pytest-mock. Default vendor `openai` / `gpt-5.4-mini` via the Responses API.

**Spec:** `docs/superpowers/specs/2026-05-26-artist-search-design.md`

**Conventions:**
- Work in the worktree `experiments/artists/`. Source files to copy come from `experiments/labels/`.
- Each task ends with a commit. Generate the commit subject/body with the `caveman:caveman-commit` skill (CLAUDE.md policy); the message shown in each step is the expected output — verify it matches, then `git commit`.
- The experiment has its OWN venv at `experiments/artists/.venv` (independent of the project `.venv`). Create it with `python3.12` (falls back to any `python3` ≥3.12).
- Run pytest via the experiment venv: `cd experiments/artists && .venv/bin/pytest`.

---

## File Structure

```
experiments/artists/
  README.md                   Task 1
  pyproject.toml              Task 1
  .env.example                Task 1
  .gitignore                  Task 1  (cp verbatim)
  fixtures.yaml               Task 4
  src/artlab/
    __init__.py               Task 1  (empty, cp verbatim)
    __main__.py               Task 1
    cli.py                    Task 9  (cp + edits)
    config.py                 Task 5
    fixtures.py               Task 1  (cp verbatim)
    aggregate.py              Task 7
    report.py                 Task 8
    runner.py                 Task 6  (cp + edit)
    schemas.py                Task 2
    prompts/
      __init__.py             Task 3
      base.py                 Task 3
      artist_v1.py            Task 3
    vendors/                  Task 1  (cp verbatim, whole dir)
      __init__.py base.py pricing.py anthropic_claude.py gemini_flash.py
      openai_gpt.py perplexity_sonar.py tavily_deepseek.py xai_grok.py kimi_k2.py
  tests/
    __init__.py               Task 1
    conftest.py               Task 6
    test_schemas.py           Task 2
    test_prompts.py           Task 3
    test_fixtures_loader.py   Task 4
    test_config.py            Task 5
    test_runner.py            Task 6
    test_aggregate.py         Task 7
    test_report.py            Task 8
    test_pricing.py           Task 9  (cp + sed)
    test_vendor_*.py          Task 9  (cp + sed, 7 files)
  outputs/  reports/          gitignored, created at runtime
```

---

## Task 1: Scaffold package skeleton + verbatim infrastructure

**Files:**
- Create dir: `experiments/artists/`
- Copy verbatim: `experiments/labels/src/lab/vendors/` → `experiments/artists/src/artlab/vendors/`
- Copy verbatim: `experiments/labels/src/lab/fixtures.py`, `experiments/labels/src/lab/__init__.py`, `experiments/labels/.gitignore`
- Create: `experiments/artists/pyproject.toml`, `.env.example`, `README.md`, `src/artlab/__main__.py`, `tests/__init__.py`

- [ ] **Step 1: Create directories and copy verbatim files**

Run from the worktree root:

```bash
cd experiments
mkdir -p artists/src/artlab artists/tests
cp -R labels/src/lab/vendors artists/src/artlab/vendors
cp labels/src/lab/fixtures.py artists/src/artlab/fixtures.py
cp labels/src/lab/__init__.py artists/src/artlab/__init__.py
cp labels/.gitignore artists/.gitignore
: > artists/tests/__init__.py
cd ..
```

- [ ] **Step 2: Verify copied source has no absolute `lab` imports**

The copied files use only relative imports, so they work unchanged under `artlab`. Confirm:

Run: `grep -rn "from lab\b\|import lab\b" experiments/artists/src`
Expected: no output (exit code 1). If anything prints, that file is not schema-agnostic — stop and report.

- [ ] **Step 3: Write `pyproject.toml`**

Create `experiments/artists/pyproject.toml`:

```toml
[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[project]
name = "clouder-artist-lab"
version = "0.1.0"
description = "Local sandbox for comparing AI vendors/prompts on artist enrichment"
requires-python = ">=3.12"
dependencies = [
    "anthropic>=0.39",
    "openai>=1.40",
    "google-genai>=1.0",
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
artlab = "artlab.cli:app"

[tool.setuptools.packages.find]
where = ["src"]

[tool.pytest.ini_options]
pythonpath = ["src"]
testpaths = ["tests"]
addopts = "-q"
```

- [ ] **Step 4: Write `.env.example`**

Create `experiments/artists/.env.example`:

```
ANTHROPIC_API_KEY=
XAI_API_KEY=
GEMINI_API_KEY=
OPENAI_API_KEY=
TAVILY_API_KEY=
DEEPSEEK_API_KEY=
PERPLEXITY_API_KEY=
MOONSHOT_API_KEY=

ANTHROPIC_MODEL=claude-sonnet-4-6
XAI_MODEL=grok-4
GEMINI_MODEL=gemini-2.5-flash
OPENAI_MODEL=gpt-5.4-mini
DEEPSEEK_MODEL=deepseek-v4-flash
PERPLEXITY_MODEL=sonar
KIMI_MODEL=kimi-k2.6

CONCURRENCY=8
REQUEST_TIMEOUT=180
```

- [ ] **Step 5: Write `src/artlab/__main__.py`**

Create `experiments/artists/src/artlab/__main__.py`:

```python
"""Allow `python -m artlab` invocation."""

from .cli import app

if __name__ == "__main__":
    app()
```

- [ ] **Step 6: Write `README.md`**

Create `experiments/artists/README.md`:

```markdown
# Artist AI Sandbox

Local-only experiment harness for comparing AI vendors and prompts on the
"music artist info enrichment" task. Production code under `src/collector/`
is not touched by this directory.

Design spec: `docs/superpowers/specs/2026-05-26-artist-search-design.md`

## Setup

```bash
cd experiments/artists
python3.12 -m venv .venv
.venv/bin/pip install -e ".[dev]"
cp .env.example .env
# edit .env and add your API keys (any subset is fine; missing vendors are skipped)
```

## Run

```bash
# default: openai / gpt-5.4-mini across all fixtures
.venv/bin/artlab run --prompts artist_v1

# subset
.venv/bin/artlab run --prompts artist_v1 --vendors openai --fixtures anna

# multi-vendor compare, then consensus merge (needs DEEPSEEK_API_KEY)
.venv/bin/artlab run --prompts artist_v1 --vendors openai,perplexity
.venv/bin/artlab aggregate <run_id>

# inspect / report
.venv/bin/artlab list prompts
.venv/bin/artlab list vendors
.venv/bin/artlab list fixtures
.venv/bin/artlab report <run_id>
open reports/<run_id>.md
```

Outputs:
- `outputs/<run_id>/<prompt>__<vendor>__<fixture>.json` — one raw cell each
- `outputs/<run_id>/manifest.json` — what was run
- `outputs/<run_id>/merged/<prompt>__<fixture>.json` — consensus (after aggregate)
- `reports/<run_id>.md` — side-by-side + consensus markdown report

`outputs/` and `reports/` are gitignored.

## Tests

```bash
.venv/bin/pytest
```

All tests use mocked SDK clients. No live API call.
```

- [ ] **Step 7: Create the venv and install**

Run:

```bash
cd experiments/artists
python3.12 -m venv .venv
.venv/bin/pip install -e ".[dev]"
cd ../..
```

Expected: install succeeds (it builds metadata only; module imports are not triggered, so the not-yet-written `schemas.py` is fine).

- [ ] **Step 8: Commit**

```bash
git add experiments/artists
git commit -m "$(cat <<'EOF'
chore(artist-lab): scaffold artist sandbox skeleton

Sibling of experiments/labels. Vendor adapters, pricing and the
fixtures loader are schema-agnostic and copied verbatim.
EOF
)"
```

---

## Task 2: `ArtistInfo` data model

**Files:**
- Create: `experiments/artists/src/artlab/schemas.py`
- Test: `experiments/artists/tests/test_schemas.py`

- [ ] **Step 1: Write the failing test**

Create `experiments/artists/tests/test_schemas.py`:

```python
import pytest
from pydantic import ValidationError

from artlab.schemas import (
    AIContentStatus,
    AISignal,
    AISignalKind,
    ArtistInfo,
    ArtistType,
)


def test_artist_info_minimal_valid():
    info = ArtistInfo(
        artist_name="ANNA",
        ai_reasoning="No AI signals found in available sources.",
        summary="Brazilian techno DJ and producer.",
        confidence=0.9,
    )
    assert info.artist_name == "ANNA"
    assert info.artist_type == ArtistType.UNKNOWN
    assert info.ai_content == AIContentStatus.UNKNOWN
    assert info.aliases == []
    assert info.labels == []


def test_artist_info_full():
    info = ArtistInfo(
        artist_name="Aiva Nova",
        country="US",
        active_since=2024,
        artist_type=ArtistType.SOLO,
        ai_content=AIContentStatus.CONFIRMED,
        ai_signals=[
            AISignal(
                kind=AISignalKind.NO_LIVE_PRESENCE,
                description="No gigs, tours, or RA dates found.",
                source_url="https://example.com/checked",
            ),
        ],
        ai_reasoning="No live presence plus AI-looking imagery.",
        summary="Likely synthetic AI persona.",
        confidence=0.8,
    )
    assert info.artist_type == ArtistType.SOLO
    assert info.ai_signals[0].kind == AISignalKind.NO_LIVE_PRESENCE


def test_confidence_bounds():
    with pytest.raises(ValidationError):
        ArtistInfo(artist_name="x", ai_reasoning="x", summary="x", confidence=1.5)
    with pytest.raises(ValidationError):
        ArtistInfo(artist_name="x", ai_reasoning="x", summary="x", confidence=-0.1)


def test_artist_info_app_fields_optional():
    info = ArtistInfo(artist_name="ANNA", ai_reasoning="-", summary="-", confidence=0.5)
    assert info.spotify_url is None
    assert info.bio is None
    assert info.tagline is None


def test_artist_info_accepts_links_and_bio():
    info = ArtistInfo(
        artist_name="ANNA",
        spotify_url="https://open.spotify.com/artist/abc",
        bio="Brazilian techno producer and DJ.",
        ai_reasoning="-",
        summary="-",
        confidence=0.6,
    )
    assert info.spotify_url == "https://open.spotify.com/artist/abc"
    assert info.bio == "Brazilian techno producer and DJ."
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd experiments/artists && .venv/bin/pytest tests/test_schemas.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'artlab.schemas'`.

- [ ] **Step 3: Write `schemas.py`**

Create `experiments/artists/src/artlab/schemas.py`:

```python
"""Data models for the artist sandbox."""

from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field


class ArtistType(str, Enum):
    SOLO = "solo"
    DUO = "duo"
    GROUP = "group"
    ALIAS_PROJECT = "alias_project"
    UNKNOWN = "unknown"


class AIContentStatus(str, Enum):
    UNKNOWN = "unknown"
    NONE_DETECTED = "none_detected"
    SUSPECTED = "suspected"
    CONFIRMED = "confirmed"


class AISignalKind(str, Enum):
    NO_LIVE_PRESENCE = "no_live_presence"
    AI_GENERATED_IMAGERY = "ai_generated_imagery"
    SUSPICIOUS_RELEASE_VELOCITY = "suspicious_release_velocity"
    NO_SOCIAL_FOOTPRINT = "no_social_footprint"
    TEMPLATED_BIO = "templated_bio"
    DISTRIBUTOR_ONLY_NO_LABEL = "distributor_only_no_label"
    VOICE_CLONING_INDICATORS = "voice_cloning_indicators"
    AI_FARM_NAME_PATTERN = "ai_farm_name_pattern"
    REVERSE_IMAGE_NO_RESULTS = "reverse_image_no_results"
    NAMED_IN_PRESS = "named_in_press"
    CREDITED_TOOL = "credited_tool"
    OTHER = "other"


class AISignal(BaseModel):
    kind: AISignalKind
    description: str
    source_url: str | None = None


class ArtistInfo(BaseModel):
    # Identity
    artist_name: str
    aliases: list[str] = Field(default_factory=list)
    real_name: str | None = None
    artist_type: ArtistType = ArtistType.UNKNOWN
    members: list[str] = Field(default_factory=list)

    # Origin
    country: str | None = None
    city: str | None = None
    active_since: int | None = None
    status: Literal["active", "inactive", "unknown"] = "unknown"

    # Music
    primary_styles: list[str] = Field(default_factory=list)
    labels: list[str] = Field(default_factory=list)
    notable_collaborators: list[str] = Field(default_factory=list)
    notable_releases: list[str] = Field(default_factory=list)

    # Links
    spotify_url: str | None = None
    soundcloud_url: str | None = None
    bandcamp_url: str | None = None
    beatport_url: str | None = None
    residentadvisor_url: str | None = None
    discogs_url: str | None = None
    instagram_url: str | None = None
    twitter_url: str | None = None
    website: str | None = None

    # Narrative
    tagline: str | None = None
    bio: str | None = None
    summary: str

    # AI detection
    ai_content: AIContentStatus = AIContentStatus.UNKNOWN
    ai_signals: list[AISignal] = Field(default_factory=list)
    ai_reasoning: str

    # Meta
    confidence: float = Field(ge=0, le=1)
    sources: list[str] = Field(default_factory=list)
    notes: str | None = None


class GroundTruth(BaseModel):
    country: str | None = None
    active_since: int | None = None
    ai_content_expected: AIContentStatus | None = None


class Fixture(BaseModel):
    id: str
    artist_name: str
    style: str
    sample_tracks: list[str] = Field(default_factory=list)
    known_labels: list[str] = Field(default_factory=list)
    ground_truth: GroundTruth | None = None


class FixturesFile(BaseModel):
    fixtures: list[Fixture]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd experiments/artists && .venv/bin/pytest tests/test_schemas.py -q`
Expected: PASS (5 passed).

- [ ] **Step 5: Commit**

```bash
git add experiments/artists/src/artlab/schemas.py experiments/artists/tests/test_schemas.py
git commit -m "feat(artist-lab): add ArtistInfo schema"
```

---

## Task 3: Prompts (`base`, registry, `artist_v1`)

**Files:**
- Create: `experiments/artists/src/artlab/prompts/base.py`
- Create: `experiments/artists/src/artlab/prompts/__init__.py`
- Create: `experiments/artists/src/artlab/prompts/artist_v1.py`
- Test: `experiments/artists/tests/test_prompts.py`

- [ ] **Step 1: Write the failing test**

Create `experiments/artists/tests/test_prompts.py`:

```python
import pytest

from artlab.prompts.base import PromptConfig, render_user
from artlab.schemas import ArtistInfo


def _make_prompt(slug: str = "demo", version: str = "v1") -> PromptConfig:
    return PromptConfig(
        slug=slug,
        version=version,
        description="demo prompt",
        system="you research artists",
        user_template='Research "{artist_name}".{context_block}',
        schema=ArtistInfo,
    )


def test_render_user_without_context():
    cfg = _make_prompt()
    out = render_user(cfg, artist_name="ANNA", style="techno")
    assert out == 'Research "ANNA".'


def test_render_user_with_context():
    cfg = _make_prompt()
    out = render_user(
        cfg,
        artist_name="ANNA",
        style="techno",
        sample_tracks=["Hidden Beauties"],
        known_labels=["Drumcode"],
    )
    assert 'Research "ANNA".' in out
    assert "Hidden Beauties" in out
    assert "Drumcode" in out
    assert "genre hint: techno" in out


def test_registry_register_and_get():
    from artlab.prompts import PROMPTS, get_prompt, register

    PROMPTS.clear()
    cfg = _make_prompt(slug="demo_a")
    register(cfg)
    assert get_prompt("demo_a") is cfg


def test_registry_rejects_duplicate():
    from artlab.prompts import PROMPTS, register

    PROMPTS.clear()
    register(_make_prompt(slug="demo_b"))
    with pytest.raises(ValueError, match="already registered"):
        register(_make_prompt(slug="demo_b"))


def test_builtin_prompts_register():
    from artlab.prompts import PROMPTS, load_builtin_prompts

    load_builtin_prompts()
    assert "artist_v1" in PROMPTS


def test_artist_v1_contains_directives():
    from artlab.prompts import PROMPTS, load_builtin_prompts

    load_builtin_prompts()
    cfg = PROMPTS["artist_v1"]
    assert cfg.version == "v1"
    assert "disambiguation" in cfg.system.lower()
    assert "ai_reasoning" in cfg.system
    assert "spotify" in cfg.user_template.lower()
    assert "{context_block}" in cfg.user_template
    assert cfg.schema is ArtistInfo
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd experiments/artists && .venv/bin/pytest tests/test_prompts.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'artlab.prompts'`.

- [ ] **Step 3: Write `prompts/base.py`**

Create `experiments/artists/src/artlab/prompts/base.py`:

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
    artist_name: str,
    style: str,
    sample_tracks: list[str] | None = None,
    known_labels: list[str] | None = None,
) -> str:
    tracks = ", ".join(sample_tracks) if sample_tracks else ""
    labels = ", ".join(known_labels) if known_labels else ""
    if tracks or labels:
        context_block = (
            "\nDisambiguation context — this is the artist who released: "
            f"{tracks or 'unknown'}; on labels: {labels or 'unknown'}; "
            f"genre hint: {style}."
        )
    else:
        context_block = ""
    return cfg.user_template.format(
        artist_name=artist_name,
        style=style,
        context_block=context_block,
    )
```

- [ ] **Step 4: Write `prompts/__init__.py`**

Create `experiments/artists/src/artlab/prompts/__init__.py`:

```python
"""Prompt registry."""

from __future__ import annotations

from .base import PromptConfig

PROMPTS: dict[str, PromptConfig] = {}

# Populated by load_builtin_prompts() on first call; used to re-register
# builtins if PROMPTS is cleared between test runs.
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
        from . import artist_v1  # noqa: F401
        _BUILTIN_CONFIGS = [cfg for slug, cfg in PROMPTS.items() if slug not in before]

    for cfg in _BUILTIN_CONFIGS:
        register(cfg)
```

- [ ] **Step 5: Write `prompts/artist_v1.py`**

Create `experiments/artists/src/artlab/prompts/artist_v1.py`:

```python
"""artist_v1 — facts-discipline + disambiguation + AI detection."""

from __future__ import annotations

from . import register
from .base import PromptConfig
from ..schemas import ArtistInfo

SYSTEM = (
    "You research electronic-music artists. Output structured facts only.\n"
    "Rules:\n"
    "- Use the disambiguation context (sample releases + labels + style) to "
    "lock onto the CORRECT artist. Many artists share a name. If the context "
    "does not resolve which artist this is, set confidence <= 0.4 and explain "
    "the ambiguity in `notes`.\n"
    "- Every URL must clearly belong to THIS artist: the profile name must "
    "match and it should reference at least one of the known releases or "
    "labels. If a link cannot be tied to this artist, omit it.\n"
    "- active_since and any year require a supporting URL in `sources`. Never "
    "guess years.\n"
    "- aliases / real_name: list everything you find; mark uncertain ones in "
    "`notes`.\n"
    "- artist_type: solo unless there is evidence of a duo / group / alias "
    "project.\n"
    "- labels: labels the artist has actually released on, most relevant "
    "first.\n"
    "- notable_collaborators: frequent co-authors and remixers, not one-offs.\n"
    "- notable_releases: at most 5 anchor tracks/EPs that confirm identity.\n"
    "- primary_styles: 2-5 specific genre tags, no umbrella terms.\n"
    "- AI detection: assess whether this may be an AI-generated artist "
    "(synthetic persona, no live presence, AI imagery, impossible output "
    "velocity, voice cloning, credited AI tools). Record evidence in "
    "`ai_signals`. ai_content=confirmed only with strong evidence (the artist "
    "or press explicitly states AI generation). ai_reasoning is always "
    "required, even when none_detected — explain why.\n"
    "- summary is always required.\n"
    "- confidence: 1.0 only if identity is confirmed via the context match "
    "AND country is sourced AND there are >=3 supporting sources."
)

USER_TEMPLATE = (
    'Research the electronic-music artist "{artist_name}".{context_block}\n'
    "Find: aliases and real name, country and city, years active, labels they "
    "release on, frequent collaborators and remixers, notable releases, "
    "streaming and social profiles (Spotify, SoundCloud, Bandcamp, Beatport, "
    "Resident Advisor, Discogs, Instagram), primary styles, and a short bio.\n"
    "Then assess AI-content status and explain your reasoning."
)


register(
    PromptConfig(
        slug="artist_v1",
        version="v1",
        description="Facts-discipline + disambiguation + AI detection for artists.",
        system=SYSTEM,
        user_template=USER_TEMPLATE,
        schema=ArtistInfo,
    )
)
```

- [ ] **Step 6: Run test to verify it passes**

Run: `cd experiments/artists && .venv/bin/pytest tests/test_prompts.py -q`
Expected: PASS (6 passed).

- [ ] **Step 7: Commit**

```bash
git add experiments/artists/src/artlab/prompts experiments/artists/tests/test_prompts.py
git commit -m "feat(artist-lab): add artist_v1 prompt and registry"
```

---

## Task 4: Fixtures (`fixtures.yaml` + loader test)

**Files:**
- Create: `experiments/artists/fixtures.yaml`
- Test: `experiments/artists/tests/test_fixtures_loader.py`

(The loader `src/artlab/fixtures.py` was copied verbatim in Task 1; it uses the `Fixture`/`FixturesFile` models from Task 2.)

- [ ] **Step 1: Write the failing test**

Create `experiments/artists/tests/test_fixtures_loader.py`:

```python
from pathlib import Path

import pytest

from artlab.fixtures import load_fixtures


def test_load_real_fixtures():
    root = Path(__file__).resolve().parents[1]  # experiments/artists/
    fixtures = load_fixtures(root / "fixtures.yaml")
    assert len(fixtures) >= 1
    ids = [f.id for f in fixtures]
    assert len(ids) == len(set(ids))  # unique
    f0 = fixtures[0]
    assert f0.artist_name
    assert f0.style


def test_duplicate_id_raises(tmp_path):
    p = tmp_path / "f.yaml"
    p.write_text(
        "fixtures:\n"
        "  - id: dup\n    artist_name: A\n    style: techno\n"
        "  - id: dup\n    artist_name: B\n    style: house\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="duplicate fixture id"):
        load_fixtures(p)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd experiments/artists && .venv/bin/pytest tests/test_fixtures_loader.py -q`
Expected: FAIL — `test_load_real_fixtures` errors because `fixtures.yaml` does not exist yet.

- [ ] **Step 3: Write `fixtures.yaml`**

Create `experiments/artists/fixtures.yaml`:

```yaml
fixtures:
  - id: anna
    artist_name: ANNA
    style: techno
    sample_tracks:
      - "Hidden Beauties"
      - "Forsaken"
    known_labels:
      - Drumcode
      - Kompakt
    ground_truth:
      country: Brazil
      active_since: 2008
      ai_content_expected: none_detected

  - id: aphex-twin
    artist_name: Aphex Twin
    style: idm
    sample_tracks:
      - "Windowlicker"
      - "Avril 14th"
    known_labels:
      - Warp Records
    ground_truth:
      country: GB
      ai_content_expected: none_detected

  - id: name-collision-vision
    artist_name: Vision
    style: drum and bass
    sample_tracks: []
    known_labels:
      - Hospital Records
    ground_truth: null

  - id: obscure-niche
    artist_name: Pessimist
    style: drum and bass / techno
    sample_tracks:
      - "Through Stims"
    known_labels:
      - Pessimist Productions
      - Ilian Tape
    ground_truth: null

  - id: synthetic-ai-artist
    artist_name: Aiva Nova
    style: lofi
    sample_tracks: []
    known_labels: []
    ground_truth:
      ai_content_expected: suspected
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd experiments/artists && .venv/bin/pytest tests/test_fixtures_loader.py -q`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add experiments/artists/fixtures.yaml experiments/artists/tests/test_fixtures_loader.py
git commit -m "feat(artist-lab): add artist fixtures"
```

---

## Task 5: Config

**Files:**
- Create: `experiments/artists/src/artlab/config.py`
- Test: `experiments/artists/tests/test_config.py`

- [ ] **Step 1: Write the failing test**

Create `experiments/artists/tests/test_config.py`:

```python
import pytest

from artlab.config import Settings, available_vendor_names

_KEY_ENVS = [
    "ANTHROPIC_API_KEY", "XAI_API_KEY", "GEMINI_API_KEY", "OPENAI_API_KEY",
    "TAVILY_API_KEY", "DEEPSEEK_API_KEY", "PERPLEXITY_API_KEY",
    "MOONSHOT_API_KEY", "KIMI_API_KEY",
]
_MODEL_ENVS = [
    "ANTHROPIC_MODEL", "XAI_MODEL", "GEMINI_MODEL", "OPENAI_MODEL",
    "DEEPSEEK_MODEL", "PERPLEXITY_MODEL", "KIMI_MODEL",
    "CONCURRENCY", "REQUEST_TIMEOUT",
]


@pytest.fixture
def clean_env(monkeypatch):
    for k in _KEY_ENVS + _MODEL_ENVS:
        monkeypatch.delenv(k, raising=False)
    return monkeypatch


def test_default_openai_model_is_gpt54_mini(clean_env):
    s = Settings(_env_file=None)
    assert s.openai_model == "gpt-5.4-mini"
    assert s.concurrency == 8
    assert s.request_timeout == 180


def test_available_vendor_names_empty(clean_env):
    s = Settings(_env_file=None)
    assert available_vendor_names(s) == []


def test_available_vendor_names_with_keys(clean_env):
    s = Settings(_env_file=None, openai_api_key="x", gemini_api_key="y")
    names = available_vendor_names(s)
    assert "openai" in names
    assert "gemini" in names


def test_tavily_deepseek_requires_both_keys(clean_env):
    s1 = Settings(_env_file=None, tavily_api_key="t")
    assert "tavily_deepseek" not in available_vendor_names(s1)
    s2 = Settings(_env_file=None, tavily_api_key="t", deepseek_api_key="d")
    assert "tavily_deepseek" in available_vendor_names(s2)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd experiments/artists && .venv/bin/pytest tests/test_config.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'artlab.config'`.

- [ ] **Step 3: Write `config.py`**

Create `experiments/artists/src/artlab/config.py`:

```python
"""Environment-driven configuration."""

from __future__ import annotations

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    anthropic_api_key: str | None = None
    xai_api_key: str | None = None
    gemini_api_key: str | None = None
    openai_api_key: str | None = None
    tavily_api_key: str | None = None
    deepseek_api_key: str | None = None
    perplexity_api_key: str | None = None
    # Accepts MOONSHOT_API_KEY (canonical Moonshot env var) or KIMI_API_KEY.
    kimi_api_key: str | None = Field(
        default=None,
        validation_alias=AliasChoices("MOONSHOT_API_KEY", "kimi_api_key", "KIMI_API_KEY"),
    )

    anthropic_model: str = "claude-sonnet-4-6"
    xai_model: str = "grok-4"
    gemini_model: str = "gemini-2.5-flash"
    openai_model: str = "gpt-5.4-mini"
    deepseek_model: str = "deepseek-v4-flash"
    perplexity_model: str = "sonar"
    kimi_model: str = "kimi-k2.6"

    concurrency: int = 8
    request_timeout: int = 180

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
    if s.gemini_api_key:
        out.append("gemini")
    if s.openai_api_key:
        out.append("openai")
    if s.tavily_api_key and s.deepseek_api_key:
        out.append("tavily_deepseek")
    if s.perplexity_api_key:
        out.append("perplexity")
    if s.kimi_api_key:
        out.append("kimi")
    return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd experiments/artists && .venv/bin/pytest tests/test_config.py -q`
Expected: PASS (4 passed).

- [ ] **Step 5: Commit**

```bash
git add experiments/artists/src/artlab/config.py experiments/artists/tests/test_config.py
git commit -m "feat(artist-lab): add config with gpt-5.4-mini default"
```

---

## Task 6: Matrix runner + test conftest

**Files:**
- Create: `experiments/artists/tests/conftest.py`
- Create (cp + edit): `experiments/artists/src/artlab/runner.py`
- Test: `experiments/artists/tests/test_runner.py`

- [ ] **Step 1: Write the test conftest**

Create `experiments/artists/tests/conftest.py`:

```python
"""Shared test helpers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Type

from pydantic import BaseModel

from artlab.schemas import Fixture
from artlab.vendors.base import VendorResponse


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
                "artist_name": "Stubbed",
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


def make_fixture(
    id: str,
    artist: str,
    style: str = "techno",
    sample_tracks: list[str] | None = None,
    known_labels: list[str] | None = None,
) -> Fixture:
    return Fixture(
        id=id,
        artist_name=artist,
        style=style,
        sample_tracks=sample_tracks or [],
        known_labels=known_labels or [],
    )
```

- [ ] **Step 2: Write the failing test**

Create `experiments/artists/tests/test_runner.py`:

```python
import json

import pytest

from artlab.prompts import PROMPTS, load_builtin_prompts
from artlab.runner import RunSpec, run_matrix
from tests.conftest import StubVendor, make_fixture


@pytest.fixture(autouse=True)
def _prompts_loaded():
    load_builtin_prompts()


def test_run_matrix_writes_cells_and_manifest(tmp_path):
    vendors = [StubVendor("anthropic"), StubVendor("openai")]
    fixtures = [make_fixture("anna", "ANNA"), make_fixture("aphex", "Aphex Twin", "idm")]
    prompts = ["artist_v1"]

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
    assert sample["response"]["parsed"]["artist_name"] == "Stubbed"

    manifest = json.loads((run_dir / "manifest.json").read_text())
    assert {v["name"] for v in manifest["vendors"]} == {"anthropic", "openai"}
    assert sorted(manifest["fixtures"]) == ["anna", "aphex"]


def test_run_matrix_renders_disambiguation_context(tmp_path):
    vendors = [StubVendor("openai")]
    fixtures = [
        make_fixture(
            "anna", "ANNA", "techno",
            sample_tracks=["Hidden Beauties"],
            known_labels=["Drumcode"],
        )
    ]
    spec = RunSpec(
        prompts=["artist_v1"],
        vendors=vendors,
        fixtures=fixtures,
        outputs_root=tmp_path,
        concurrency=1,
    )
    result = run_matrix(spec)
    cell = next((tmp_path / result.run_id).glob("*.json"))
    payload = json.loads(cell.read_text())
    assert "Hidden Beauties" in payload["rendered_user_prompt"]
    assert "Drumcode" in payload["rendered_user_prompt"]


def test_run_matrix_records_vendor_error(tmp_path):
    class FailingVendor(StubVendor):
        def run(self, system, user, schema, model=None):
            from artlab.vendors.base import VendorResponse
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
        prompts=["artist_v1"],
        vendors=[FailingVendor("openai")],
        fixtures=[make_fixture("anna", "ANNA")],
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

- [ ] **Step 3: Run test to verify it fails**

Run: `cd experiments/artists && .venv/bin/pytest tests/test_runner.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'artlab.runner'`.

- [ ] **Step 4: Copy `runner.py` verbatim from the label sandbox**

Run from the worktree root:

```bash
cp experiments/labels/src/lab/runner.py experiments/artists/src/artlab/runner.py
```

- [ ] **Step 5: Adapt the `render_user` call in `_execute_cell`**

In `experiments/artists/src/artlab/runner.py`, replace this block:

```python
    user = render_user(
        prompt,
        label_name=cell.fixture.label_name,
        style=cell.fixture.style,
        release_name=cell.fixture.release_name,
    )
```

with:

```python
    user = render_user(
        prompt,
        artist_name=cell.fixture.artist_name,
        style=cell.fixture.style,
        sample_tracks=cell.fixture.sample_tracks,
        known_labels=cell.fixture.known_labels,
    )
```

(No other change is needed — `runner.py` imports `Fixture` from `.schemas` and `render_user` from `.prompts.base`, both already artist-shaped, and the rest is schema-agnostic.)

- [ ] **Step 6: Run test to verify it passes**

Run: `cd experiments/artists && .venv/bin/pytest tests/test_runner.py -q`
Expected: PASS (3 passed).

- [ ] **Step 7: Commit**

```bash
git add experiments/artists/src/artlab/runner.py experiments/artists/tests/conftest.py experiments/artists/tests/test_runner.py
git commit -m "feat(artist-lab): add matrix runner and test stubs"
```

---

## Task 7: Consensus aggregator

**Files:**
- Create: `experiments/artists/src/artlab/aggregate.py`
- Test: `experiments/artists/tests/test_aggregate.py`

- [ ] **Step 1: Write the failing test**

Create `experiments/artists/tests/test_aggregate.py`:

```python
"""Tests for artlab.aggregate."""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from artlab.aggregate import _filter_parseable, _merge_deterministic, merge_cells
from artlab.schemas import ArtistInfo


def _cell(vendor: str, model: str, parsed: dict | None = None, error: str | None = None) -> dict:
    return {
        "run_id": "test-run",
        "prompt": {"slug": "artist_v1", "version": "v1"},
        "vendor": {"name": vendor, "model": model},
        "fixture": {"id": "anna", "artist_name": "ANNA", "style": "techno",
                    "sample_tracks": [], "known_labels": []},
        "rendered_user_prompt": "...",
        "response": {
            "parsed": parsed,
            "citations": [],
            "usage": {"input_tokens": 100, "output_tokens": 200, "cost_usd": 0.001},
            "latency_ms": 1234,
            "raw": {},
        },
        "error": error,
    }


def _parsed(**overrides) -> dict:
    base = {
        "artist_name": "ANNA",
        "aliases": [],
        "real_name": None,
        "artist_type": "solo",
        "members": [],
        "country": "Brazil",
        "city": None,
        "active_since": 2010,
        "status": "active",
        "primary_styles": [],
        "labels": [],
        "notable_collaborators": [],
        "notable_releases": [],
        "spotify_url": None,
        "soundcloud_url": None,
        "bandcamp_url": None,
        "beatport_url": None,
        "residentadvisor_url": None,
        "discogs_url": None,
        "instagram_url": None,
        "twitter_url": None,
        "website": None,
        "tagline": None,
        "bio": None,
        "summary": "Brazilian techno DJ.",
        "ai_content": "none_detected",
        "ai_signals": [],
        "ai_reasoning": "n/a",
        "confidence": 0.9,
        "sources": [],
        "notes": None,
    }
    base.update(overrides)
    return base


def test_filter_parseable_drops_errored_and_none():
    cells = [
        _cell("a", "ma", parsed=_parsed()),
        _cell("b", "mb", parsed=None, error="boom"),
        _cell("c", "mc", parsed=None),
        _cell("d", "md", parsed=_parsed(country="Germany")),
    ]
    filtered = _filter_parseable(cells)
    assert len(filtered) == 2
    assert filtered[0]["vendor"]["name"] == "a"
    assert filtered[1]["vendor"]["name"] == "d"


def test_merge_deterministic_numeric_median():
    cells = [
        _cell("a", "ma", parsed=_parsed(active_since=2008)),
        _cell("b", "mb", parsed=_parsed(active_since=2010)),
        _cell("c", "mc", parsed=_parsed(active_since=2012)),
    ]
    merged, prov = _merge_deterministic(cells)
    assert merged["active_since"] == 2010
    assert prov["active_since"] == "median:2010"


def test_merge_deterministic_enum_majority():
    cells = [
        _cell("a", "ma", parsed=_parsed(status="active", confidence=0.9)),
        _cell("b", "mb", parsed=_parsed(status="active", confidence=0.7)),
        _cell("c", "mc", parsed=_parsed(status="inactive", confidence=1.0)),
    ]
    merged, prov = _merge_deterministic(cells)
    assert merged["status"] == "active"
    assert prov["status"].startswith("majority")


def test_merge_deterministic_enum_tie_breaks_on_confidence():
    cells = [
        _cell("a", "ma", parsed=_parsed(status="active", confidence=0.8)),
        _cell("b", "mb", parsed=_parsed(status="inactive", confidence=0.95)),
    ]
    merged, prov = _merge_deterministic(cells)
    assert merged["status"] == "inactive"
    assert "tie" in prov["status"]


def test_merge_deterministic_country_short_wins_tie():
    cells = [
        _cell("a", "ma", parsed=_parsed(country="United Kingdom")),
        _cell("b", "mb", parsed=_parsed(country="GB")),
    ]
    merged, prov = _merge_deterministic(cells)
    assert merged["country"] == "GB"
    assert "shortest" in prov["country"]


def test_merge_deterministic_releases_union_top5():
    cells = [
        _cell("a", "ma", parsed=_parsed(notable_releases=["Hidden Beauties", "Forsaken", "Remixes"], confidence=1.0)),
        _cell("b", "mb", parsed=_parsed(notable_releases=["Hidden Beauties", "Spline", "Mira", "Forsaken"], confidence=0.8)),
        _cell("c", "mc", parsed=_parsed(notable_releases=["Hidden Beauties", "Odd Concept"], confidence=0.6)),
    ]
    merged, prov = _merge_deterministic(cells)
    releases = merged["notable_releases"]
    assert releases[0] == "Hidden Beauties"  # most frequent first
    assert len(releases) <= 5
    assert "union top-5 round-robin" in prov["notable_releases"]


def test_merge_deterministic_url_max_confidence_wins():
    cells = [
        _cell("a", "ma", parsed=_parsed(spotify_url=None, confidence=0.95)),
        _cell("b", "mb", parsed=_parsed(spotify_url="https://open.spotify.com/artist/x", confidence=0.7)),
        _cell("c", "mc", parsed=_parsed(spotify_url="https://open.spotify.com/artist/y", confidence=0.8)),
    ]
    merged, prov = _merge_deterministic(cells)
    assert merged["spotify_url"] == "https://open.spotify.com/artist/y"  # cell c (higher conf among non-null)
    assert "highest confidence" in prov["spotify_url"]


def test_merge_deterministic_confidence_mean():
    cells = [
        _cell("a", "ma", parsed=_parsed(confidence=0.8)),
        _cell("b", "mb", parsed=_parsed(confidence=1.0)),
        _cell("c", "mc", parsed=_parsed(confidence=0.6)),
    ]
    merged, prov = _merge_deterministic(cells)
    assert merged["confidence"] == pytest.approx(0.8)
    assert prov["confidence"].startswith("mean")


def test_merge_deterministic_unknown_abstains_from_enum_vote():
    cells = [
        _cell("a", "ma", parsed=_parsed(ai_content="none_detected", confidence=1.0)),
        _cell("b", "mb", parsed=_parsed(ai_content="unknown", confidence=0.6)),
        _cell("c", "mc", parsed=_parsed(ai_content="unknown", confidence=0.8)),
    ]
    merged, prov = _merge_deterministic(cells)
    assert merged["ai_content"] == "none_detected"
    assert "definitive" in prov["ai_content"]


def _mock_deepseek_response(content: str, prompt_tokens: int = 800, completion_tokens: int = 300):
    msg = SimpleNamespace(content=content)
    choice = SimpleNamespace(message=msg, finish_reason="stop")
    usage = SimpleNamespace(
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=prompt_tokens + completion_tokens,
    )
    return SimpleNamespace(choices=[choice], usage=usage, model="deepseek-v4-flash")


def test_merge_cells_narrative_through_deepseek():
    payload = {
        "tagline": "Brazilian techno force.",
        "bio": "ANNA is a Brazilian DJ and producer.",
        "summary": "ANNA, born Ana Miranda, is a Brazilian techno artist.",
        "ai_reasoning": "No AI signals across vendors.",
        "notes": None,
    }
    fake = MagicMock()
    fake.chat.completions.create.return_value = _mock_deepseek_response(json.dumps(payload))

    cells = [
        _cell("a", "ma", parsed=_parsed(tagline="t1", bio="b1", summary="s1", confidence=0.9)),
        _cell("b", "mb", parsed=_parsed(tagline="t2", bio="b2", summary="s2", confidence=0.95)),
    ]
    merged, meta = merge_cells(cells, fake, deepseek_model="deepseek-v4-flash")
    assert isinstance(merged, ArtistInfo)
    assert merged.tagline == "Brazilian techno force."
    assert merged.bio == "ANNA is a Brazilian DJ and producer."
    assert merged.country == "Brazil"
    assert merged.active_since == 2010
    assert meta["narrative_cost_usd"] > 0
    assert meta["field_provenance"]["tagline"] == "deepseek narrative"
    fake.chat.completions.create.assert_called_once()


def test_merge_cells_narrative_fallback_on_error():
    fake = MagicMock()
    fake.chat.completions.create.side_effect = RuntimeError("boom")
    cells = [
        _cell("a", "ma", parsed=_parsed(tagline="low", summary="low s", confidence=0.4)),
        _cell("b", "mb", parsed=_parsed(tagline="high", summary="high s", confidence=0.95)),
    ]
    merged, meta = merge_cells(cells, fake)
    assert merged.tagline == "high"
    assert merged.summary == "high s"
    assert meta["narrative_fallback"] == "max_confidence"


def test_merge_cells_single_source_skips_deepseek():
    fake = MagicMock()
    cells = [_cell("a", "ma", parsed=_parsed(summary="single s", tagline="single"))]
    merged, meta = merge_cells(cells, fake)
    assert merged.summary == "single s"
    assert merged.tagline == "single"
    assert meta["single_source"] is True
    assert meta["narrative_cost_usd"] == 0.0
    fake.chat.completions.create.assert_not_called()


def test_merge_cells_all_failed_returns_placeholder():
    fake = MagicMock()
    cells = [_cell("a", "ma", parsed=None, error="boom"), _cell("b", "mb", parsed=None)]
    merged, meta = merge_cells(cells, fake)
    assert merged.summary == "All vendor sources failed."
    assert merged.confidence == 0.0
    assert meta["all_failed"] is True
    fake.chat.completions.create.assert_not_called()


def test_merge_cells_handles_malformed_deepseek_json():
    fake = MagicMock()
    fake.chat.completions.create.return_value = _mock_deepseek_response("not json")
    cells = [
        _cell("a", "ma", parsed=_parsed(tagline="A", summary="A", confidence=0.8)),
        _cell("b", "mb", parsed=_parsed(tagline="B", summary="B", confidence=0.95)),
    ]
    merged, meta = merge_cells(cells, fake)
    assert meta["narrative_fallback"] == "max_confidence"
    assert merged.tagline == "B"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd experiments/artists && .venv/bin/pytest tests/test_aggregate.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'artlab.aggregate'`.

- [ ] **Step 3: Write `aggregate.py`**

Create `experiments/artists/src/artlab/aggregate.py`:

```python
"""Multi-vendor consensus aggregator for ArtistInfo cells.

The single public entry point is `merge_cells`. Private helpers
(`_filter_parseable`, `_merge_deterministic`, `_merge_narrative`) are exposed
for tests.
"""

from __future__ import annotations

import json
import time
from collections import Counter
from statistics import median
from typing import Any

from .schemas import ArtistInfo
from .vendors.pricing import estimate_cost

NARRATIVE_FIELDS = ("tagline", "bio", "summary", "ai_reasoning", "notes")
URL_FIELDS = (
    "spotify_url",
    "soundcloud_url",
    "bandcamp_url",
    "beatport_url",
    "residentadvisor_url",
    "discogs_url",
    "instagram_url",
    "twitter_url",
    "website",
)
NUMERIC_FIELDS = ("active_since",)
ENUM_FIELDS = ("artist_type", "ai_content", "status")
LIST_FIELDS = (
    "aliases",
    "members",
    "primary_styles",
    "labels",
    "notable_collaborators",
    "notable_releases",
    "sources",
)
CAPPED_LIST_FIELDS = ("notable_collaborators", "notable_releases")
STRING_FIELDS = ("real_name", "city")


def _rank_list_round_robin(per_cell_items: list[list[str]], cap: int) -> tuple[list[str], int, int]:
    """Rank list items: shared first (freq desc), then round-robin from each cell."""
    counts: Counter[str] = Counter()
    seen_original: dict[str, str] = {}
    for items in per_cell_items:
        for item in items:
            if not isinstance(item, str) or not item.strip():
                continue
            k = item.strip().lower()
            if k not in seen_original:
                seen_original[k] = item.strip()
            counts[k] += 1

    ranked = [k for k, _c in sorted(counts.items(), key=lambda x: (-x[1], x[0])) if counts[k] > 1]
    seen_in_ranked = set(ranked)

    max_len = max((len(items) for items in per_cell_items), default=0)
    for i in range(max_len):
        if len(ranked) >= cap:
            break
        for items in per_cell_items:
            if i < len(items):
                k = items[i].strip().lower() if isinstance(items[i], str) else ""
                if k and k not in seen_in_ranked:
                    ranked.append(k)
                    seen_in_ranked.add(k)
                    if len(ranked) >= cap:
                        break

    shared_count = sum(1 for c in counts.values() if c > 1)
    return [seen_original[k] for k in ranked[:cap]], len(seen_original), shared_count


def _filter_parseable(cells: list[dict]) -> list[dict]:
    """Return cells whose response.parsed is a non-null dict and error is None."""
    out = []
    for cell in cells:
        if cell.get("error"):
            continue
        parsed = cell.get("response", {}).get("parsed")
        if isinstance(parsed, dict) and parsed:
            out.append(cell)
    return out


def _merge_deterministic(cells: list[dict]) -> tuple[dict, dict]:
    """Apply deterministic merge rules to all non-narrative fields."""
    parseds = [c["response"]["parsed"] for c in cells]
    confidences = [(c, c["response"]["parsed"].get("confidence", 0.0) or 0.0) for c in cells]
    confidences.sort(key=lambda x: (-x[1], x[0]["vendor"]["name"]))

    merged: dict = {}
    prov: dict = {}

    # artist_name: highest confidence
    for cell, _conf in confidences:
        v = cell["response"]["parsed"].get("artist_name")
        if v:
            merged["artist_name"] = v
            prov["artist_name"] = f"highest confidence({cell['vendor']['name']})"
            break
    if "artist_name" not in merged:
        merged["artist_name"] = parseds[0].get("artist_name", "")
        prov["artist_name"] = "fallback first"

    # Numeric fields: median of non-null
    for field in NUMERIC_FIELDS:
        vals = [p.get(field) for p in parseds if p.get(field) is not None]
        if vals:
            m = median(vals)
            merged[field] = int(round(m))
            prov[field] = f"median:{merged[field]}"
        else:
            merged[field] = None
            prov[field] = "all null"

    # Enum fields: majority vote, tie -> highest confidence; "unknown" abstains
    for field in ENUM_FIELDS:
        raw_vals = [p.get(field) for p in parseds if p.get(field) is not None]
        voting_vals = [v for v in raw_vals if v != "unknown"]
        if not voting_vals:
            merged[field] = "unknown"
            prov[field] = "all unknown" if raw_vals else "all null"
            continue
        if len(voting_vals) == 1:
            merged[field] = voting_vals[0]
            contributing = None
            for c in cells:
                if c["response"]["parsed"].get(field) == voting_vals[0]:
                    contributing = c["vendor"]["name"]
                    break
            prov[field] = f"only definitive source({contributing})"
            continue
        counts = Counter(voting_vals)
        top_count = max(counts.values())
        top_vals = [v for v, c in counts.items() if c == top_count]
        if len(top_vals) == 1:
            merged[field] = top_vals[0]
            prov[field] = f"majority({top_count}/{len(voting_vals)} definitive)"
        else:
            chosen = None
            for cell, _conf in confidences:
                v = cell["response"]["parsed"].get(field)
                if v in top_vals:
                    chosen = v
                    break
            merged[field] = chosen if chosen is not None else top_vals[0]
            prov[field] = f"tie → highest confidence({merged[field]})"

    # country: majority, tie -> shortest
    country_vals = [p.get("country") for p in parseds if p.get("country")]
    if country_vals:
        if len(country_vals) == 1:
            merged["country"] = country_vals[0]
            contributing = None
            for c in cells:
                if c["response"]["parsed"].get("country") == country_vals[0]:
                    contributing = c["vendor"]["name"]
                    break
            prov["country"] = f"only source({contributing})"
        else:
            counts = Counter(country_vals)
            top_count = max(counts.values())
            top_vals = [v for v, c in counts.items() if c == top_count]
            if len(top_vals) == 1:
                merged["country"] = top_vals[0]
                prov["country"] = f"majority({top_count}/{len(country_vals)})"
            else:
                merged["country"] = min(top_vals, key=len)
                prov["country"] = f"tie → shortest({merged['country']})"
    else:
        merged["country"] = None
        prov["country"] = "all null"

    # Other string fields: majority, tie -> highest confidence
    for field in STRING_FIELDS:
        vals = [p.get(field) for p in parseds if p.get(field)]
        if not vals:
            merged[field] = None
            prov[field] = "all null"
            continue
        if len(vals) == 1:
            merged[field] = vals[0]
            contributing = None
            for c in cells:
                if c["response"]["parsed"].get(field) == vals[0]:
                    contributing = c["vendor"]["name"]
                    break
            prov[field] = f"only source({contributing})"
            continue
        counts = Counter(vals)
        top_count = max(counts.values())
        top_vals = [v for v, c in counts.items() if c == top_count]
        if len(top_vals) == 1:
            merged[field] = top_vals[0]
            prov[field] = f"majority({top_count}/{len(vals)})"
        else:
            chosen = None
            for cell, _conf in confidences:
                v = cell["response"]["parsed"].get(field)
                if v in top_vals:
                    chosen = v
                    break
            merged[field] = chosen if chosen else top_vals[0]
            prov[field] = f"tie → highest confidence({merged[field]})"

    # URL fields: pick from highest-confidence cell with non-null value
    for field in URL_FIELDS:
        chosen = None
        chosen_vendor = None
        for cell, _conf in confidences:
            v = cell["response"]["parsed"].get(field)
            if v:
                chosen = v
                chosen_vendor = cell["vendor"]["name"]
                break
        merged[field] = chosen
        prov[field] = f"highest confidence({chosen_vendor})" if chosen else "all null"

    # List fields: capped lists use round-robin top-5; others union all
    cells_by_conf = [c for c, _ in confidences]
    for field in LIST_FIELDS:
        if field in CAPPED_LIST_FIELDS:
            per_cell = [(c["response"]["parsed"].get(field, []) or []) for c in cells_by_conf]
            ranked_items, unique_count, shared_count = _rank_list_round_robin(per_cell, cap=5)
            merged[field] = ranked_items
            prov[field] = f"union top-5 round-robin({unique_count} unique, {shared_count} shared)"
            continue
        all_items: list[str] = []
        for p in parseds:
            for item in p.get(field, []) or []:
                if isinstance(item, str) and item.strip():
                    all_items.append(item.strip())
        seen: dict[str, str] = {}
        counts2: Counter[str] = Counter()
        for item in all_items:
            key = item.lower()
            if key not in seen:
                seen[key] = item
            counts2[key] += 1
        merged[field] = [seen[k] for k in sorted(seen.keys(), key=lambda k: -counts2[k])]
        prov[field] = f"union({len(seen)})"

    # ai_signals: dedup by (kind, normalized description)
    seen_signals: dict[tuple[str, str], dict] = {}
    for p in parseds:
        for sig in p.get("ai_signals", []) or []:
            if not isinstance(sig, dict):
                continue
            kind = sig.get("kind") or ""
            desc = (sig.get("description") or "").strip().lower()
            key = (kind, desc)
            if key not in seen_signals and desc:
                seen_signals[key] = sig
    merged["ai_signals"] = list(seen_signals.values())
    prov["ai_signals"] = f"union({len(seen_signals)})"

    # confidence: mean of non-null
    confs = [p.get("confidence") for p in parseds if isinstance(p.get("confidence"), (int, float))]
    if confs:
        mean = sum(confs) / len(confs)
        merged["confidence"] = round(mean, 4)
        prov["confidence"] = f"mean({len(confs)})"
    else:
        merged["confidence"] = 0.0
        prov["confidence"] = "all null"

    return merged, prov


NARRATIVE_SYSTEM = (
    "You are a music-industry data editor. You will receive multiple vendor-sourced JSON descriptions "
    "of a music artist. Synthesise them into a single, accurate, well-written set of narrative fields. "
    "Return a JSON object with exactly these keys: tagline, bio, summary, ai_reasoning, notes. "
    "tagline: one punchy sentence (≤ 100 chars). "
    "bio: 1-3 factual sentences about the artist. "
    "summary: 2-4 sentences, factual, no superlatives. "
    "ai_reasoning: concise explanation of any AI-generation signals found, or 'No AI signals detected.' "
    "notes: any caveats about identity disambiguation or data conflicts, or null. "
    "Output ONLY valid JSON, no markdown fences."
)


def _build_narrative_prompt(artist_name: str, cells: list[dict]) -> str:
    parts = [f"Artist: {artist_name}\n"]
    for i, cell in enumerate(cells, 1):
        vendor = cell["vendor"]["name"]
        p = cell["response"]["parsed"]
        conf = p.get("confidence", 0.0)
        parts.append(
            f"--- Source {i} ({vendor}, confidence={conf}) ---\n"
            f"tagline: {p.get('tagline')}\n"
            f"bio: {p.get('bio')}\n"
            f"summary: {p.get('summary')}\n"
            f"ai_reasoning: {p.get('ai_reasoning')}\n"
            f"notes: {p.get('notes')}\n"
        )
    parts.append("\nSynthesize the above into the required JSON.")
    return "\n".join(parts)


def _highest_confidence_cell(cells: list[dict]) -> dict:
    return max(cells, key=lambda c: c["response"]["parsed"].get("confidence", 0.0) or 0.0)


def _merge_narrative(
    cells: list[dict],
    deepseek_client: Any,
    deepseek_model: str,
    artist_name: str,
) -> tuple[dict, dict]:
    """Call DeepSeek for narrative fields; fall back to max-confidence cell on any error."""
    t0 = time.monotonic()
    try:
        user_msg = _build_narrative_prompt(artist_name, cells)
        resp = deepseek_client.chat.completions.create(
            model=deepseek_model,
            messages=[
                {"role": "system", "content": NARRATIVE_SYSTEM},
                {"role": "user", "content": user_msg},
            ],
            response_format={"type": "json_object"},
            temperature=0.1,
        )
        latency_ms = (time.monotonic() - t0) * 1000
        raw_content = resp.choices[0].message.content
        parsed_narrative = json.loads(raw_content)
        for key in NARRATIVE_FIELDS:
            if key not in parsed_narrative:
                raise KeyError(f"Missing narrative key: {key}")
        usage = resp.usage
        cost = estimate_cost(deepseek_model, usage.prompt_tokens, usage.completion_tokens)
        meta = {"narrative_cost_usd": cost, "narrative_latency_ms": latency_ms}
        return {k: parsed_narrative[k] for k in NARRATIVE_FIELDS}, meta
    except Exception:
        latency_ms = (time.monotonic() - t0) * 1000
        best = _highest_confidence_cell(cells)
        p = best["response"]["parsed"]
        fallback_fields = {k: p.get(k) for k in NARRATIVE_FIELDS}
        meta = {
            "narrative_cost_usd": 0.0,
            "narrative_latency_ms": latency_ms,
            "narrative_fallback": "max_confidence",
        }
        return fallback_fields, meta


def merge_cells(
    cells: list[dict],
    deepseek_client: Any,
    deepseek_model: str = "deepseek-v4-flash",
) -> tuple[ArtistInfo, dict]:
    """Merge vendor cells into a single ArtistInfo with DeepSeek narrative synthesis."""
    parseable = _filter_parseable(cells)

    if not parseable:
        artist_name = ""
        if cells:
            artist_name = cells[0].get("fixture", {}).get("artist_name", "")
        info = ArtistInfo(
            artist_name=artist_name or "unknown",
            summary="All vendor sources failed.",
            ai_reasoning="n/a",
            confidence=0.0,
        )
        meta: dict[str, Any] = {
            "all_failed": True,
            "source_count": 0,
            "narrative_cost_usd": 0.0,
            "narrative_latency_ms": 0.0,
            "field_provenance": {},
        }
        return info, meta

    if len(parseable) == 1:
        p = parseable[0]["response"]["parsed"]
        info = ArtistInfo.model_validate(p)
        meta = {
            "single_source": True,
            "source_count": 1,
            "narrative_cost_usd": 0.0,
            "narrative_latency_ms": 0.0,
            "field_provenance": {"tagline": "single source", "summary": "single source"},
        }
        return info, meta

    artist_name = parseable[0].get("fixture", {}).get("artist_name", "")
    if not artist_name:
        artist_name = parseable[0]["response"]["parsed"].get("artist_name", "unknown")

    det_payload, det_prov = _merge_deterministic(parseable)
    narr_fields, narr_meta = _merge_narrative(parseable, deepseek_client, deepseek_model, artist_name)

    final: dict[str, Any] = {**det_payload}
    for key in NARRATIVE_FIELDS:
        final[key] = narr_fields.get(key)

    narr_prov_label = "max_confidence fallback" if "narrative_fallback" in narr_meta else "deepseek narrative"
    narr_prov = {k: narr_prov_label for k in NARRATIVE_FIELDS}
    combined_prov = {**det_prov, **narr_prov}

    info = ArtistInfo.model_validate(final)

    meta = {
        "source_count": len(parseable),
        "narrative_cost_usd": narr_meta["narrative_cost_usd"],
        "narrative_latency_ms": narr_meta["narrative_latency_ms"],
        "field_provenance": combined_prov,
    }
    if "narrative_fallback" in narr_meta:
        meta["narrative_fallback"] = narr_meta["narrative_fallback"]

    return info, meta
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd experiments/artists && .venv/bin/pytest tests/test_aggregate.py -q`
Expected: PASS (14 passed).

- [ ] **Step 5: Commit**

```bash
git add experiments/artists/src/artlab/aggregate.py experiments/artists/tests/test_aggregate.py
git commit -m "feat(artist-lab): add consensus aggregator"
```

---

## Task 8: Markdown report generator

**Files:**
- Create: `experiments/artists/src/artlab/report.py`
- Test: `experiments/artists/tests/test_report.py`

- [ ] **Step 1: Write the failing test**

Create `experiments/artists/tests/test_report.py`:

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
            "artist_name": parsed.get("artist_name", fixture_id),
            "style": "techno",
            "sample_tracks": [],
            "known_labels": [],
            "ground_truth": {"country": "Brazil", "active_since": 2010, "ai_content_expected": "none_detected"}
            if fixture_id == "anna"
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
        json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def _write_manifest(run_dir: Path, ok: int, err: int, cost: float) -> None:
    manifest = {
        "run_id": run_dir.name,
        "started_at": "2026-05-26T10:00:00+00:00",
        "finished_at": "2026-05-26T10:01:00+00:00",
        "prompts": [{"slug": "artist_v1", "version": "v1"}],
        "vendors": [{"name": "openai", "model": "gpt-5.4-mini"}, {"name": "perplexity", "model": "sonar"}],
        "fixtures": ["anna"],
        "totals": {"cells": ok + err, "ok": ok, "error": err, "cost_usd": cost},
    }
    (run_dir / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")


def test_build_report_renders_sections(tmp_path):
    from artlab.report import build_report

    run_dir = tmp_path / "outputs" / "20260526-100000-abcd"
    reports_dir = tmp_path / "reports"

    _write_cell(run_dir, "artist_v1", "openai", "anna", {
        "artist_name": "ANNA", "country": "Brazil", "active_since": 2010,
        "ai_content": "none_detected", "ai_reasoning": "—",
        "summary": "Brazilian techno DJ.", "confidence": 0.9, "notable_releases": ["Hidden Beauties"],
    })
    _write_cell(run_dir, "artist_v1", "perplexity", "anna", {
        "artist_name": "ANNA", "country": "Brazil", "active_since": 2008,
        "ai_content": "none_detected", "ai_reasoning": "—",
        "summary": "DJ.", "confidence": 0.7, "notable_releases": [],
    })
    _write_manifest(run_dir, ok=2, err=0, cost=0.002)

    out_path = build_report(run_dir, reports_dir)
    text = out_path.read_text(encoding="utf-8")

    assert out_path.name.startswith("20260526-100000-abcd")
    assert "## Summary" in text
    assert "ok: 2" in text
    assert "## Fixture: anna" in text
    assert "2010 ✓" in text   # ground-truth active_since match
    assert "2008 ✗" in text   # mismatch
    assert "Brazil ✓" in text
    assert "<details>" in text
    assert "—" in text
    assert "openai-model" in text
    assert "perplexity-model" in text


def _write_merged(run_dir: Path, prompt: str, fixture_id: str, merged_payload: dict, source_cells: list[dict], meta: dict) -> None:
    merged_dir = run_dir / "merged"
    merged_dir.mkdir(exist_ok=True)
    (merged_dir / f"{prompt}__{fixture_id}.json").write_text(json.dumps({
        "run_id": run_dir.name,
        "merged_at": "2026-05-26T20:00:00+00:00",
        "prompt": {"slug": prompt, "version": "v1"},
        "fixture": {
            "id": fixture_id, "artist_name": merged_payload.get("artist_name", fixture_id),
            "style": "techno", "sample_tracks": [], "known_labels": [],
            "ground_truth": {"country": "Brazil", "active_since": 2010, "ai_content_expected": "none_detected"} if fixture_id == "anna" else None,
        },
        "source_cells": source_cells,
        "merged": merged_payload,
        "merge_meta": meta,
        "aggregate_cost_usd": meta.get("narrative_cost_usd", 0.0),
    }, indent=2, ensure_ascii=False), encoding="utf-8")


def test_build_report_renders_aggregated_section(tmp_path):
    from artlab.report import build_report

    run_dir = tmp_path / "outputs" / "20260526-200000-test"
    reports_dir = tmp_path / "reports"

    _write_cell(run_dir, "artist_v1", "openai", "anna", {
        "artist_name": "ANNA", "country": "Brazil", "active_since": 2010,
        "ai_content": "none_detected", "ai_reasoning": "—",
        "summary": "Techno DJ.", "confidence": 0.9, "notable_releases": ["Hidden Beauties"],
    })
    _write_manifest(run_dir, ok=1, err=0, cost=0.001)

    _write_merged(run_dir, "artist_v1", "anna",
        merged_payload={
            "artist_name": "ANNA",
            "tagline": "Brazilian techno force.",
            "country": "Brazil",
            "active_since": 2010,
            "ai_content": "none_detected",
            "confidence": 0.95,
            "notable_releases": ["Hidden Beauties", "Forsaken"],
            "spotify_url": "https://open.spotify.com/artist/abc",
            "summary": "Merged summary.",
            "ai_reasoning": "—",
        },
        source_cells=[
            {"vendor": "openai", "model": "gpt-5.4-mini", "confidence": 0.9},
            {"vendor": "perplexity", "model": "sonar", "confidence": 1.0},
        ],
        meta={
            "field_provenance": {
                "active_since": "median:2010",
                "country": "majority(2/2)",
                "tagline": "deepseek narrative",
            },
            "narrative_cost_usd": 0.0004,
            "narrative_latency_ms": 4200,
        },
    )

    out_path = build_report(run_dir, reports_dir)
    text = out_path.read_text(encoding="utf-8")

    assert "## Aggregated (consensus)" in text
    assert "anna — artist_v1" in text
    assert "Brazilian techno force." in text
    assert "median:2010" in text
    assert "2010 ✓" in text
    assert "Brazil ✓" in text


def test_build_report_no_aggregated_section_when_merged_dir_absent(tmp_path):
    from artlab.report import build_report

    run_dir = tmp_path / "outputs" / "20260526-201000-test"
    reports_dir = tmp_path / "reports"
    _write_cell(run_dir, "artist_v1", "openai", "anna", {
        "artist_name": "ANNA", "country": "Brazil", "active_since": 2010,
        "ai_content": "none_detected", "ai_reasoning": "—",
        "summary": "x", "confidence": 0.9, "notable_releases": [],
    })
    _write_manifest(run_dir, ok=1, err=0, cost=0.001)

    text = build_report(run_dir, reports_dir).read_text()
    assert "## Aggregated" not in text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd experiments/artists && .venv/bin/pytest tests/test_report.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'artlab.report'`.

- [ ] **Step 3: Write `report.py`**

Create `experiments/artists/src/artlab/report.py`:

```python
"""Markdown report generator."""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

# Fields rendered in the per-fixture side-by-side table (one column per vendor)
TABLE_FIELDS: list[str] = [
    # identity
    "country",
    "city",
    "active_since",
    "artist_type",
    "status",
    # assessment
    "ai_content",
    "confidence",
    # taxonomy
    "primary_styles",
    "labels",
    "notable_collaborators",
    "notable_releases",
    # narrative
    "tagline",
    # channels
    "spotify_url",
    "soundcloud_url",
    "bandcamp_url",
    "beatport_url",
    "residentadvisor_url",
    "discogs_url",
    "instagram_url",
    "twitter_url",
    "website",
]

# Same field set is used in the Aggregated (consensus) section.
AGGREGATED_TABLE_FIELDS: list[str] = list(TABLE_FIELDS)

EMPTY = "—"


def _ground_truth_expected(field: str, truth: dict):
    if field == "active_since":
        return truth.get("active_since")
    if field == "country":
        return truth.get("country")
    if field == "ai_content":
        return truth.get("ai_content_expected")
    return None


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
    lines.extend(_aggregated_section(run_dir))
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
    by_pair_latency: dict[tuple[str, str], list[int]] = defaultdict(list)
    by_pair_cost: dict[tuple[str, str], float] = defaultdict(float)
    for cell in cells:
        key = (cell["vendor"]["name"], cell["vendor"]["model"])
        by_pair_latency[key].append(int(cell["response"]["latency_ms"]))
        by_pair_cost[key] += float(cell["response"]["usage"].get("cost_usd") or 0.0)
    rows = []
    rows.append("## Summary")
    rows.append("")
    rows.append(f"- cells: {totals['cells']}")
    rows.append(f"- ok: {totals['ok']}")
    rows.append(f"- error: {totals['error']}")
    rows.append(f"- total cost: ${totals['cost_usd']:.4f}")
    rows.append("")
    rows.append("| Vendor | Model | Mean latency (ms) | Total cost (USD) |")
    rows.append("| --- | --- | --- | --- |")
    for (vendor, model) in sorted(by_pair_latency):
        lats = by_pair_latency[(vendor, model)]
        mean = sum(lats) / len(lats)
        cost = by_pair_cost[(vendor, model)]
        rows.append(f"| {vendor} | {model} | {mean:.0f} | {cost:.4f} |")
    rows.append("")
    return rows


def _aggregated_section(run_dir: Path) -> list[str]:
    merged_dir = run_dir / "merged"
    if not merged_dir.exists():
        return []
    files = sorted(merged_dir.glob("*.json"))
    if not files:
        return []

    rows: list[str] = ["## Aggregated (consensus)", ""]
    total_cost = 0.0
    payloads = []
    for f in files:
        payload = json.loads(f.read_text(encoding="utf-8"))
        payloads.append(payload)
        total_cost += float(payload.get("aggregate_cost_usd") or 0.0)
    rows.append(f"Merged via DeepSeek narrative + deterministic rules. Total aggregate cost: ${total_cost:.4f}.")
    rows.append("")

    for payload in payloads:
        rows.extend(_aggregated_one(payload))

    return rows


def _aggregated_one(payload: dict) -> list[str]:
    fixture_id = payload["fixture"]["id"]
    prompt_slug = payload["prompt"]["slug"]
    sources = payload.get("source_cells") or []
    merged = payload.get("merged") or {}
    prov = (payload.get("merge_meta") or {}).get("field_provenance") or {}
    truth = (payload["fixture"].get("ground_truth")) or {}

    rows: list[str] = []
    rows.append(f"### {fixture_id} — {prompt_slug} ({len(sources)} sources)")
    rows.append("")
    rows.append("| field | value | provenance |")
    rows.append("| --- | --- | --- |")

    for field in AGGREGATED_TABLE_FIELDS:
        raw_value = merged.get(field)
        if raw_value is None or raw_value == [] or raw_value == "":
            rendered = EMPTY
        elif isinstance(raw_value, list):
            rendered = ", ".join(str(v) for v in raw_value)
        else:
            rendered = str(raw_value)

        expected = _ground_truth_expected(field, truth)
        if expected is not None and rendered != EMPTY:
            rendered += " ✓" if str(raw_value) == str(expected) else " ✗"

        rows.append(f"| {field} | {rendered} | {prov.get(field, '—')} |")

    rows.append("")
    sources_line = ", ".join(f"{s['vendor']}/{s['model']}" for s in sources)
    rows.append(f"**Sources:** {sources_line}")
    rows.append("")
    return rows


def _fixture_section(fixture_id: str, cells: list[dict]) -> list[str]:
    if not cells:
        return []
    first = cells[0]
    artist_name = first["fixture"]["artist_name"]
    style = first["fixture"]["style"]
    truth = first["fixture"].get("ground_truth") or {}

    rows = []
    rows.append(f"## Fixture: {fixture_id}")
    rows.append("")
    rows.append(f"**{artist_name}** — {style}")
    if truth:
        bits = [f"{k}={v}" for k, v in truth.items() if v is not None]
        if bits:
            rows.append(f"_Ground truth:_ {', '.join(bits)}")
    rows.append("")

    headers = ["field"] + [
        f"{c['prompt']['slug']} / {c['vendor']['name']} ({c['vendor']['model']})"
        for c in cells
    ]
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

    expected = _ground_truth_expected(field, truth)
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
            releases = parsed.get("notable_releases") or []
            reasoning = parsed.get("ai_reasoning") or EMPTY
            rows.append(f"**summary:** {summary}")
            rows.append("")
            rows.append(f"**notable releases:** {', '.join(releases) if releases else EMPTY}")
            rows.append("")
            rows.append(f"**ai_reasoning:** {reasoning}")
        rows.append("")
        rows.append("</details>")
        rows.append("")
    return rows
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd experiments/artists && .venv/bin/pytest tests/test_report.py -q`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add experiments/artists/src/artlab/report.py experiments/artists/tests/test_report.py
git commit -m "feat(artist-lab): add markdown report generator"
```

---

## Task 9: CLI + vendor/pricing tests

**Files:**
- Create (cp + edit): `experiments/artists/src/artlab/cli.py`
- Create (cp + sed): `experiments/artists/tests/test_pricing.py`, `experiments/artists/tests/test_vendor_*.py` (7 files)

- [ ] **Step 1: Copy `cli.py` verbatim from the label sandbox**

Run from the worktree root:

```bash
cp experiments/labels/src/lab/cli.py experiments/artists/src/artlab/cli.py
```

- [ ] **Step 2: Adapt the ROOT comment**

In `experiments/artists/src/artlab/cli.py`, replace:

```python
ROOT = Path(__file__).resolve().parents[2]  # experiments/labels/
```

with:

```python
ROOT = Path(__file__).resolve().parents[2]  # experiments/artists/
```

- [ ] **Step 3: Adapt the app help text**

Replace:

```python
app = typer.Typer(help="Local sandbox for label AI experiments.")
```

with:

```python
app = typer.Typer(help="Local sandbox for artist AI experiments.")
```

- [ ] **Step 4: Adapt the aggregate command docstring**

Replace:

```python
    """Merge per-vendor cells in a run into consensus LabelInfo per fixture."""
```

with:

```python
    """Merge per-vendor cells in a run into consensus ArtistInfo per fixture."""
```

- [ ] **Step 5: Adapt `list_fixtures` to artist fields**

Replace the whole `list_fixtures` function:

```python
@list_app.command("fixtures")
def list_fixtures() -> None:
    for f in load_fixtures(FIXTURES_PATH):
        gt = "with ground_truth" if f.ground_truth else "no ground_truth"
        rel = f", release={f.release_name}" if f.release_name else ""
        typer.echo(f"{f.id} — {f.label_name} / {f.style} ({gt}){rel}")
```

with:

```python
@list_app.command("fixtures")
def list_fixtures() -> None:
    for f in load_fixtures(FIXTURES_PATH):
        gt = "with ground_truth" if f.ground_truth else "no ground_truth"
        anchors = []
        if f.sample_tracks:
            anchors.append(f"tracks={'; '.join(f.sample_tracks)}")
        if f.known_labels:
            anchors.append(f"labels={', '.join(f.known_labels)}")
        suffix = f" [{' | '.join(anchors)}]" if anchors else ""
        typer.echo(f"{f.id} — {f.artist_name} / {f.style} ({gt}){suffix}")
```

(No other change is needed: `cli.py` builds vendors, runs the matrix, aggregates via DeepSeek and builds the report — all already artist-shaped through the modules they import.)

- [ ] **Step 6: Copy and rename the vendor + pricing tests**

These adapter tests exercise SDK mechanics, not label fields. Copy them, then rewrite the only schema couplings (`LabelInfo` → `ArtistInfo`, `label_name=` → `artist_name=`, `from lab.` → `from artlab.`).

Run from the worktree root:

```bash
cp experiments/labels/tests/test_pricing.py experiments/artists/tests/test_pricing.py
cp experiments/labels/tests/test_vendor_anthropic.py experiments/artists/tests/test_vendor_anthropic.py
cp experiments/labels/tests/test_vendor_gemini.py experiments/artists/tests/test_vendor_gemini.py
cp experiments/labels/tests/test_vendor_grok.py experiments/artists/tests/test_vendor_grok.py
cp experiments/labels/tests/test_vendor_kimi.py experiments/artists/tests/test_vendor_kimi.py
cp experiments/labels/tests/test_vendor_openai.py experiments/artists/tests/test_vendor_openai.py
cp experiments/labels/tests/test_vendor_perplexity.py experiments/artists/tests/test_vendor_perplexity.py
cp experiments/labels/tests/test_vendor_tavily_deepseek.py experiments/artists/tests/test_vendor_tavily_deepseek.py

sed -i '' \
  -e 's/from lab\./from artlab./g' \
  -e 's/LabelInfo/ArtistInfo/g' \
  -e 's/label_name=/artist_name=/g' \
  experiments/artists/tests/test_pricing.py \
  experiments/artists/tests/test_vendor_*.py
```

- [ ] **Step 7: Confirm no label couplings remain in the copied tests**

Run: `grep -ln "from lab\.\|LabelInfo\|label_name=" experiments/artists/tests/test_pricing.py experiments/artists/tests/test_vendor_*.py`
Expected: no output (exit code 1). If any file is listed, open it and replace the remaining reference by hand (e.g. a `label_name` used without a trailing `=`).

- [ ] **Step 8: Run the vendor + pricing tests**

Run: `cd experiments/artists && .venv/bin/pytest tests/test_pricing.py tests/test_vendor_anthropic.py tests/test_vendor_gemini.py tests/test_vendor_grok.py tests/test_vendor_kimi.py tests/test_vendor_openai.py tests/test_vendor_perplexity.py tests/test_vendor_tavily_deepseek.py -q`
Expected: PASS. If a vendor test references a label-only field beyond the three handled by the sed (rare), fix that single reference and rerun.

- [ ] **Step 9: Smoke-test the CLI (no API key needed)**

Run: `cd experiments/artists && .venv/bin/artlab list fixtures`
Expected: prints the 5 fixtures, e.g. `anna — ANNA / techno (with ground_truth) [tracks=Hidden Beauties; Forsaken | labels=Drumcode, Kompakt]`.

Run: `cd experiments/artists && .venv/bin/artlab list prompts`
Expected: `artist_v1/v1 — Facts-discipline + disambiguation + AI detection for artists.`

- [ ] **Step 10: Commit**

```bash
git add experiments/artists/src/artlab/cli.py experiments/artists/tests/test_pricing.py experiments/artists/tests/test_vendor_*.py
git commit -m "feat(artist-lab): add CLI and vendor tests"
```

---

## Task 10: Full suite + manual verification

**Files:** none (verification only).

- [ ] **Step 1: Run the entire test suite**

Run: `cd experiments/artists && .venv/bin/pytest -q`
Expected: all tests pass (schemas 5, prompts 6, fixtures 2, config 4, runner 3, aggregate 14, report 3, pricing + 7 vendor suites). No failures, no errors.

- [ ] **Step 2: Confirm the package has no leftover label references**

Run: `grep -rn "label_name\|LabelInfo\|from lab\b\|label_v" experiments/artists/src`
Expected: no output (exit code 1).

- [ ] **Step 3 (optional, costs a few cents): live single-vendor run**

Only if an `OPENAI_API_KEY` is available. Run:

```bash
cd experiments/artists
cp .env.example .env   # then paste OPENAI_API_KEY into .env
.venv/bin/artlab run --prompts artist_v1 --vendors openai --fixtures anna
.venv/bin/artlab report <run_id_printed_above>
open reports/<run_id>.md
```

Expected: one cell written under `outputs/<run_id>/`, a report at `reports/<run_id>.md` showing ANNA's country/labels/links and an `ai_content` assessment. Sanity-check the disambiguation worked (the resolved artist is the Brazilian techno ANNA, not another "ANNA").

- [ ] **Step 4: Final commit (only if Step 3 produced doc-worthy notes)**

If the live run surfaced prompt tweaks, capture them in `experiments/artists/README.md` under a short "Findings" heading and commit:

```bash
git add experiments/artists/README.md
git commit -m "docs(artist-lab): note first-run findings"
```

Otherwise no commit — the experiment is complete and green.

---

## Notes on deferred production work

This plan delivers ONLY the local experiment. Once `artist_v1` + `ArtistInfo` are validated, the production feature (Aurora tables, `artist_enrichment` Lambda + SQS queue, `/admin/artists/enrich` and `/admin/auto-enrich/artists` routes, the frontend "artists" tab) follows the label pattern and gets its own spec → plan → implementation cycle. See the spec's "Future" section.

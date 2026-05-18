# Label Enrichment Pipeline Implementation Plan (Phase 1)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add app-targeted fields to `LabelInfo` (logo, Instagram, Twitter, tagline), a new prompt `label_v3_app_fields/v1` that asks for them, and a multi-vendor consensus aggregator (`merge_cells()` core + `lab aggregate` CLI + report section) that merges per-vendor outputs into a single `LabelInfo` with field-level provenance.

**Architecture:** Pure Python additions inside the existing sandbox at `experiments/labels/`. The new `lab/aggregate.py` module exposes one public function `merge_cells(cells, deepseek_client, deepseek_model) -> (LabelInfo, meta)` with private helpers for deterministic field rules and one DeepSeek narrative call. The `lab aggregate` CLI subcommand reads `outputs/<run_id>/`, groups cells by `(prompt, fixture)`, writes `outputs/<run_id>/merged/*.json`, appends an `aggregates` block to `manifest.json`, and re-renders the markdown report which now has a `## Aggregated (consensus)` section. Production code under `src/collector/` is not touched.

**Tech Stack:** Python 3.12, `pydantic>=2`, existing `openai` SDK pointed at DeepSeek base URL, existing `typer` CLI, existing `pytest`. No new runtime dependencies.

**Spec:** `docs/superpowers/specs/2026-05-18-label-enrichment-pipeline-design.md` (commit `1aead98`).

---

## File Structure

```
experiments/labels/
  src/lab/
    schemas.py                      # MODIFY: 4 new Optional fields on LabelInfo
    prompts/
      __init__.py                   # MODIFY: register new prompt in load_builtin_prompts
      label_v3_app_fields.py        # CREATE: new prompt module
    aggregate.py                    # CREATE: merge_cells() + private helpers
    cli.py                          # MODIFY: add `lab aggregate` subcommand
    report.py                       # MODIFY: render ## Aggregated section when merged/ exists
  tests/
    test_schemas.py                 # MODIFY: tests for new fields
    test_prompts.py                 # MODIFY: assert new prompt registers
    test_cli.py                     # MODIFY: list prompts now includes v3_app_fields; new aggregate test
    test_aggregate.py               # CREATE: merge_cells and helpers
    test_report.py                  # MODIFY: aggregated section rendering
  README.md                         # MODIFY: pipeline section
```

Each file keeps one clear responsibility. The aggregator orchestrator (`aggregate.py`) is one file because the core logic — filter, deterministic merge, narrative merge — fits comfortably together; private helpers keep functions small and testable.

---

## Conventions for the Engineer

- Run every test command from `experiments/labels/` so `pytest.ini` picks up `pythonpath = ["src"]`.
- Conventional Commits, scope `experiments`. Project hooks reject other formats. Use heredoc form for multi-line commit bodies.
- Never add `Co-Authored-By: Claude` trailers — the `caveman-commit` hook blocks the commit.
- Do not modify `src/collector/`, `infra/`, the root `pyproject.toml`, or any file outside `experiments/labels/`.
- DeepSeek client is constructed in the CLI via the existing settings; tests inject a `MagicMock` so no live API call happens during `pytest`.

---

## Task 1: Schema additions — 4 Optional fields on LabelInfo

**Files:**
- Modify: `experiments/labels/src/lab/schemas.py`
- Modify: `experiments/labels/tests/test_schemas.py`

- [ ] **Step 1: Write the failing test**

Append to `experiments/labels/tests/test_schemas.py`:

```python
def test_label_info_accepts_new_app_fields():
    info = LabelInfo(
        label_name="Drumcode",
        logo_url="https://example.com/drumcode-avatar.png",
        tagline="Swedish techno powerhouse since 1996.",
        instagram_url="https://www.instagram.com/drumcode_se",
        twitter_url="https://x.com/drumcode",
        ai_reasoning="No AI signals.",
        summary="Swedish techno label.",
        confidence=0.9,
    )
    assert info.logo_url == "https://example.com/drumcode-avatar.png"
    assert info.tagline == "Swedish techno powerhouse since 1996."
    assert info.instagram_url == "https://www.instagram.com/drumcode_se"
    assert info.twitter_url == "https://x.com/drumcode"


def test_label_info_new_fields_optional():
    info = LabelInfo(
        label_name="Anjunadeep",
        ai_reasoning="-",
        summary="-",
        confidence=0.5,
    )
    assert info.logo_url is None
    assert info.tagline is None
    assert info.instagram_url is None
    assert info.twitter_url is None
```

- [ ] **Step 2: Run test, expect failure**

```bash
.venv/bin/pytest tests/test_schemas.py::test_label_info_accepts_new_app_fields -v
```

Expected: `AttributeError` or `ValidationError` — the new fields don't exist on `LabelInfo`.

- [ ] **Step 3: Add the four fields to `LabelInfo`**

In `experiments/labels/src/lab/schemas.py`, locate the `LabelInfo` class. Add `logo_url` and `tagline` next to other identity-block fields (after `status`), and add `instagram_url` and `twitter_url` next to the other channel URLs (after `soundcloud_url`):

```python
class LabelInfo(BaseModel):
    # identity (existing fields stay as-is)
    label_name: str
    aliases: list[str] = Field(default_factory=list)
    parent_label: str | None = None
    sublabels: list[str] = Field(default_factory=list)
    country: str | None = None
    founded_year: int | None = None
    status: Literal["active", "inactive", "unknown"] = "unknown"
    logo_url: str | None = None       # NEW
    tagline: str | None = None        # NEW

    # ... size block unchanged ...

    # channels
    website: str | None = None
    bandcamp_url: str | None = None
    residentadvisor_url: str | None = None
    discogs_url: str | None = None
    beatport_url: str | None = None
    soundcloud_url: str | None = None
    instagram_url: str | None = None  # NEW
    twitter_url: str | None = None    # NEW

    # ... rest unchanged ...
```

- [ ] **Step 4: Run tests, expect pass**

```bash
.venv/bin/pytest tests/test_schemas.py -v
```

Expected: all schema tests pass (existing + 2 new).

- [ ] **Step 5: Run the full suite to confirm no regression**

```bash
.venv/bin/pytest -v
```

Expected: previous test count + 2 = 53 passed (was 51).

- [ ] **Step 6: Commit**

```bash
git add experiments/labels/src/lab/schemas.py experiments/labels/tests/test_schemas.py
git commit -m "feat(experiments): add logo_url, tagline, instagram_url, twitter_url to LabelInfo"
```

---

## Task 2: Create `label_v3_app_fields/v1` prompt

**Files:**
- Create: `experiments/labels/src/lab/prompts/label_v3_app_fields.py`
- Modify: `experiments/labels/src/lab/prompts/__init__.py` (add to `load_builtin_prompts`)
- Modify: `experiments/labels/tests/test_prompts.py` (assert new prompt registers)
- Modify: `experiments/labels/tests/test_cli.py` (list-prompts now includes new slug)

- [ ] **Step 1: Update tests first**

Replace the existing `test_builtin_prompts_register` in `experiments/labels/tests/test_prompts.py`:

```python
def test_builtin_prompts_register():
    from lab.prompts import PROMPTS, load_builtin_prompts

    load_builtin_prompts()
    assert {"label_v1_baseline", "label_v2_facts", "label_v3_app_fields"} <= set(PROMPTS)
    assert "label_v3_ai_focus" not in PROMPTS


def test_label_v3_app_fields_contains_app_directives():
    from lab.prompts import PROMPTS, load_builtin_prompts

    load_builtin_prompts()
    cfg = PROMPTS["label_v3_app_fields"]
    assert cfg.version == "v1"
    assert "logo_url" in cfg.system
    assert "instagram_url" in cfg.system
    assert "tagline" in cfg.system
    assert "label logo image URL" in cfg.user_template
```

In `experiments/labels/tests/test_cli.py::test_list_prompts`, replace the assertion list:

```python
def test_list_prompts():
    result = runner.invoke(app, ["list", "prompts"])
    assert result.exit_code == 0
    assert "label_v1_baseline" in result.stdout
    assert "label_v2_facts" in result.stdout
    assert "label_v3_app_fields" in result.stdout
    assert "label_v3_ai_focus" not in result.stdout
```

- [ ] **Step 2: Run tests, expect failure**

```bash
.venv/bin/pytest tests/test_prompts.py tests/test_cli.py -v
```

Expected: failures for `test_builtin_prompts_register`, `test_label_v3_app_fields_contains_app_directives`, `test_list_prompts`. The new prompt module doesn't exist yet.

- [ ] **Step 3: Create the prompt module**

Create `experiments/labels/src/lab/prompts/label_v3_app_fields.py`:

```python
"""label_v3_app_fields — label_v2_facts plus logo, socials, tagline for app integration."""

from __future__ import annotations

from . import register
from .base import PromptConfig
from .label_v2_facts import SYSTEM as V2_SYSTEM
from ..schemas import LabelInfo

APP_FIELDS_BLOCK = (
    "\n\n"
    "- `logo_url`: prefer the label's official square/profile image as a "
    "direct image URL (ends with .png/.jpg/.webp/.gif). Source priority: "
    "Bandcamp profile avatar > Discogs label image > official website "
    "logo > SoundCloud avatar. Leave null if no clear direct image URL is "
    "found. Do not return page URLs.\n"
    "- `instagram_url` / `twitter_url`: official accounts only. Prefer "
    "https://www.instagram.com/<handle> and https://x.com/<handle>. The "
    "handle must match the label name or be clearly linked from the "
    "label's website / Bandcamp / RA. Leave null when uncertain.\n"
    "- `tagline`: one short sentence, max 100 characters, capturing the "
    "label's identity. Examples:\n"
    "    * \"Swedish techno powerhouse since 1996.\"\n"
    "    * \"London home of melodic deep house.\"\n"
    "    * \"AI-generated lofi YouTube channel.\"\n"
    "  Avoid generic copy (\"a record label\"). Leave null only if the "
    "label is truly unknown."
)

USER_TEMPLATE = (
    'Research label "{label_name}" in style "{style}".{release_block}\n'
    "Find: founding year, country, parent and sublabels, catalog and "
    "roster size, releases in the last 12 months, last release date, "
    "official channels (website, Bandcamp, Resident Advisor, Discogs, "
    "Beatport, SoundCloud, Instagram, Twitter/X), label logo image URL, "
    "notable artists, distributor.\n"
    "Write a one-sentence tagline capturing the label's identity.\n"
    "Then assess AI-content status and explain your reasoning."
)


register(
    PromptConfig(
        slug="label_v3_app_fields",
        version="v1",
        description="Facts-discipline plus logo, socials, and tagline for app integration.",
        system=V2_SYSTEM + APP_FIELDS_BLOCK,
        user_template=USER_TEMPLATE,
        schema=LabelInfo,
    )
)
```

- [ ] **Step 4: Wire into `load_builtin_prompts`**

Edit `experiments/labels/src/lab/prompts/__init__.py`. Inside `load_builtin_prompts()`, add the new import next to the existing ones:

```python
def load_builtin_prompts() -> None:
    """Import the built-in prompt modules so they self-register.

    Safe to call multiple times: re-registers configs that may have been
    cleared from the PROMPTS dict between test runs.
    """
    global _BUILTIN_CONFIGS

    if not _BUILTIN_CONFIGS:
        before = set(PROMPTS)
        from . import label_v1_baseline  # noqa: F401
        from . import label_v2_facts  # noqa: F401
        from . import label_v3_app_fields  # noqa: F401
        _BUILTIN_CONFIGS = [cfg for slug, cfg in PROMPTS.items() if slug not in before]

    for cfg in _BUILTIN_CONFIGS:
        register(cfg)
```

- [ ] **Step 5: Run tests, expect pass**

```bash
.venv/bin/pytest tests/test_prompts.py tests/test_cli.py -v
```

Expected: previously failing tests now pass. Full suite: `.venv/bin/pytest` should show 54 passed (53 + 1 new prompt test).

- [ ] **Step 6: Commit**

```bash
git add experiments/labels/src/lab/prompts/ experiments/labels/tests/test_prompts.py experiments/labels/tests/test_cli.py
git commit -m "feat(experiments): add label_v3_app_fields prompt"
```

---

## Task 3: aggregate.py — deterministic field merge (no LLM)

This task builds the pure-Python deterministic merge first. The narrative DeepSeek call comes in Task 4. Splitting like this keeps each test layer focused.

**Files:**
- Create: `experiments/labels/src/lab/aggregate.py`
- Create: `experiments/labels/tests/test_aggregate.py`

- [ ] **Step 1: Write the failing test for filter helper**

Create `experiments/labels/tests/test_aggregate.py`:

```python
"""Tests for lab.aggregate."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from lab.aggregate import (
    _filter_parseable,
    _merge_deterministic,
    merge_cells,
)
from lab.schemas import AIContentStatus, ActivityLevel, LabelInfo


def _cell(vendor: str, model: str, parsed: dict | None = None, error: str | None = None) -> dict:
    """Build a synthetic cell JSON for tests."""
    return {
        "run_id": "test-run",
        "prompt": {"slug": "label_v3_app_fields", "version": "v1"},
        "vendor": {"name": vendor, "model": model},
        "fixture": {"id": "drumcode", "label_name": "Drumcode", "style": "techno", "release_name": None},
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
    """Build a synthetic LabelInfo dump with sensible defaults."""
    base = {
        "label_name": "Drumcode",
        "aliases": [],
        "parent_label": None,
        "sublabels": [],
        "country": "Sweden",
        "founded_year": 1996,
        "status": "active",
        "logo_url": None,
        "tagline": None,
        "catalog_size_estimate": None,
        "roster_size_estimate": None,
        "releases_last_12_months": None,
        "last_release_date": None,
        "activity": "unknown",
        "website": None,
        "bandcamp_url": None,
        "residentadvisor_url": None,
        "discogs_url": None,
        "beatport_url": None,
        "soundcloud_url": None,
        "instagram_url": None,
        "twitter_url": None,
        "notable_artists": [],
        "primary_styles": [],
        "distribution": None,
        "ai_content": "none_detected",
        "ai_signals": [],
        "ai_reasoning": "n/a",
        "summary": "Swedish techno label.",
        "confidence": 0.9,
        "sources": [],
        "notes": None,
    }
    base.update(overrides)
    return base


def test_filter_parseable_drops_errored_and_none_parsed():
    cells = [
        _cell("a", "ma", parsed=_parsed()),
        _cell("b", "mb", parsed=None, error="boom"),
        _cell("c", "mc", parsed=None),
        _cell("d", "md", parsed=_parsed(country="Norway"), error=None),
    ]
    filtered = _filter_parseable(cells)
    assert len(filtered) == 2
    assert filtered[0]["vendor"]["name"] == "a"
    assert filtered[1]["vendor"]["name"] == "d"
```

- [ ] **Step 2: Run test, expect import error**

```bash
.venv/bin/pytest tests/test_aggregate.py -v
```

Expected: `ModuleNotFoundError: No module named 'lab.aggregate'`.

- [ ] **Step 3: Create `aggregate.py` skeleton + `_filter_parseable`**

Create `experiments/labels/src/lab/aggregate.py`:

```python
"""Multi-vendor consensus aggregator for LabelInfo cells.

The single public entry point is `merge_cells`. Private helpers (`_filter_parseable`,
`_merge_deterministic`, `_merge_narrative`) are exposed for tests.
"""

from __future__ import annotations

import json
import time
from collections import Counter, defaultdict
from statistics import median
from typing import Any

from pydantic import BaseModel, ValidationError

from .schemas import LabelInfo
from .vendors.pricing import estimate_cost

NARRATIVE_FIELDS = ("tagline", "summary", "ai_reasoning", "notes")
URL_FIELDS = (
    "logo_url",
    "website",
    "bandcamp_url",
    "residentadvisor_url",
    "discogs_url",
    "beatport_url",
    "soundcloud_url",
    "instagram_url",
    "twitter_url",
)
NUMERIC_FIELDS = (
    "founded_year",
    "catalog_size_estimate",
    "roster_size_estimate",
    "releases_last_12_months",
)
ENUM_FIELDS = ("activity", "ai_content", "status")
LIST_FIELDS = (
    "aliases",
    "sublabels",
    "notable_artists",
    "primary_styles",
    "sources",
)
STRING_FIELDS = ("parent_label", "distribution", "last_release_date", "country")


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
```

- [ ] **Step 4: Run test, expect pass**

```bash
.venv/bin/pytest tests/test_aggregate.py::test_filter_parseable_drops_errored_and_none_parsed -v
```

Expected: 1 passed.

- [ ] **Step 5: Add deterministic merge tests**

Append to `experiments/labels/tests/test_aggregate.py`:

```python
def test_merge_deterministic_numeric_median():
    cells = [
        _cell("a", "ma", parsed=_parsed(founded_year=1995, releases_last_12_months=20)),
        _cell("b", "mb", parsed=_parsed(founded_year=1996, releases_last_12_months=30)),
        _cell("c", "mc", parsed=_parsed(founded_year=1997, releases_last_12_months=None)),
    ]
    merged, prov = _merge_deterministic(cells)
    assert merged["founded_year"] == 1996
    assert prov["founded_year"] == "median:1996"
    assert merged["releases_last_12_months"] == 25  # median of [20, 30]
    assert prov["releases_last_12_months"] == "median:25"


def test_merge_deterministic_enum_majority():
    cells = [
        _cell("a", "ma", parsed=_parsed(activity="high", confidence=0.9)),
        _cell("b", "mb", parsed=_parsed(activity="high", confidence=0.7)),
        _cell("c", "mc", parsed=_parsed(activity="steady", confidence=1.0)),
    ]
    merged, prov = _merge_deterministic(cells)
    assert merged["activity"] == "high"
    assert prov["activity"].startswith("majority")


def test_merge_deterministic_enum_tie_breaks_on_confidence():
    cells = [
        _cell("a", "ma", parsed=_parsed(activity="high", confidence=0.8)),
        _cell("b", "mb", parsed=_parsed(activity="steady", confidence=0.95)),
    ]
    merged, prov = _merge_deterministic(cells)
    assert merged["activity"] == "steady"  # higher confidence wins on tie
    assert "tie" in prov["activity"]


def test_merge_deterministic_country_short_wins_tie():
    cells = [
        _cell("a", "ma", parsed=_parsed(country="United Kingdom")),
        _cell("b", "mb", parsed=_parsed(country="GB")),
    ]
    merged, prov = _merge_deterministic(cells)
    assert merged["country"] == "GB"
    assert "shortest" in prov["country"]


def test_merge_deterministic_list_union_top5_notable_artists():
    cells = [
        _cell("a", "ma", parsed=_parsed(notable_artists=["Adam Beyer", "Amelie Lens", "ANNA"])),
        _cell("b", "mb", parsed=_parsed(notable_artists=["Adam Beyer", "Alan Fitzpatrick", "Bart Skils", "Amelie Lens"])),
        _cell("c", "mc", parsed=_parsed(notable_artists=["Adam Beyer", "Layton Giordani"])),
    ]
    merged, prov = _merge_deterministic(cells)
    artists = merged["notable_artists"]
    assert "Adam Beyer" == artists[0]  # most frequent first
    assert "Amelie Lens" in artists
    assert len(artists) <= 5
    assert "union top-5" in prov["notable_artists"]


def test_merge_deterministic_url_max_confidence_wins():
    cells = [
        _cell("a", "ma", parsed=_parsed(bandcamp_url=None, confidence=0.95)),
        _cell("b", "mb", parsed=_parsed(bandcamp_url="https://drumcode.bandcamp.com/", confidence=0.7)),
        _cell("c", "mc", parsed=_parsed(bandcamp_url="https://drumcode.bandcamp.com", confidence=0.8)),
    ]
    merged, prov = _merge_deterministic(cells)
    assert merged["bandcamp_url"] == "https://drumcode.bandcamp.com"  # from cell c
    assert "highest confidence" in prov["bandcamp_url"]


def test_merge_deterministic_confidence_mean():
    cells = [
        _cell("a", "ma", parsed=_parsed(confidence=0.8)),
        _cell("b", "mb", parsed=_parsed(confidence=1.0)),
        _cell("c", "mc", parsed=_parsed(confidence=0.6)),
    ]
    merged, prov = _merge_deterministic(cells)
    assert merged["confidence"] == pytest.approx(0.8)
    assert prov["confidence"].startswith("mean")
```

- [ ] **Step 6: Run, expect failure**

```bash
.venv/bin/pytest tests/test_aggregate.py -v
```

Expected: many tests fail — `_merge_deterministic` doesn't exist.

- [ ] **Step 7: Implement `_merge_deterministic`**

Append to `experiments/labels/src/lab/aggregate.py`:

```python
def _merge_deterministic(cells: list[dict]) -> tuple[dict, dict]:
    """Apply deterministic merge rules to all non-narrative fields.

    Returns (merged_payload, field_provenance). Narrative fields
    (tagline, summary, ai_reasoning, notes) are left absent from
    merged_payload — they're filled by _merge_narrative.
    """
    parseds = [c["response"]["parsed"] for c in cells]
    confidences = [(c, c["response"]["parsed"].get("confidence", 0.0) or 0.0) for c in cells]
    confidences.sort(key=lambda x: (-x[1], x[0]["vendor"]["name"]))  # desc by conf, asc by vendor

    merged: dict = {}
    prov: dict = {}

    # label_name: highest confidence
    for cell, _conf in confidences:
        v = cell["response"]["parsed"].get("label_name")
        if v:
            merged["label_name"] = v
            prov["label_name"] = f"highest confidence({cell['vendor']['name']})"
            break
    if "label_name" not in merged:
        merged["label_name"] = parseds[0].get("label_name", "")
        prov["label_name"] = "fallback first"

    # Numeric fields: median of non-null
    for field in NUMERIC_FIELDS:
        vals = [p.get(field) for p in parseds if p.get(field) is not None]
        if vals:
            m = median(vals)
            merged[field] = int(m) if isinstance(m, float) and m.is_integer() else (int(m) if field == "founded_year" else m)
            prov[field] = f"median:{merged[field]}"
        else:
            merged[field] = None
            prov[field] = "all null"

    # Enum fields: majority vote, tie → highest confidence
    for field in ENUM_FIELDS:
        vals = [p.get(field) for p in parseds if p.get(field) is not None]
        if not vals:
            merged[field] = None if field == "status" else "unknown"
            prov[field] = "all null"
            continue
        counts = Counter(vals)
        top_count = max(counts.values())
        top_vals = [v for v, c in counts.items() if c == top_count]
        if len(top_vals) == 1:
            merged[field] = top_vals[0]
            prov[field] = f"majority({top_count}/{len(vals)})"
        else:
            # Tie — pick value from highest-confidence cell whose value is in top_vals
            chosen = None
            for cell, _conf in confidences:
                v = cell["response"]["parsed"].get(field)
                if v in top_vals:
                    chosen = v
                    break
            merged[field] = chosen if chosen is not None else top_vals[0]
            prov[field] = f"tie → highest confidence({merged[field]})"

    # country: majority, tie → shortest
    country_vals = [p.get("country") for p in parseds if p.get("country")]
    if country_vals:
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

    # Other string fields: majority, tie → highest confidence
    for field in ("parent_label", "distribution", "last_release_date"):
        vals = [p.get(field) for p in parseds if p.get(field)]
        if not vals:
            merged[field] = None
            prov[field] = "all null"
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

    # List fields: union + dedup; notable_artists capped top-5 by freq
    for field in LIST_FIELDS:
        all_items: list[str] = []
        for p in parseds:
            for item in p.get(field, []) or []:
                if isinstance(item, str) and item.strip():
                    all_items.append(item.strip())
        seen: dict[str, str] = {}  # lowercase → first-cased value
        counts: Counter[str] = Counter()
        for item in all_items:
            key = item.lower()
            if key not in seen:
                seen[key] = item
            counts[key] += 1
        if field == "notable_artists":
            ranked = sorted(seen.keys(), key=lambda k: (-counts[k], k))[:5]
            merged[field] = [seen[k] for k in ranked]
            prov[field] = f"union top-5 by freq({len(seen)} unique)"
        else:
            merged[field] = [seen[k] for k in sorted(seen.keys(), key=lambda k: -counts[k])]
            prov[field] = f"union({len(seen)})"

    # ai_signals: list of dicts, dedup by (kind, description normalized)
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
```

- [ ] **Step 8: Run tests, expect pass**

```bash
.venv/bin/pytest tests/test_aggregate.py -v
```

Expected: all deterministic tests pass.

- [ ] **Step 9: Commit**

```bash
git add experiments/labels/src/lab/aggregate.py experiments/labels/tests/test_aggregate.py
git commit -m "feat(experiments): add deterministic field merge for aggregate"
```

---

## Task 4: aggregate.py — narrative merge via DeepSeek

**Files:**
- Modify: `experiments/labels/src/lab/aggregate.py` (add `_merge_narrative` + public `merge_cells`)
- Modify: `experiments/labels/tests/test_aggregate.py` (tests for narrative + end-to-end)

- [ ] **Step 1: Write the failing test**

Append to `experiments/labels/tests/test_aggregate.py`:

```python
def _mock_deepseek_response(content: str, prompt_tokens: int = 800, completion_tokens: int = 300):
    """Mimic openai SDK chat.completions.create return value."""
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
        "tagline": "Swedish techno powerhouse since 1996.",
        "summary": "Drumcode is a Swedish techno label founded in 1996 by Adam Beyer. It is widely respected for peak-time techno.",
        "ai_reasoning": "No AI signals across multiple vendors.",
        "notes": None,
    }
    fake_deepseek = MagicMock()
    fake_deepseek.chat.completions.create.return_value = _mock_deepseek_response(
        json.dumps(payload)
    )

    cells = [
        _cell("a", "ma", parsed=_parsed(
            tagline="Swedish techno legend.",
            summary="Drumcode, Swedish techno.",
            ai_reasoning="-",
            confidence=0.9,
        )),
        _cell("b", "mb", parsed=_parsed(
            tagline="Peak-time techno from Sweden.",
            summary="Founded 1996 by Adam Beyer.",
            ai_reasoning="-",
            confidence=0.95,
        )),
    ]

    merged, meta = merge_cells(cells, fake_deepseek, deepseek_model="deepseek-v4-flash")
    assert isinstance(merged, LabelInfo)
    assert merged.tagline == "Swedish techno powerhouse since 1996."
    assert "Adam Beyer" in merged.summary
    assert merged.country == "Sweden"
    assert merged.founded_year == 1996
    assert meta["narrative_cost_usd"] > 0
    assert meta["narrative_latency_ms"] >= 0
    assert "field_provenance" in meta
    assert meta["field_provenance"]["tagline"] == "deepseek narrative"
    fake_deepseek.chat.completions.create.assert_called_once()


def test_merge_cells_narrative_fallback_on_deepseek_error():
    fake_deepseek = MagicMock()
    fake_deepseek.chat.completions.create.side_effect = RuntimeError("boom")
    cells = [
        _cell("a", "ma", parsed=_parsed(
            tagline="Low-confidence tagline.",
            summary="Low-conf summary.",
            ai_reasoning="low",
            confidence=0.4,
        )),
        _cell("b", "mb", parsed=_parsed(
            tagline="High-confidence tagline.",
            summary="High-conf summary.",
            ai_reasoning="high",
            confidence=0.95,
        )),
    ]
    merged, meta = merge_cells(cells, fake_deepseek, deepseek_model="deepseek-v4-flash")
    assert merged.tagline == "High-confidence tagline."
    assert merged.summary == "High-conf summary."
    assert meta["narrative_fallback"] == "max_confidence"
```

- [ ] **Step 2: Run, expect failure**

```bash
.venv/bin/pytest tests/test_aggregate.py -v
```

Expected: new tests fail (no `merge_cells` defined yet).

- [ ] **Step 3: Implement `_merge_narrative` and `merge_cells`**

Append to `experiments/labels/src/lab/aggregate.py`:

```python
NARRATIVE_SYSTEM = (
    "You are merging multiple researchers' narrative descriptions of the "
    "same music label into one coherent output. Use ONLY facts present in "
    "the inputs. Never invent."
)


def _build_narrative_prompt(label_name: str, cells: list[dict]) -> str:
    sections = []
    for idx, cell in enumerate(cells):
        p = cell["response"]["parsed"]
        sections.append(
            f"VENDOR {chr(ord('A') + idx)} ({cell['vendor']['name']}, confidence {p.get('confidence', 0)}):\n"
            f"tagline: {p.get('tagline')}\n"
            f"summary: {p.get('summary')}\n"
            f"ai_reasoning: {p.get('ai_reasoning')}"
        )
    return (
        f'{len(cells)} vendors researched the label "{label_name}". '
        f"Here are their narrative outputs:\n\n"
        + "\n\n".join(sections)
        + "\n\n"
        "Combine these into ONE clean narrative section:\n"
        "- tagline: pick the strongest single sentence from the vendors. Do "
        "NOT invent new facts. If all vendors returned null, return null.\n"
        "- summary: 2-4 sentences using ONLY facts that appear in at least "
        "one vendor's narrative. Resolve contradictions by preferring the "
        "vendor with higher confidence.\n"
        "- ai_reasoning: combine the signals/reasoning into one coherent paragraph.\n"
        "- notes: empty (null) unless vendors disagree on key facts. If "
        "they do, note the disagreement explicitly.\n\n"
        'Output ONLY JSON: {"tagline": "..." | null, "summary": "...", "ai_reasoning": "...", "notes": "..." | null}'
    )


def _highest_confidence_cell(cells: list[dict]) -> dict:
    return max(cells, key=lambda c: c["response"]["parsed"].get("confidence") or 0.0)


def _merge_narrative(
    cells: list[dict],
    deepseek_client: Any,
    deepseek_model: str,
    label_name: str,
) -> tuple[dict, dict]:
    """Call DeepSeek to merge narrative fields. On failure fall back to max-confidence cell.

    Returns (narrative_payload, narrative_meta).
    narrative_payload keys: tagline, summary, ai_reasoning, notes
    narrative_meta keys: narrative_cost_usd, narrative_latency_ms, narrative_fallback?
    """
    started = time.monotonic()
    try:
        resp = deepseek_client.chat.completions.create(
            model=deepseek_model,
            messages=[
                {"role": "system", "content": NARRATIVE_SYSTEM},
                {"role": "user", "content": _build_narrative_prompt(label_name, cells)},
            ],
            response_format={"type": "json_object"},
            temperature=0.1,
        )
        latency = int((time.monotonic() - started) * 1000)
        content = resp.choices[0].message.content or ""
        payload = json.loads(content)
        usage = resp.usage
        input_tokens = getattr(usage, "prompt_tokens", 0) or 0
        output_tokens = getattr(usage, "completion_tokens", 0) or 0
        cost = estimate_cost(deepseek_model, input_tokens, output_tokens)
        narrative = {
            "tagline": payload.get("tagline"),
            "summary": payload.get("summary") or "",
            "ai_reasoning": payload.get("ai_reasoning") or "",
            "notes": payload.get("notes"),
        }
        return narrative, {
            "narrative_cost_usd": cost,
            "narrative_latency_ms": latency,
        }
    except Exception:  # noqa: BLE001 — never raise to caller
        # Fallback: take narrative from highest-confidence cell
        top = _highest_confidence_cell(cells)
        tp = top["response"]["parsed"]
        return (
            {
                "tagline": tp.get("tagline"),
                "summary": tp.get("summary") or "",
                "ai_reasoning": tp.get("ai_reasoning") or "",
                "notes": tp.get("notes"),
            },
            {
                "narrative_cost_usd": 0.0,
                "narrative_latency_ms": int((time.monotonic() - started) * 1000),
                "narrative_fallback": "max_confidence",
            },
        )


def merge_cells(
    cells: list[dict],
    deepseek_client: Any,
    deepseek_model: str = "deepseek-v4-flash",
) -> tuple[LabelInfo, dict]:
    """Merge multiple vendor cells into a single LabelInfo.

    See spec docs/superpowers/specs/2026-05-18-label-enrichment-pipeline-design.md.
    """
    parseable = _filter_parseable(cells)
    if not parseable:
        first = cells[0] if cells else {}
        label_name = first.get("fixture", {}).get("label_name", "unknown")
        merged = LabelInfo(
            label_name=label_name,
            summary="All vendor sources failed.",
            ai_reasoning="n/a",
            confidence=0.0,
        )
        return merged, {
            "source_cells": [],
            "field_provenance": {},
            "narrative_cost_usd": 0.0,
            "narrative_latency_ms": 0,
            "all_failed": True,
        }

    if len(parseable) == 1:
        only = parseable[0]
        parsed = only["response"]["parsed"]
        merged = LabelInfo.model_validate(parsed)
        return merged, {
            "source_cells": [
                {
                    "vendor": only["vendor"]["name"],
                    "model": only["vendor"]["model"],
                    "confidence": parsed.get("confidence"),
                }
            ],
            "field_provenance": {f: f"single source({only['vendor']['name']})" for f in parsed},
            "narrative_cost_usd": 0.0,
            "narrative_latency_ms": 0,
            "single_source": True,
        }

    det_merged, det_prov = _merge_deterministic(parseable)
    narrative, narr_meta = _merge_narrative(
        parseable, deepseek_client, deepseek_model, det_merged.get("label_name", "unknown")
    )

    final = {**det_merged, **narrative}
    # narrative provenance
    for nf in NARRATIVE_FIELDS:
        det_prov[nf] = "deepseek narrative" if "narrative_fallback" not in narr_meta else "max_confidence fallback"

    try:
        merged_label = LabelInfo.model_validate(final)
    except ValidationError:
        # Last-resort: pad required fields if narrative came back empty.
        final.setdefault("summary", "")
        final.setdefault("ai_reasoning", "")
        merged_label = LabelInfo.model_validate(final)

    return merged_label, {
        "source_cells": [
            {
                "vendor": c["vendor"]["name"],
                "model": c["vendor"]["model"],
                "confidence": c["response"]["parsed"].get("confidence"),
            }
            for c in parseable
        ],
        "field_provenance": det_prov,
        **narr_meta,
    }
```

- [ ] **Step 4: Run tests, expect pass**

```bash
.venv/bin/pytest tests/test_aggregate.py -v
```

Expected: all aggregate tests pass.

- [ ] **Step 5: Commit**

```bash
git add experiments/labels/src/lab/aggregate.py experiments/labels/tests/test_aggregate.py
git commit -m "feat(experiments): merge_cells with DeepSeek narrative merge"
```

---

## Task 5: aggregate.py — edge cases (single source, all failed)

The previous task already added these branches inside `merge_cells`. This task adds the tests that exercise them and verifies the behavior end-to-end.

**Files:**
- Modify: `experiments/labels/tests/test_aggregate.py`

- [ ] **Step 1: Add edge-case tests**

Append to `experiments/labels/tests/test_aggregate.py`:

```python
def test_merge_cells_single_source_skips_deepseek():
    fake_deepseek = MagicMock()
    cells = [_cell("a", "ma", parsed=_parsed(summary="Single-source summary.", tagline="Single."))]
    merged, meta = merge_cells(cells, fake_deepseek)
    assert merged.summary == "Single-source summary."
    assert merged.tagline == "Single."
    assert meta["single_source"] is True
    assert meta["narrative_cost_usd"] == 0.0
    fake_deepseek.chat.completions.create.assert_not_called()


def test_merge_cells_all_failed_returns_placeholder():
    fake_deepseek = MagicMock()
    cells = [
        _cell("a", "ma", parsed=None, error="boom"),
        _cell("b", "mb", parsed=None),
    ]
    merged, meta = merge_cells(cells, fake_deepseek)
    assert merged.summary == "All vendor sources failed."
    assert merged.confidence == 0.0
    assert meta["all_failed"] is True
    fake_deepseek.chat.completions.create.assert_not_called()


def test_merge_cells_handles_malformed_deepseek_json():
    fake_deepseek = MagicMock()
    fake_deepseek.chat.completions.create.return_value = _mock_deepseek_response("not json")
    cells = [
        _cell("a", "ma", parsed=_parsed(tagline="A.", summary="A.", confidence=0.8)),
        _cell("b", "mb", parsed=_parsed(tagline="B.", summary="B.", confidence=0.95)),
    ]
    merged, meta = merge_cells(cells, fake_deepseek)
    assert meta["narrative_fallback"] == "max_confidence"
    assert merged.tagline == "B."  # higher-confidence cell wins
```

- [ ] **Step 2: Run, expect pass**

```bash
.venv/bin/pytest tests/test_aggregate.py -v
```

Expected: all aggregate tests still green, 3 new ones added.

- [ ] **Step 3: Commit**

```bash
git add experiments/labels/tests/test_aggregate.py
git commit -m "test(experiments): aggregate edge cases (single source, all failed, bad JSON)"
```

---

## Task 6: `lab aggregate` CLI subcommand

**Files:**
- Modify: `experiments/labels/src/lab/cli.py` (add `aggregate` command + helpers)
- Modify: `experiments/labels/tests/test_cli.py` (add aggregate test)

- [ ] **Step 1: Write the failing test**

Append to `experiments/labels/tests/test_cli.py`:

```python
def test_aggregate_writes_merged_and_updates_manifest(tmp_path, monkeypatch):
    """End-to-end: lab aggregate reads cells, calls DeepSeek (stubbed),
    writes merged/<file>, updates manifest, regenerates report."""
    import json as _json
    from types import SimpleNamespace
    from unittest.mock import MagicMock
    import lab.cli as cli_mod

    monkeypatch.setattr(cli_mod, "OUTPUTS_ROOT", tmp_path / "outputs")
    monkeypatch.setattr(cli_mod, "REPORTS_ROOT", tmp_path / "reports")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "fake-key")

    # Stub the DeepSeek client builder
    def fake_build(settings):
        client = MagicMock()
        client.chat.completions.create.return_value = SimpleNamespace(
            choices=[SimpleNamespace(
                message=SimpleNamespace(content=_json.dumps({
                    "tagline": "Test tagline.",
                    "summary": "Merged summary.",
                    "ai_reasoning": "Merged reasoning.",
                    "notes": None,
                })),
                finish_reason="stop",
            )],
            usage=SimpleNamespace(prompt_tokens=500, completion_tokens=200, total_tokens=700),
            model="deepseek-v4-flash",
        )
        return client, "deepseek-v4-flash"

    monkeypatch.setattr(cli_mod, "build_deepseek_client", fake_build)

    # Set up a fake run dir with 2 cell JSONs and a manifest
    run_id = "20260518-200000-test"
    run_dir = tmp_path / "outputs" / run_id
    run_dir.mkdir(parents=True)
    manifest = {
        "run_id": run_id,
        "started_at": "2026-05-18T20:00:00+00:00",
        "finished_at": "2026-05-18T20:01:00+00:00",
        "prompts": [{"slug": "label_v3_app_fields", "version": "v1"}],
        "vendors": [
            {"name": "gemini", "model": "gemini-2.5-flash"},
            {"name": "tavily_deepseek", "model": "deepseek-v4-flash"},
        ],
        "fixtures": ["drumcode"],
        "totals": {"cells": 2, "ok": 2, "error": 0, "cost_usd": 0.01},
    }
    (run_dir / "manifest.json").write_text(_json.dumps(manifest), encoding="utf-8")

    base_parsed = {
        "label_name": "Drumcode",
        "aliases": [], "parent_label": None, "sublabels": [],
        "country": "Sweden", "founded_year": 1996, "status": "active",
        "logo_url": None, "tagline": "Swedish techno.",
        "catalog_size_estimate": None, "roster_size_estimate": None,
        "releases_last_12_months": None, "last_release_date": None,
        "activity": "unknown",
        "website": None, "bandcamp_url": None, "residentadvisor_url": None,
        "discogs_url": None, "beatport_url": None, "soundcloud_url": None,
        "instagram_url": None, "twitter_url": None,
        "notable_artists": ["Adam Beyer"], "primary_styles": [],
        "distribution": None, "ai_content": "none_detected",
        "ai_signals": [], "ai_reasoning": "n/a",
        "summary": "Swedish techno label.", "confidence": 0.9,
        "sources": [], "notes": None,
    }
    for vendor, model in [("gemini", "gemini-2.5-flash"), ("tavily_deepseek", "deepseek-v4-flash")]:
        cell_path = run_dir / f"label_v3_app_fields__{vendor}__drumcode.json"
        cell_path.write_text(_json.dumps({
            "run_id": run_id,
            "prompt": {"slug": "label_v3_app_fields", "version": "v1"},
            "vendor": {"name": vendor, "model": model},
            "fixture": {"id": "drumcode", "label_name": "Drumcode", "style": "techno", "release_name": None},
            "rendered_user_prompt": "...",
            "response": {
                "parsed": base_parsed,
                "citations": [],
                "usage": {"input_tokens": 100, "output_tokens": 200, "cost_usd": 0.001},
                "latency_ms": 1500,
                "raw": {},
            },
            "error": None,
        }), encoding="utf-8")

    result = runner.invoke(app, ["aggregate", run_id])
    assert result.exit_code == 0, result.stdout

    # Verify merged JSON written
    merged_files = list((run_dir / "merged").glob("*.json"))
    assert len(merged_files) == 1
    merged_payload = _json.loads(merged_files[0].read_text())
    assert merged_payload["merged"]["tagline"] == "Test tagline."
    assert merged_payload["merged"]["founded_year"] == 1996
    assert len(merged_payload["source_cells"]) == 2

    # Manifest updated
    new_manifest = _json.loads((run_dir / "manifest.json").read_text())
    assert "aggregates" in new_manifest
    assert new_manifest["aggregates"]["groups"] == 1
    assert new_manifest["aggregates"]["total_aggregate_cost_usd"] >= 0
```

- [ ] **Step 2: Run, expect failure**

```bash
.venv/bin/pytest tests/test_cli.py::test_aggregate_writes_merged_and_updates_manifest -v
```

Expected: failure — `aggregate` command not defined.

- [ ] **Step 3: Implement the `aggregate` command**

In `experiments/labels/src/lab/cli.py`, add new imports near the top:

```python
import json
from datetime import datetime, timezone
from .aggregate import merge_cells
```

Add a helper for building the DeepSeek client (single source of truth, easy to monkey-patch in tests):

```python
def build_deepseek_client(settings: Settings) -> tuple[Any, str]:
    """Build a DeepSeek-pointed OpenAI client + return chosen model."""
    if not settings.deepseek_api_key:
        typer.echo("DEEPSEEK_API_KEY required for aggregation", err=True)
        raise typer.Exit(2)
    from openai import OpenAI
    client = OpenAI(
        api_key=settings.deepseek_api_key,
        base_url="https://api.deepseek.com",
        timeout=settings.request_timeout,
    )
    return client, settings.deepseek_model
```

Add the `aggregate` command (place it next to existing `run` and `report` commands):

```python
@app.command()
def aggregate(
    run_id: str,
    prompts: str = typer.Option(None, "--prompts"),
    vendors: str = typer.Option(None, "--vendors"),
    fixtures: str = typer.Option(None, "--fixtures"),
) -> None:
    """Merge per-vendor cells in a run into consensus LabelInfo per fixture."""
    run_dir = OUTPUTS_ROOT / run_id
    if not run_dir.exists():
        typer.echo(f"no such run: {run_id}", err=True)
        raise typer.Exit(2)

    settings = Settings()
    client, model = build_deepseek_client(settings)

    # Load cells
    cells: list[dict] = []
    for path in sorted(run_dir.glob("*.json")):
        if path.name == "manifest.json":
            continue
        cells.append(json.loads(path.read_text(encoding="utf-8")))

    # Filter
    sel_prompts = _parse_csv(prompts)
    sel_vendors = _parse_csv(vendors)
    sel_fixtures = _parse_csv(fixtures)
    if sel_prompts:
        cells = [c for c in cells if c["prompt"]["slug"] in sel_prompts]
    if sel_vendors:
        cells = [c for c in cells if c["vendor"]["name"] in sel_vendors]
    if sel_fixtures:
        cells = [c for c in cells if c["fixture"]["id"] in sel_fixtures]

    if not cells:
        typer.echo("no cells match filters", err=True)
        raise typer.Exit(2)

    # Group by (prompt, fixture)
    from collections import defaultdict as _dd
    groups: dict[tuple[str, str], list[dict]] = _dd(list)
    for c in cells:
        groups[(c["prompt"]["slug"], c["fixture"]["id"])].append(c)

    merged_dir = run_dir / "merged"
    merged_dir.mkdir(exist_ok=True)
    total_cost = 0.0

    for (prompt_slug, fixture_id), group in groups.items():
        merged_label, meta = merge_cells(group, client, model)
        first = group[0]
        payload = {
            "run_id": run_id,
            "merged_at": datetime.now(timezone.utc).isoformat(),
            "prompt": first["prompt"],
            "fixture": first["fixture"],
            "source_cells": [
                {
                    "vendor": c["vendor"]["name"],
                    "model": c["vendor"]["model"],
                    "file": f"{prompt_slug}__{c['vendor']['name']}__{fixture_id}.json",
                    "confidence": c["response"]["parsed"].get("confidence") if c["response"]["parsed"] else None,
                }
                for c in group
            ],
            "merged": merged_label.model_dump(),
            "merge_meta": meta,
            "aggregate_cost_usd": meta.get("narrative_cost_usd", 0.0),
        }
        out_path = merged_dir / f"{prompt_slug}__{fixture_id}.json"
        out_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
        total_cost += meta.get("narrative_cost_usd", 0.0)
        typer.echo(f"merged {prompt_slug} × {fixture_id} ({len(group)} sources)")

    # Update manifest
    manifest_path = run_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["aggregates"] = {
        "merged_at": datetime.now(timezone.utc).isoformat(),
        "groups": len(groups),
        "filters_applied": {"vendors": sel_vendors, "prompts": sel_prompts, "fixtures": sel_fixtures},
        "total_aggregate_cost_usd": round(total_cost, 6),
    }
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")

    # Regenerate report
    out_path = build_report(run_dir, REPORTS_ROOT)
    typer.echo(f"groups: {len(groups)}, cost: ${total_cost:.6f}")
    typer.echo(f"report: {out_path}")
```

The `Any` type may need import — add `from typing import Any` at the top if not already there. The `Settings` import already exists in this file.

- [ ] **Step 4: Run test, expect pass**

```bash
.venv/bin/pytest tests/test_cli.py -v
```

Expected: all CLI tests pass.

- [ ] **Step 5: Commit**

```bash
git add experiments/labels/src/lab/cli.py experiments/labels/tests/test_cli.py
git commit -m "feat(experiments): add lab aggregate CLI command"
```

---

## Task 7: report.py — render `## Aggregated (consensus)` section

**Files:**
- Modify: `experiments/labels/src/lab/report.py` (load merged JSONs and render section)
- Modify: `experiments/labels/tests/test_report.py` (add aggregated-section test)

- [ ] **Step 1: Write the failing test**

Append to `experiments/labels/tests/test_report.py`:

```python
def _write_merged(run_dir, prompt: str, fixture_id: str, merged_payload: dict, source_cells: list[dict], meta: dict) -> None:
    """Write a merged/<file>.json record to a run dir."""
    import json as _json
    merged_dir = run_dir / "merged"
    merged_dir.mkdir(exist_ok=True)
    (merged_dir / f"{prompt}__{fixture_id}.json").write_text(_json.dumps({
        "run_id": run_dir.name,
        "merged_at": "2026-05-18T20:00:00+00:00",
        "prompt": {"slug": prompt, "version": "v1"},
        "fixture": {
            "id": fixture_id, "label_name": merged_payload.get("label_name", fixture_id),
            "style": "techno", "release_name": None,
            "ground_truth": {"founded_year": 1996, "country": "Sweden", "parent_label": None, "ai_content_expected": "none_detected"} if fixture_id == "drumcode" else None,
        },
        "source_cells": source_cells,
        "merged": merged_payload,
        "merge_meta": meta,
        "aggregate_cost_usd": meta.get("narrative_cost_usd", 0.0),
    }, indent=2, ensure_ascii=False), encoding="utf-8")


def test_build_report_renders_aggregated_section(tmp_path):
    from lab.report import build_report

    run_dir = tmp_path / "outputs" / "20260518-200000-test"
    reports_dir = tmp_path / "reports"

    _write_cell(run_dir, "label_v3_app_fields", "gemini", "drumcode", {
        "label_name": "Drumcode", "founded_year": 1996, "country": "Sweden",
        "ai_content": "none_detected", "ai_reasoning": "—",
        "summary": "Techno label.", "confidence": 0.9, "notable_artists": ["Adam Beyer"]
    })
    _write_manifest(run_dir, ok=1, err=0, cost=0.001)

    _write_merged(run_dir, "label_v3_app_fields", "drumcode",
        merged_payload={
            "label_name": "Drumcode",
            "tagline": "Swedish techno powerhouse since 1996.",
            "founded_year": 1996,
            "country": "Sweden",
            "ai_content": "none_detected",
            "confidence": 0.95,
            "notable_artists": ["Adam Beyer", "Amelie Lens"],
            "logo_url": "https://example.com/drumcode.png",
            "instagram_url": "https://www.instagram.com/drumcode_se",
            "summary": "Merged summary.",
            "ai_reasoning": "—",
        },
        source_cells=[
            {"vendor": "gemini", "model": "gemini-2.5-flash", "confidence": 0.9},
            {"vendor": "tavily_deepseek", "model": "deepseek-v4-flash", "confidence": 1.0},
        ],
        meta={
            "field_provenance": {
                "founded_year": "median:1996",
                "country": "majority(2/2)",
                "tagline": "deepseek narrative",
                "logo_url": "highest confidence(tavily_deepseek)",
            },
            "narrative_cost_usd": 0.0004,
            "narrative_latency_ms": 4200,
        },
    )

    out_path = build_report(run_dir, reports_dir)
    text = out_path.read_text(encoding="utf-8")

    assert "## Aggregated (consensus)" in text
    assert "drumcode — label_v3_app_fields" in text
    assert "Swedish techno powerhouse since 1996." in text
    assert "median:1996" in text
    assert "highest confidence(tavily_deepseek)" in text
    assert "1996 ✓" in text  # ground-truth match still annotated
    assert "Sweden ✓" in text


def test_build_report_no_aggregated_section_when_merged_dir_absent(tmp_path):
    from lab.report import build_report

    run_dir = tmp_path / "outputs" / "20260518-201000-test"
    reports_dir = tmp_path / "reports"
    _write_cell(run_dir, "label_v1_baseline", "anthropic", "drumcode", {
        "label_name": "Drumcode", "founded_year": 1996, "country": "Sweden",
        "ai_content": "none_detected", "ai_reasoning": "—",
        "summary": "x", "confidence": 0.9, "notable_artists": [],
    })
    _write_manifest(run_dir, ok=1, err=0, cost=0.001)

    text = build_report(run_dir, reports_dir).read_text()
    assert "## Aggregated" not in text
```

- [ ] **Step 2: Run, expect failure**

```bash
.venv/bin/pytest tests/test_report.py -v
```

Expected: both new tests fail — section doesn't exist.

- [ ] **Step 3: Implement the aggregated section**

In `experiments/labels/src/lab/report.py`, add `AGGREGATED_TABLE_FIELDS` constant near the existing `TABLE_FIELDS`:

```python
AGGREGATED_TABLE_FIELDS: list[str] = [
    "founded_year",
    "country",
    "parent_label",
    "logo_url",
    "instagram_url",
    "twitter_url",
    "catalog_size_estimate",
    "releases_last_12_months",
    "activity",
    "ai_content",
    "confidence",
    "tagline",
    "notable_artists",
]
```

Add a new helper `_aggregated_section`:

```python
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

        # Ground-truth annotation, same logic as fixture section
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

        rows.append(f"| {field} | {rendered} | {prov.get(field, '—')} |")

    rows.append("")
    sources_line = ", ".join(f"{s['vendor']}/{s['model']}" for s in sources)
    rows.append(f"**Sources:** {sources_line}")
    rows.append("")
    return rows
```

Hook it into `build_report` — after `_summary_section(...)` and before the loop over fixtures:

```python
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
    lines.extend(_aggregated_section(run_dir))   # NEW
    for fixture_id in sorted(cells_by_fixture):
        lines.extend(_fixture_section(fixture_id, cells_by_fixture[fixture_id]))
    lines.extend(_details_section(cells))

    out_path = reports_dir / f"{run_id}.md"
    out_path.write_text("\n".join(lines), encoding="utf-8")
    return out_path
```

- [ ] **Step 4: Run tests, expect pass**

```bash
.venv/bin/pytest tests/test_report.py -v
```

Expected: both new tests pass; existing tests still pass.

- [ ] **Step 5: Run full suite**

```bash
.venv/bin/pytest -v
```

Expected: 54 (from Task 2) + 7 aggregate tests + 1 new CLI test + 2 new report tests = **64 passed** (approximate — slight count differences are OK).

- [ ] **Step 6: Commit**

```bash
git add experiments/labels/src/lab/report.py experiments/labels/tests/test_report.py
git commit -m "feat(experiments): render Aggregated section in report"
```

---

## Task 8: README — document the recommended pipeline

**Files:**
- Modify: `experiments/labels/README.md`

- [ ] **Step 1: Read the existing README**

Open `experiments/labels/README.md` and locate the `## Run` section.

- [ ] **Step 2: Add the pipeline section after `## Run`**

Insert this new section between `## Run` and `## Tests`:

````markdown
## Recommended pipeline

For an end-to-end experiment producing a consensus label record:

```bash
# 1. Run two complementary vendors with the app-targeted prompt
.venv/bin/lab run --prompts label_v3_app_fields --vendors tavily_deepseek,gemini

# 2. Merge per-fixture cells into one consensus LabelInfo
.venv/bin/lab aggregate <run_id>

# 3. Inspect
open reports/<run_id>.md
```

Approximate cost for 8 fixtures: $0.007 (Tavily+DeepSeek) + $0.04 (Gemini) +
$0.003 (narrative merge) = **~$0.05** per full run.

When a merged cell shows `confidence < 0.5` or `ai_content=unknown`, rerun
that specific fixture against a higher-quality vendor and re-aggregate:

```bash
.venv/bin/lab run --fixtures <id> --vendors anthropic --prompts label_v3_app_fields
.venv/bin/lab aggregate <newer_run_id>
```

Cheap baseline + on-demand expert arbiter pattern.
````

- [ ] **Step 3: Verify the README renders cleanly**

Skim the file. Confirm code fences are balanced and Markdown headers cascade correctly. No automated check.

- [ ] **Step 4: Commit**

```bash
git add experiments/labels/README.md
git commit -m "docs(experiments): document consensus pipeline in README"
```

---

## Final verification

- [ ] **Step 1: Run the whole suite from the sandbox**

```bash
cd experiments/labels
.venv/bin/pytest -v
```

Expected: every test green.

- [ ] **Step 2: Smoke the CLI without API calls**

```bash
.venv/bin/lab list prompts
```

Expected output includes:
```
label_v1_baseline/v1 — Port of the production prompt onto the new schema.
label_v2_facts/v1 — Facts-discipline: numbers require sources, no guessing.
label_v3_app_fields/v1 — Facts-discipline plus logo, socials, and tagline for app integration.
```

- [ ] **Step 3: Confirm production untouched**

```bash
git diff --stat main -- src/ infra/ alembic/
```

Expected: empty output.

---

## Self-Review Checklist (already applied)

- Every spec section maps to a task: schema (Task 1), prompt (Task 2), `merge_cells` core (Tasks 3, 4, 5), CLI (Task 6), report (Task 7), README (Task 8).
- No `TBD` / `TODO` / `implement later` placeholders.
- Type consistency: `merge_cells` signature `(cells, deepseek_client, deepseek_model) -> (LabelInfo, dict)` is identical in Task 4 implementation and Task 6 CLI invocation. The internal `_filter_parseable`, `_merge_deterministic`, `_merge_narrative` signatures are consistent across their definitions and test calls.
- Provenance strings (`"median:..."`, `"majority(...)"`, `"highest confidence(...)"`) are produced by `_merge_deterministic` (Task 3) and asserted in tests in Tasks 3 + 7.
- `LabelInfo` model has the 4 new fields (Task 1) — every later task that builds parsed payloads uses them correctly.
- Out-of-scope items from the spec (consensus vendor adapter, image fetching, cross-vendor scoring) appear in NO task.
- Tests use mocks/stubs for DeepSeek throughout — no live API in the suite.

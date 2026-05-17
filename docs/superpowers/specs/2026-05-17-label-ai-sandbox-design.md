# Label AI Sandbox — Design Spec

**Date:** 2026-05-17
**Status:** Draft
**Scope:** Local-only experimentation environment for comparing AI vendors and prompt formulations on the "label info enrichment" task. Production code under `src/collector/` is not modified by this work.

## 1. Motivation

The current production label-enrichment pipeline (`src/collector/search/`, `src/collector/providers/perplexity/label.py`) uses a single vendor (Perplexity `sonar`) with a single prompt (`label_info/v1`) and was built ad hoc. Pain points:

- **Coarse enums** (`size`, `age`, `ai_content` as `unknown/micro/small/...`) discard quantitative signal that the model could provide.
- **Missing fields** — no sublabels, parent label, distributor, Bandcamp/RA/Discogs links, last release date, activity level.
- **Weak AI-content detector** — single string, no structured signals, no source attribution.

We want a controlled environment to:

1. Compare three vendors (Anthropic Claude, xAI Grok, Perplexity sonar) on the same inputs.
2. Iterate prompt formulations against a stable golden set.
3. Produce a `(prompt, vendor, model)` recipe that can later be ported back into the production path. **Porting is a separate effort, not part of this spec.**

## 2. Goal

Build a self-contained local sandbox at `experiments/labels/` that runs a matrix of `prompts × vendors × fixtures`, persists raw responses, and emits a side-by-side markdown report.

**Non-goals:**

- Changing production schema (`LabelSearchResult`) or production code.
- AWS deployment, Lambda packaging, or CI integration.
- LLM-as-judge evaluation (deliberately deferred to keep dependencies and cost predictable).
- A web UI or HTML dashboard.
- Multi-user / shared-state operation.

## 3. Directory Layout

```
experiments/labels/
  README.md
  pyproject.toml          # isolated deps, own venv
  .env.example            # API key template
  .gitignore              # outputs/, reports/, .env, .venv/
  fixtures.yaml           # golden set
  src/lab/
    __init__.py
    cli.py                # `python -m lab` entrypoint
    config.py             # env loader (pydantic-settings)
    runner.py             # matrix orchestration
    report.py             # markdown generator
    schemas.py            # LabelInfo, AISignal, enums
    prompts/
      __init__.py         # registry
      base.py             # PromptConfig dataclass
      label_v1_baseline.py
      label_v2_facts.py
      label_v3_ai_focus.py
    vendors/
      __init__.py         # registry
      base.py             # VendorAdapter protocol, VendorResponse
      anthropic_claude.py
      xai_grok.py
      perplexity_sonar.py
      pricing.py          # hardcoded per-model $/Mtok table
  outputs/<run_id>/       # gitignored: raw JSON cells + manifest.json
  reports/<run_id>.md     # gitignored: human-readable report
```

The sandbox is intentionally **not** importable from `src/collector/`. The two trees share no Python imports. Lambda packaging (`scripts/package_lambda.sh`) does not touch `experiments/`.

Dependencies (`pyproject.toml`):

- `anthropic` — Claude SDK
- `openai` — used against xAI base URL (Grok is OpenAI-compatible)
- `httpx` — Perplexity client
- `pydantic>=2`, `pydantic-settings`
- `typer` — CLI framework
- `PyYAML` — fixtures parsing
- `python-dotenv`

## 4. Schemas

`schemas.py` defines the common output model. Promotion of any of these fields into the production `LabelSearchResult` is a separate decision after experiments conclude.

```python
class ActivityLevel(str, Enum):
    UNKNOWN = "unknown"
    DORMANT = "dormant"           # >2 years without releases
    LOW = "low"                   # <6 releases in last 12 months
    STEADY = "steady"             # 6-24 / 12 months
    HIGH = "high"                 # 25-60 / 12 months
    FIRE_HOSE = "fire_hose"       # >60 / 12 months — common AI signal

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
    # identity
    label_name: str
    aliases: list[str] = []
    parent_label: str | None = None
    sublabels: list[str] = []
    country: str | None = None
    founded_year: int | None = None
    status: Literal["active", "inactive", "unknown"] = "unknown"

    # size — numbers, not enums
    catalog_size_estimate: int | None = None
    roster_size_estimate: int | None = None
    releases_last_12_months: int | None = None
    last_release_date: str | None = None      # ISO date or null
    activity: ActivityLevel = ActivityLevel.UNKNOWN

    # channels
    website: str | None = None
    bandcamp_url: str | None = None
    residentadvisor_url: str | None = None
    discogs_url: str | None = None
    beatport_url: str | None = None
    soundcloud_url: str | None = None

    # roster / style
    notable_artists: list[str] = []           # prompt asks for top 5; schema does not enforce
    primary_styles: list[str] = []
    distribution: str | None = None

    # AI section
    ai_content: AIContentStatus = AIContentStatus.UNKNOWN
    ai_signals: list[AISignal] = []
    ai_reasoning: str

    # meta
    summary: str
    confidence: float = Field(ge=0, le=1)
    sources: list[str] = []
    notes: str | None = None
```

A prompt MAY define its own schema by subclassing `LabelInfo` (for example `label_v3_ai_focus` could add extra AI fields). The runner serializes whatever Pydantic model the prompt declares. The report generator inspects each cell independently: fields not present in a given cell's payload are rendered as `—` in the side-by-side table; prompt-specific fields appear only in the per-cell `<details>` section.

## 5. Prompt Contract

```python
# prompts/base.py
@dataclass(frozen=True)
class PromptConfig:
    slug: str                          # e.g. "label_v2_facts"
    version: str                       # e.g. "v1"
    description: str                   # one-liner for report.md
    system: str
    user_template: str                 # uses {label_name}, {style}, {release_block}
    schema: type[BaseModel]
    vendor_overrides: dict[str, str] = field(default_factory=dict)
                                       # vendor name → model id override
```

The runner renders `user_template` with `label_name`, `style` always; `release_block` is `""` when the fixture has no `release_name`, otherwise `"\nRecent release: {release_name}"`. This keeps a single template across the two input forms without conditionals in prompt code.

`prompts/__init__.py` exposes `PROMPTS: dict[str, PromptConfig]` populated by importing the prompt modules.

### Starter prompts (three)

1. **`label_v1_baseline/v1`** — port of the current production prompt onto the new schema. Acts as control. Same wording, just remaps fields.
2. **`label_v2_facts/v1`** — facts-discipline prompt: every numeric field must be backed by a source URL or left null; `activity` derived from `releases_last_12_months`; ambiguity in `notes`. Full text in module docstring.
3. **`label_v3_ai_focus/v1`** — `label_v2_facts` plus a structured AI-assessment section (volume / generic names / press credits / cover art / tool credits → populate `ai_signals[]` with `kind`, `description`, `source_url`).

The comparison axis is: baseline vs. facts-discipline vs. facts + AI-discipline.

## 6. Vendor Adapter Contract

```python
# vendors/base.py
class VendorAdapter(Protocol):
    name: str                       # "anthropic" | "xai" | "perplexity"
    default_model: str
    supports_web_search: bool

    def run(
        self,
        system: str,
        user: str,
        schema: type[BaseModel],
        model: str | None = None,
    ) -> VendorResponse: ...

@dataclass
class VendorResponse:
    parsed: BaseModel | None
    raw: dict
    citations: list[str]
    usage: dict                     # {"input_tokens": int, "output_tokens": int, "cost_usd": float}
    latency_ms: int
    model: str
    error: str | None = None
```

All vendors use their native web-search capability — without it, niche label coverage collapses.

- **Anthropic Claude** (`anthropic_claude.py`): `anthropic` SDK; `tools=[{"type": "web_search_20250305", "name": "web_search"}]`; structured output via a tool whose `input_schema` is the prompt's Pydantic schema. Default model `claude-sonnet-4-6`.
- **xAI Grok** (`xai_grok.py`): `openai` SDK pointed at `https://api.x.ai/v1`; Live Search via `extra_body={"search_parameters": {"mode": "on"}}`; structured output via `response_format={"type": "json_schema", "json_schema": {...}}`. Default model `grok-4`.
- **Perplexity sonar** (`perplexity_sonar.py`): port of `src/collector/search/perplexity_client.py` replacing `urllib` with `httpx`. Default model `sonar`.

Adapter responsibilities:

- Catch all exceptions; populate `error` and return; never raise to runner.
- Mask `Authorization` headers in any debug print of `raw`.
- Compute `cost_usd` from usage and the pricing table (`vendors/pricing.py`). Pricing table is updated manually; outdated values are tolerable (cost is informational, not gating).
- Retry once on HTTP 429 / 5xx with exponential backoff (start 2s).

## 7. Fixtures

```yaml
# experiments/labels/fixtures.yaml
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

  - id: obscure-niche-1
    label_name: Wisdom Teeth
    style: bass / UK garage
    release_name: K-LONE - Cape Cira
    ground_truth: null

  - id: synthetic-ai-trap
    label_name: NeuroBeats AI
    style: lofi
    release_name: null
    ground_truth:
      ai_content_expected: confirmed
```

Loader: a `FixturesFile` pydantic model → `list[Fixture]`. `id` is required and unique; `release_name` and `ground_truth` are optional. `ground_truth` is consumed only by the report — the runner does not validate model output against it.

Starter set: 10–15 fixtures mixing 4–5 known mid-to-large labels (truth filled in by hand), 3–4 niche labels (no truth — vendor-vs-vendor comparison only), 2–3 suspected AI labels, 1–2 disambiguation traps (multiple labels sharing a name).

## 8. Runner & CLI

```
python -m lab run                                  # full matrix
python -m lab run --prompts label_v2_facts,label_v3_ai_focus
python -m lab run --vendors anthropic,grok
python -m lab run --fixtures anjunadeep,drumcode
python -m lab run --prompts label_v2_facts --vendors grok --fixtures drumcode
python -m lab list {prompts,vendors,fixtures}     # one subject at a time
python -m lab report <run_id>                      # regenerate report only
```

Run flow:

1. Generate `run_id = YYYYMMDD-HHMMSS-<short-uuid>`.
2. Build the Cartesian product `prompts × vendors × fixtures` after applying filters.
3. Execute in parallel via `concurrent.futures.ThreadPoolExecutor(max_workers=N)`, where `N = LAB_CONCURRENCY` (default 4) or `--concurrency`.
4. For each cell: render `user_template`, call adapter, write `outputs/<run_id>/<prompt>__<vendor>__<fixture>.json`.
5. Write `outputs/<run_id>/manifest.json` once all cells finish.
6. Invoke `report.py`.
7. Stdout progress: `[3/45] label_v2_facts × grok × drumcode ... ok (1820ms, $0.0042)`.

Vendor missing an API key is automatically dropped from the matrix with a warning, so the lab is usable with even one key.

## 9. Output Artifacts

**Per-cell JSON** (`outputs/<run_id>/<prompt>__<vendor>__<fixture>.json`):

```json
{
  "run_id": "20260517-143022-a3f1",
  "prompt": {"slug": "label_v2_facts", "version": "v1"},
  "vendor": {"name": "anthropic", "model": "claude-sonnet-4-6"},
  "fixture": {"id": "drumcode", "label_name": "Drumcode", "style": "techno", "release_name": null},
  "rendered_user_prompt": "...",
  "response": {
    "parsed": { ... full schema dump ... },
    "citations": ["https://..."],
    "usage": {"input_tokens": 412, "output_tokens": 380, "cost_usd": 0.0042},
    "latency_ms": 1820,
    "raw": { ... }
  },
  "error": null
}
```

**Manifest** (`outputs/<run_id>/manifest.json`):

```json
{
  "run_id": "20260517-143022-a3f1",
  "started_at": "2026-05-17T14:30:22Z",
  "finished_at": "2026-05-17T14:32:48Z",
  "prompts":  [{"slug": "label_v2_facts",  "version": "v1"}],
  "vendors":  [{"name": "anthropic", "model": "claude-sonnet-4-6"}],
  "fixtures": ["anjunadeep", "drumcode"],
  "totals":   {"cells": 45, "ok": 43, "error": 2, "cost_usd": 0.84}
}
```

**Report** (`reports/<run_id>.md`):

1. **Summary** — overall cells × ok / error counts, total cost, mean latency per vendor.
2. **Per-fixture side-by-side** — a markdown table per fixture with columns `prompt × vendor`, rows being key fields (`founded_year`, `country`, `releases_last_12_months`, `activity`, `ai_content`, …). Cells with `ground_truth` get a `✓` / `✗` annotation.
3. **Full responses** — collapsible `<details>` blocks containing `summary`, `notable_artists`, and `ai_reasoning` per cell.

The report is built by reading the cell JSONs and grouping them. No LLM is invoked during report generation.

## 10. Secrets & Config

`.env` (gitignored), `.env.example` checked in:

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

Loaded via `python-dotenv` → `pydantic-settings.BaseSettings`. The lab does not use AWS Secrets Manager — this is a single-developer local environment. The `bp_token` rule from `CLAUDE.md` is unrelated; it concerns the production Spotify auth flow and never appears in this code path.

## 11. Out of Scope

These are deliberately excluded from this spec:

- Modifying `src/collector/search/`, `LabelSearchResult`, alembic migrations, or production prompts.
- LLM-as-judge evaluation, cross-vendor consensus voting, automated scoring.
- Web UI, HTML dashboard, hosted reports.
- CI integration or GitHub Actions running the matrix.
- Caching API responses across runs.
- Cost-budget enforcement that aborts a run mid-flight (cost is reported, not gated).

## 12. Open Questions

None for this spec. Anything not specified above is an implementation decision for the plan that follows.

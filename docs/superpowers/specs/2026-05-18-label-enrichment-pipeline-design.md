# Label Enrichment Pipeline — Design Spec

**Date:** 2026-05-18
**Status:** Draft
**Scope:** Extend the local label-AI sandbox at `experiments/labels/` with three additions: (1) app-targeted output fields on `LabelInfo` (logo, social links, tagline), (2) a new prompt `label_v3_app_fields` that asks for them, (3) a multi-vendor consensus aggregator that merges per-vendor outputs into a single `LabelInfo`. Production code under `src/collector/` remains untouched.

Builds on the existing sandbox spec at `docs/superpowers/specs/2026-05-17-label-ai-sandbox-design.md`.

## 1. Motivation

Live experiments produced strong per-vendor results, but each vendor has gaps:

- **Tavily + DeepSeek**: cheapest, honest about missing data, but conservative on inference and weaker at narrative writing.
- **Gemini 2.5 / 3 Flash**: good coverage with Google grounding, but Gemini 3 hallucinates with high confidence on niche labels.
- **Grok / Claude Sonnet**: best quality but expensive (~$0.13 / cell).

Single-vendor runs miss the upside of combining vendors. Manual eyeballing of `outputs/<run_id>/*.json` works for one fixture but not at scale. A consensus aggregator picks per-field winners (majority vote for facts, single LLM call for narrative) and produces one clean record per fixture that downstream code can consume.

Separately, the `LabelInfo` schema currently lacks fields the app will need: a logo URL for cards, Instagram/Twitter handles, and a tagline distinct from the multi-sentence summary. Adding them now lets the experiment phase exercise the prompt extension and the aggregator together.

## 2. Goal

After this work, the canonical experiment loop is:

```bash
lab run --prompts label_v3_app_fields --vendors tavily_deepseek,gemini
lab aggregate <run_id>
open reports/<run_id>.md
```

The report shows both raw per-vendor cells (existing) and a new `## Aggregated (consensus)` section with one merged `LabelInfo` per fixture, including field-level provenance.

**Non-goals**

- Wiring the new fields into production `LabelSearchResult` or any `src/collector/` code.
- Building a `consensus` vendor adapter that runs all vendors and merges in one step. Reserved for Phase 2 (a separate spec / plan) once the recipe stabilizes.
- Image download / hosting of `logo_url`. Sandbox stores the URL only.
- LLM-as-judge cross-validation of fact correctness against ground truth. The aggregator merges; it does not score.

## 3. Phasing

This spec covers **Phase 1 only**.

- **Phase 1 (this spec):** schema fields + `label_v3_app_fields` prompt + `lab.aggregate.merge_cells()` core + `lab aggregate` CLI + report extension.
- **Phase 2 (future, separate spec):** `consensus` vendor adapter that internally runs the configured upstream vendors and calls `merge_cells()` so a single `lab run --vendors consensus` produces a merged cell. Reuses Phase 1 core unchanged.

The phasing keeps each PR small and lets Phase 1 ship value immediately. Phase 2 is optional and only undertaken if the merged-result quality justifies hiding intermediate cells.

## 4. Schema additions

Edit `experiments/labels/src/lab/schemas.py`. Add four optional fields to `LabelInfo`:

```python
class LabelInfo(BaseModel):
    # ... existing identity block ...
    founded_year: int | None = None
    status: Literal["active", "inactive", "unknown"] = "unknown"
    logo_url: str | None = None          # NEW: direct image URL of the label logo / avatar
    tagline: str | None = None           # NEW: single-sentence identity line (<= 100 chars)

    # ... existing size block, unchanged ...

    # channels block — appended:
    website: str | None = None
    bandcamp_url: str | None = None
    residentadvisor_url: str | None = None
    discogs_url: str | None = None
    beatport_url: str | None = None
    soundcloud_url: str | None = None
    instagram_url: str | None = None     # NEW
    twitter_url: str | None = None       # NEW: accepts twitter.com or x.com URLs

    # ... rest unchanged ...
```

### Decisions

- All four new fields are `str | None = None` (Optional, default null). Back-compat: existing cell JSONs still validate.
- `tagline` is NOT required, unlike `summary`. When the label is unknown the model returns null instead of inventing text.
- `twitter_url` accepts either domain. Normalization is left to the downstream app — the sandbox stores whatever the model returns.
- `logo_url` is a **direct image URL** (ends in `.png` / `.jpg` / `.webp` / `.gif`), not a page URL. The prompt enforces this; the aggregator's URL dedup logic does not validate the suffix (model may return CDN URLs without extensions).

## 5. New prompt: `label_v3_app_fields/v1`

Create `experiments/labels/src/lab/prompts/label_v3_app_fields.py`. Register slug `label_v3_app_fields`, version `v1`, schema `LabelInfo`.

The slug `label_v3` is free after the earlier removal of `label_v3_ai_focus`. The descriptive suffix `_app_fields` signals intent: this prompt targets app-integration output, not pure AI-detection.

### Source

Built as `label_v2_facts/v1` + extensions. The new system prompt is the v2 system text plus this addendum:

```
- `logo_url`: prefer the label's official square/profile image as a direct
  image URL (ends with .png/.jpg/.webp/.gif). Source priority: Bandcamp
  profile avatar > Discogs label image > official website logo > SoundCloud
  avatar. Leave null if no clear direct image URL is found. Do not return
  page URLs.
- `instagram_url` / `twitter_url`: official accounts only. Prefer
  https://www.instagram.com/<handle> and https://x.com/<handle>. The handle
  must match the label name or be clearly linked from the label's website /
  Bandcamp / RA. Leave null when uncertain.
- `tagline`: one short sentence, max 100 characters, capturing the label's
  identity. Examples:
    * "Swedish techno powerhouse since 1996."
    * "London home of melodic deep house."
    * "AI-generated lofi YouTube channel."
  Avoid generic copy ("a record label"). Leave null only if the label is
  truly unknown.
```

The new user template extends `label_v2_facts.USER_TEMPLATE`:

```python
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
```

Register in `load_builtin_prompts()` next to existing prompts.

`label_v2_facts/v1` is **not modified or removed**. It remains as the A/B baseline.

## 6. Aggregator core: `lab.aggregate`

Create `experiments/labels/src/lab/aggregate.py`. Pure module — no CLI / no IO except calling the LLM client passed in.

### Public surface

```python
def merge_cells(
    cells: list[dict],
    deepseek_client: Any,
    deepseek_model: str = "deepseek-v4-flash",
) -> tuple[BaseModel, dict]:
    """
    Merge parsed LabelInfo outputs from multiple vendor cells.

    Cells with response.parsed == None or error != None are filtered out.
    Returns (merged_label_info, merge_meta).

    merge_meta keys:
      - source_cells: list of {vendor, model, confidence}
      - field_provenance: dict[field_name, str] explaining how each field
        was chosen ("median", "majority(3/3)", "first non-null(gemini)", etc.)
      - narrative_cost_usd: float (DeepSeek call cost, 0 if skipped)
      - narrative_latency_ms: int (DeepSeek call latency, 0 if skipped)
      - narrative_fallback: optional str ("max_confidence" if DeepSeek failed)
      - single_source: optional bool (True if only one cell in)
      - all_failed: optional bool (True if no parseable cells)
    """
```

### Field-level merge rules

Deterministic for everything except four narrative fields.

| Field | Type | Strategy |
|---|---|---|
| `label_name` | str | First non-null ordered by descending confidence. |
| `founded_year` | int \| None | Median of non-null values. |
| `country` | str \| None | Majority vote. Tie → shortest string (`GB` beats `UK` beats `United Kingdom`). |
| `parent_label`, `distribution`, `last_release_date`, `status` | str \| None | Majority vote. Tie → value from cell with highest `confidence`. |
| `catalog_size_estimate`, `roster_size_estimate`, `releases_last_12_months` | int \| None | Median of non-null values. |
| `activity`, `ai_content` | enum | Majority vote. Tie → highest-confidence cell. |
| `aliases`, `sublabels`, `notable_artists`, `primary_styles`, `sources` | list[str] | Union with case-insensitive dedup. `notable_artists` capped at top-5 by frequency across cells. |
| `website`, `bandcamp_url`, `residentadvisor_url`, `discogs_url`, `beatport_url`, `soundcloud_url`, `instagram_url`, `twitter_url`, `logo_url` | str \| None | Pick the non-null value from the cell with the highest `confidence`. Tie → first by vendor name alphabetically. |
| `confidence` | float | Mean of non-null. |
| `ai_signals` | list[AISignal] | Union dedup by `(kind, description.strip().lower())`. |

Narrative fields go through one DeepSeek call:

| Field | Type | Strategy |
|---|---|---|
| `tagline`, `summary`, `ai_reasoning`, `notes` | str \| None | DeepSeek narrative merge (see below). |

### Narrative merge call

One `chat.completions.create` against DeepSeek with `response_format={"type": "json_object"}`. Input is a structured user message containing each vendor's narrative outputs verbatim plus the merge instructions:

```
Three vendors researched the label "<label_name>". Here are their narrative
outputs:

VENDOR A (<name>, confidence <X>):
tagline: <...>
summary: <...>
ai_reasoning: <...>

VENDOR B (...):
...

Combine these into ONE clean narrative section:
- tagline: pick the strongest single sentence from the vendors. Do NOT
  invent new facts. If all vendors returned null, return null.
- summary: 2-4 sentences using ONLY facts that appear in at least one
  vendor's narrative. Resolve contradictions by preferring the vendor with
  higher confidence.
- ai_reasoning: combine the signals/reasoning into one coherent paragraph.
- notes: empty (null) unless vendors disagree on key facts. If they do,
  note the disagreement explicitly.

Output ONLY JSON: {"tagline": "..." | null, "summary": "...", "ai_reasoning": "...", "notes": "..." | null}
```

System prompt for this call:

> You are merging multiple researchers' narrative descriptions of the same music label into one coherent output. Use ONLY facts present in the inputs. Never invent.

### Cost

Estimated per merge group: ~2k input + ~500 output tokens × `deepseek-v4-flash` pricing = **~$0.0004**. A run of 8 fixtures with 3 vendors each produces 8 merge groups, costing **~$0.003** for narrative merging total.

### Failure modes

- **Single cell in group** → skip merge entirely. Copy the single cell's parsed payload as `merged`. Set `merge_meta.single_source = True`. Cost 0.
- **All cells failed (no parseable input)** → return a `LabelInfo` with `label_name = cells[0]["fixture"]["label_name"]`, `summary = "All vendor sources failed."`, `ai_reasoning = "n/a"`, `confidence = 0.0`. Set `merge_meta.all_failed = True`. Cost 0.
- **DeepSeek narrative call raises or returns malformed JSON** → fall back: take narrative fields verbatim from the cell with the highest confidence. Set `merge_meta.narrative_fallback = "max_confidence"`. Other (deterministic) fields are unaffected.

The aggregator never raises out to the caller — same contract as vendor adapters.

## 7. CLI: `lab aggregate <run_id>`

New typer subcommand in `experiments/labels/src/lab/cli.py`.

```
lab aggregate <run_id>
lab aggregate <run_id> --fixtures drumcode,anjunadeep
lab aggregate <run_id> --vendors gemini,tavily_deepseek
lab aggregate <run_id> --prompts label_v3_app_fields
```

### Flow

1. Read `outputs/<run_id>/manifest.json` and `outputs/<run_id>/*.json` (existing loader logic from `report.py`).
2. Filter cells by CLI flags (`--vendors`, `--prompts`, `--fixtures`).
3. Group cells by `(prompt_slug, fixture_id)`. Each group is one merge target.
4. For each group call `merge_cells(group, deepseek_client, deepseek_model)`.
5. Write `outputs/<run_id>/merged/<prompt_slug>__<fixture_id>.json` for each group.
6. Append a top-level `aggregates` section to `manifest.json`:

```json
"aggregates": {
  "merged_at": "2026-05-19T08:00:00Z",
  "groups": 8,
  "filters_applied": {"vendors": null, "prompts": ["label_v3_app_fields"], "fixtures": null},
  "total_aggregate_cost_usd": 0.0032
}
```

If `aggregates` already exists (re-aggregation of the same run), overwrite it.

7. Call `build_report(...)` so the markdown report is regenerated with the new `## Aggregated` section.

### Merged cell file shape

```json
{
  "run_id": "20260518-200000-abcd",
  "merged_at": "2026-05-19T08:00:00Z",
  "prompt": {"slug": "label_v3_app_fields", "version": "v1"},
  "fixture": {"id": "drumcode", "label_name": "Drumcode", ...},
  "source_cells": [
    {
      "vendor": "tavily_deepseek",
      "model": "deepseek-v4-flash",
      "file": "label_v3_app_fields__tavily_deepseek__drumcode.json",
      "confidence": 1.0
    },
    {
      "vendor": "gemini",
      "model": "gemini-2.5-flash",
      "file": "label_v3_app_fields__gemini__drumcode.json",
      "confidence": 0.95
    }
  ],
  "merged": { /* full LabelInfo dump */ },
  "merge_meta": {
    "field_provenance": {
      "founded_year": "median:1996",
      "country": "majority(2/2)",
      "logo_url": "first non-null(tavily_deepseek)",
      "tagline": "deepseek narrative"
    },
    "narrative_cost_usd": 0.0004,
    "narrative_latency_ms": 4200
  },
  "aggregate_cost_usd": 0.0004
}
```

### Dependencies

`DEEPSEEK_API_KEY` must be set (already in `Settings`). Failure mode: if missing, CLI exits with code 2 and message "DEEPSEEK_API_KEY required for aggregation".

## 8. Report extension

`build_report(run_dir, reports_dir)` in `experiments/labels/src/lab/report.py` gains one optional behavior: if `run_dir/merged/` exists and contains JSON files, render a new `## Aggregated (consensus)` section **after** `## Summary` and **before** the first `## Fixture:` section.

Implementation note: add a `_aggregated_section(merged_files: list[Path]) -> list[str]` helper. Hook into `build_report` near the top, after the summary section.

### Section content

```markdown
## Aggregated (consensus)

Merged via DeepSeek narrative + deterministic rules. Total aggregate cost: $0.0032.

### drumcode — label_v3_app_fields (2 sources)

| field | value | provenance |
| --- | --- | --- |
| founded_year | 1996 ✓ | median:1996 |
| country | Sweden ✓ | majority(2/2) |
| logo_url | https://f4.bcbits.com/img/drumcode-avatar.jpg | first non-null(tavily_deepseek) |
| instagram_url | https://instagram.com/drumcode_se | first non-null(gemini) |
| twitter_url | https://x.com/drumcode | first non-null(gemini) |
| activity | high | majority(2/2) |
| ai_content | none_detected ✓ | majority(2/2) |
| confidence | 0.975 | mean(1.0, 0.95) |
| tagline | Swedish techno powerhouse since 1996. | deepseek narrative |
| summary | (full text...) | deepseek narrative |
| notable_artists | Adam Beyer, Amelie Lens, Alan Fitzpatrick, Layton Giordani, Bart Skils | union top-5 by freq |

**Sources:** tavily_deepseek/deepseek-v4-flash, gemini/gemini-2.5-flash
```

### Ground-truth ✓/✗

Same logic as existing per-fixture tables: when the fixture has a `ground_truth` block, compare and annotate `founded_year`, `country`, `parent_label`, `ai_content`. Reuse the existing `_render_cell_field` annotation helper or extract its compare logic.

### Back-compat

If `run_dir/merged/` does not exist or is empty, `build_report` produces exactly the same output as before. Existing tests stay green.

## 9. Recommended experiment pipeline

Document the canonical run in `experiments/labels/README.md` under a new section:

```markdown
## Recommended pipeline

For an end-to-end experiment producing a consensus label record:

```bash
# 1. Run two complementary vendors with the app-targeted prompt
lab run --prompts label_v3_app_fields --vendors tavily_deepseek,gemini

# 2. Merge per-fixture cells into one consensus LabelInfo
lab aggregate <run_id>

# 3. Inspect
open reports/<run_id>.md
```

Approximate cost for 8 fixtures: $0.007 (Tavily+DeepSeek) + $0.04 (Gemini) +
$0.003 (narrative merge) = **~$0.05** per full run.

When a merged cell shows `confidence < 0.5` or `ai_content=unknown`, rerun
that specific fixture against a higher-quality vendor and re-aggregate:

```bash
lab run --fixtures <id> --vendors anthropic --prompts label_v3_app_fields
lab aggregate <newer_run_id>
```

Cheap baseline + on-demand expert arbiter pattern.
```

## 10. Tests

| File | Coverage |
|---|---|
| `tests/test_schemas.py` | LabelInfo accepts old payloads (no new fields, back-compat) AND new payloads (logo_url, instagram_url, twitter_url, tagline) without error. |
| `tests/test_prompts.py` | `label_v3_app_fields` registers via `load_builtin_prompts()`. system prompt contains `"logo_url"`, `"tagline"`, `"instagram_url"`. user template contains `"label logo image URL"`. |
| `tests/test_aggregate.py` (new) | Direct calls to `merge_cells` with 3 synthetic cell dicts. Verify median (numbers), majority+tie-break (enums, strings), union+dedup (lists), `notable_artists` top-5 cap, URL normalization, `confidence` mean. DeepSeek path: mock client returning `{"tagline": "...", "summary": "...", "ai_reasoning": "...", "notes": null}`. Edge cases: single source → skip merge with `single_source=True`; all-error → `all_failed=True`; DeepSeek raises → `narrative_fallback="max_confidence"`. |
| `tests/test_cli.py` | New `test_aggregate_writes_merged` with tmp_path + StubDeepSeek + 2 fake input cells. Verify `outputs/<run>/merged/*.json` files exist, manifest gets `aggregates` block, report shows `## Aggregated`. |
| `tests/test_report.py` | New `test_build_report_renders_aggregated_section`: write 2 raw cell JSONs + 1 merged JSON to tmp_path, call `build_report`, assert `## Aggregated (consensus)` and provenance text appear. |

No live API in the suite. All vendor and DeepSeek calls go through mocks/stubs.

## 11. Out of scope

- `consensus` vendor adapter (Phase 2).
- Modifying production `src/collector/` code, `LabelSearchResult` schema, or alembic migrations.
- Image fetching, image hosting, image dimension validation, or alt-text generation for `logo_url`.
- Cross-vendor scoring against ground truth or any kind of accuracy metric.
- Caching merged outputs across runs.
- Re-running aggregator automatically when new cells arrive in an existing run dir (must be invoked explicitly).
- Multi-prompt merging (cells from `label_v1_baseline` and `label_v3_app_fields` for the same fixture stay in separate merge groups; we never combine across prompts).

## 12. Open questions

None for this spec.

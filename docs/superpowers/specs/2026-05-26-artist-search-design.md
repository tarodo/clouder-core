# Artist Information Search — Local Experiment (Design Spec)

**Date:** 2026-05-26
**Status:** Approved for implementation (experiment scope only)
**Author:** brainstorming session

## Goal

Build a local-only experiment harness for comparing AI vendors and prompts on
the task of **researching a music artist** and producing a structured
`ArtistInfo` record. This mirrors the proven label-enrichment sandbox at
`experiments/labels/` (design spec
`docs/superpowers/specs/2026-05-17-label-ai-sandbox-design.md`).

The deliverable of this spec is three things:

1. A search **prompt** (`artist_v1`) tuned for artist disambiguation + facts.
2. A **data model** (`ArtistInfo`) for the search result.
3. A **local test script** (`artlab` Typer CLI) under `experiments/artists/`.

## Scope

**In scope (this spec):**

- `experiments/artists/` self-contained package, a sibling of
  `experiments/labels/`. Own vendor adapters, prompts, fixtures, reports.
- `ArtistInfo` pydantic schema.
- One prompt: `artist_v1` (facts-discipline + disambiguation + AI detection).
- CLI: `run`, `aggregate`, `report`, `list`.
- Mocked-SDK tests, mirroring the label sandbox test layout.

**Out of scope (deferred, NOT this spec):**

- Production wiring: DB tables (`clouder_artist_enrichment_*`,
  `clouder_artist_info`), the `artist_enrichment` Lambda handler, SQS queue,
  `/admin/artists/enrich` + `/admin/auto-enrich/artists` routes, the frontend
  "artists" tab in `AdminAutoEnrichPage`.
- These follow the label production pattern and get their own spec(s) once the
  prompt + schema are validated locally. This is the same staged approach used
  for labels (sandbox first, production second).

**Why a sibling, not a generalized `lab`:** generalizing `lab` to
`--entity artist|label` would couple artist work to the proven label code and
risk regressing it. A sibling package is isolated and disposable, which is the
point of an experiment harness. The multi-vendor comparison is retained — that
is the whole reason this is a harness and not a one-off script.

## Design decisions (from brainstorming)

| Decision | Choice | Rationale |
|---|---|---|
| First-spec scope | Experiment only | "для начала — эксперимент-скрипт" |
| Disambiguation input | name + sample tracks + labels | artist names collide heavily; tracks/labels anchor identity |
| AI detection | Full mirror of labels | useful to filter AI-generated "artists" out of DJ curation |
| Headline fields | streaming/social links, labels/collabs, bio/country/genres | most valuable for DJ curation |
| Default vendor/model | `openai` / `gpt-5.4-mini` | user-specified |

## Directory layout

Mirrors `experiments/labels/` exactly. Package import name `artlab`,
distribution name `clouder-artist-lab`, CLI entry point `artlab`.

```
experiments/artists/
  README.md
  pyproject.toml              # name=clouder-artist-lab, [project.scripts] artlab = "artlab.cli:app"
  .env.example
  .gitignore                  # ignores .env, outputs/, reports/, .venv/, *.egg-info
  fixtures.yaml               # test artists: name + sample_tracks + known_labels + style
  src/artlab/
    __init__.py
    __main__.py
    cli.py                    # Typer: run / aggregate / report / list
    config.py                 # Settings (env keys + default models)
    fixtures.py               # load_fixtures()
    aggregate.py              # merge_cells() consensus merge (DeepSeek narrative)
    report.py                 # build_report()
    runner.py                 # RunSpec, run_matrix() — ThreadPoolExecutor
    schemas.py                # ArtistInfo, Fixture, GroundTruth, enums
    prompts/
      __init__.py             # PROMPTS registry, register(), load_builtin_prompts()
      base.py                 # PromptConfig, render_user()
      artist_v1.py            # the artist search prompt
    vendors/
      __init__.py
      base.py                 # VendorAdapter Protocol, VendorResponse
      anthropic_claude.py
      gemini_flash.py
      openai_gpt.py
      perplexity_sonar.py
      tavily_deepseek.py
      xai_grok.py
      kimi_k2.py
      pricing.py
  tests/
    conftest.py
    test_schemas.py
    test_prompts.py
    test_config.py
    test_fixtures_loader.py
    test_runner.py
    test_aggregate.py
    test_report.py
    test_pricing.py
    test_vendor_*.py          # one per vendor, mocked SDK
  outputs/<run_id>/...        # gitignored: raw cells + manifest.json + merged/
  reports/<run_id>.md         # gitignored: side-by-side markdown report
```

The vendor adapters, `runner.py`, `report.py`, `aggregate.py`, `pricing.py`,
and `config.py` are near-verbatim copies from the label sandbox. The only
substantive new content is `schemas.py`, `prompts/artist_v1.py`,
`fixtures.yaml`, the `render_user()` signature, and the `Fixture` model.

## Data model — `ArtistInfo`

`src/artlab/schemas.py`. Pydantic v2. Field-discipline mirrors `LabelInfo`.

```python
class ArtistType(str, Enum):
    SOLO = "solo"
    DUO = "duo"
    GROUP = "group"
    ALIAS_PROJECT = "alias_project"   # one person's side alias
    UNKNOWN = "unknown"

class AIContentStatus(str, Enum):
    UNKNOWN = "unknown"
    NONE_DETECTED = "none_detected"
    SUSPECTED = "suspected"
    CONFIRMED = "confirmed"

class AISignalKind(str, Enum):
    NO_LIVE_PRESENCE = "no_live_presence"               # no gigs/tour/RA dates
    AI_GENERATED_IMAGERY = "ai_generated_imagery"        # artist photos look AI
    SUSPICIOUS_RELEASE_VELOCITY = "suspicious_release_velocity"  # impossible output
    NO_SOCIAL_FOOTPRINT = "no_social_footprint"
    TEMPLATED_BIO = "templated_bio"                      # generic/boilerplate bio
    DISTRIBUTOR_ONLY_NO_LABEL = "distributor_only_no_label"
    VOICE_CLONING_INDICATORS = "voice_cloning_indicators"
    AI_FARM_NAME_PATTERN = "ai_farm_name_pattern"        # mass-produced naming
    REVERSE_IMAGE_NO_RESULTS = "reverse_image_no_results"
    NAMED_IN_PRESS = "named_in_press"                    # press explicitly says AI
    CREDITED_TOOL = "credited_tool"                      # artist credits Suno/etc.
    OTHER = "other"

class AISignal(BaseModel):
    kind: AISignalKind
    description: str
    source_url: str | None = None

class ArtistInfo(BaseModel):
    # --- Identity ---
    artist_name: str                                     # canonical, resolved
    aliases: list[str] = Field(default_factory=list)     # AKA / other names
    real_name: str | None = None
    artist_type: ArtistType = ArtistType.UNKNOWN
    members: list[str] = Field(default_factory=list)     # if duo/group

    # --- Origin ---
    country: str | None = None
    city: str | None = None
    active_since: int | None = None                      # year; sourced only
    status: Literal["active", "inactive", "unknown"] = "unknown"

    # --- Music ---
    primary_styles: list[str] = Field(default_factory=list)        # 2-5 tags
    labels: list[str] = Field(default_factory=list)                # releases on
    notable_collaborators: list[str] = Field(default_factory=list) # co-authors/remixers
    notable_releases: list[str] = Field(default_factory=list)      # <=5 anchor tracks/EPs

    # --- Links (each must clearly belong to THIS artist) ---
    spotify_url: str | None = None
    soundcloud_url: str | None = None
    bandcamp_url: str | None = None
    beatport_url: str | None = None
    residentadvisor_url: str | None = None
    discogs_url: str | None = None
    instagram_url: str | None = None
    twitter_url: str | None = None
    website: str | None = None

    # --- Narrative ---
    tagline: str | None = None                           # <=100 chars
    bio: str | None = None                               # 1-3 sentences
    summary: str                                         # required

    # --- AI detection ---
    ai_content: AIContentStatus = AIContentStatus.UNKNOWN
    ai_signals: list[AISignal] = Field(default_factory=list)
    ai_reasoning: str                                    # required

    # --- Meta ---
    confidence: float = Field(ge=0, le=1)
    sources: list[str] = Field(default_factory=list)
    notes: str | None = None
```

Note: `aliases` is included even though it was not picked as a "headline" field
— it is core to artist identity and disambiguation, and it is cheap.

### Fixture / GroundTruth models

```python
class GroundTruth(BaseModel):
    country: str | None = None
    active_since: int | None = None
    ai_content_expected: AIContentStatus | None = None

class Fixture(BaseModel):
    id: str
    artist_name: str
    style: str
    sample_tracks: list[str] = Field(default_factory=list)   # disambiguation anchor
    known_labels: list[str] = Field(default_factory=list)    # disambiguation anchor
    ground_truth: GroundTruth | None = None

class FixturesFile(BaseModel):
    fixtures: list[Fixture]
```

## Prompt — `artist_v1`

`src/artlab/prompts/artist_v1.py`. Registered via `register(PromptConfig(...))`,
imported from `load_builtin_prompts()` in `prompts/__init__.py`.

**System prompt:**

```
You research electronic-music artists. Output structured facts only.
Rules:
- Use the disambiguation context (sample releases + labels + style) to lock
  onto the CORRECT artist. Many artists share a name. If the context does not
  resolve which artist this is, set confidence <= 0.4 and explain the
  ambiguity in `notes`.
- Every URL must clearly belong to THIS artist: the profile name must match
  and it should reference at least one of the known releases or labels. If a
  link cannot be tied to this artist, omit it.
- active_since and any year require a supporting URL in `sources`. Never guess
  years.
- aliases / real_name: list everything you find; mark uncertain ones in `notes`.
- artist_type: solo unless there is evidence of a duo / group / alias project.
- labels: labels the artist has actually released on, most relevant first.
- notable_collaborators: frequent co-authors and remixers, not one-offs.
- notable_releases: at most 5 anchor tracks/EPs that confirm identity.
- primary_styles: 2-5 specific genre tags, no umbrella terms.
- AI detection: assess whether this may be an AI-generated artist (synthetic
  persona, no live presence, AI imagery, impossible output velocity, voice
  cloning, credited AI tools). Record evidence in `ai_signals`.
  ai_content=confirmed only with strong evidence (the artist or press
  explicitly states AI generation). ai_reasoning is always required, even when
  none_detected — explain why.
- summary is always required.
- confidence: 1.0 only if identity is confirmed via the context match AND
  country is sourced AND there are >=3 supporting sources.
```

**User template:**

```
Research the electronic-music artist "{artist_name}".{context_block}
Find: aliases and real name, country and city, years active, labels they
release on, frequent collaborators and remixers, notable releases, streaming
and social profiles (Spotify, SoundCloud, Bandcamp, Beatport, Resident
Advisor, Discogs, Instagram), primary styles, and a short bio.
Then assess AI-content status and explain your reasoning.
```

**`render_user()` builds `context_block`** from the fixture's disambiguation
anchors (empty string if none provided):

```
\nDisambiguation context — this is the artist who released: {sample_tracks};
on labels: {known_labels}; genre hint: {style}.
```

New signature (replaces the label `render_user(cfg, label_name, style, release_name)`):

```python
def render_user(cfg, artist_name, style, sample_tracks, known_labels) -> str: ...
```

## CLI

`artlab` Typer app, same command surface as `lab`:

```bash
cd experiments/artists
python3.12 -m venv .venv
.venv/bin/pip install -e ".[dev]"
cp .env.example .env            # add API keys; any subset works, missing vendors skipped

# default run: openai / gpt-5.4-mini across all fixtures
.venv/bin/artlab run --prompts artist_v1

# subset
.venv/bin/artlab run --prompts artist_v1 --vendors openai --fixtures anna

# multi-vendor compare, then consensus merge
.venv/bin/artlab run --prompts artist_v1 --vendors openai,perplexity
.venv/bin/artlab aggregate <run_id>     # DeepSeek narrative merge; needs DEEPSEEK_API_KEY

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
- `reports/<run_id>.md` — side-by-side markdown report

## Config / vendors

`src/artlab/config.py` `Settings` (env-driven, copied from labels). Vendor set
is identical: `anthropic`, `xai`, `gemini`, `openai`, `tavily_deepseek`,
`perplexity`, `kimi`. A vendor is only usable if its API key is present
(`available_vendor_names()`); missing vendors are skipped silently.

**Default models** — same as the label sandbox, except `openai_model`:

| Setting | Default |
|---|---|
| `openai_model` | **`gpt-5.4-mini`** (user-specified; via Responses API) |
| `anthropic_model` | `claude-sonnet-4-6` |
| `gemini_model` | `gemini-2.5-flash` |
| `xai_model` | `grok-4` |
| `deepseek_model` | `deepseek-v4-flash` |
| `perplexity_model` | `sonar` |
| `kimi_model` | `kimi-k2.6` |
| `concurrency` | `8` |
| `request_timeout` | `180` |

The default `run` (no `--vendors`) uses every vendor with a configured key;
in practice a first run sets only `OPENAI_API_KEY`, so it exercises
`openai` / `gpt-5.4-mini`. Web search matters for artists (fresh profiles), so
when comparing, pair `openai` with a web-search vendor (`perplexity` or
`tavily_deepseek`).

## Aggregation

`merge_cells()` copied from labels: median for numeric, majority vote for
enums, dedup/round-robin for lists and URLs, DeepSeek LLM synthesis for
narrative fields (`tagline`, `bio`, `summary`, `ai_reasoning`, `notes`).
Provenance recorded per field. Aggregation is optional — only meaningful when
2+ vendors ran the same fixture. Requires `DEEPSEEK_API_KEY`.

## Fixtures

`fixtures.yaml` — a representative spread for the artist task:

- **Clear, well-documented:** e.g. a major artist with unique name.
- **Name collision:** a common artist name (the disambiguation stress test) —
  `sample_tracks` + `known_labels` must resolve it.
- **Obscure / niche:** sparse web presence.
- **Synthetic AI artist:** expect `ai_content` `suspected`/`confirmed`.

Each fixture carries `artist_name`, `style`, `sample_tracks`, `known_labels`,
and optional `ground_truth` (`country`, `active_since`, `ai_content_expected`)
for spot-checking accuracy in the report.

## Tests

Mirror the label test layout. All tests mock the vendor SDK clients — **no live
API calls**. Coverage: schema validation, prompt registration + `render_user`
(including empty `context_block`), config/env parsing, fixtures loader, runner
matrix, aggregate merge rules, report rendering, pricing, and one mocked test
per vendor adapter. Run with `.venv/bin/pytest`.

## Cost

Comparable to the label sandbox (~$0.05 per full multi-vendor run over ~6-8
fixtures). A single-vendor `openai` run is a few cents.

## Future (deferred to later specs)

Once `artist_v1` + `ArtistInfo` are validated locally, the production feature
follows the label pattern: alembic tables (`clouder_artist_enrichment_runs`,
`clouder_artist_enrichment_cells`, `clouder_artist_info`,
`artist_auto_enrich_config`, `artist_auto_enrich_state`), an
`artist_enrichment_handler` Lambda on a dedicated SQS queue, `/admin/artists/enrich`
+ `/admin/auto-enrich/artists` routes, and the "artists" tab in
`AdminAutoEnrichPage` (already stubbed as "coming soon"). Each is its own
spec → plan → implementation cycle.

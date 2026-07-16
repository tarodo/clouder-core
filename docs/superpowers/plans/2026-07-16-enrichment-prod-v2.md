# Enrichment Prod v2 Implementation Plan (AI-off + socials post-pass)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the experiment-validated production shape: single OpenAI pass without AI-detection (full schema minus `ai_*`, `max_tool_calls=3`), a 3-tier Tavily socials post-pass with validation on all tiers, honest per-run pricing, hidden AI frontend surfaces, and analytics scripts.

**Architecture:** Spec addendum governs: `docs/superpowers/specs/2026-07-15-enrichment-cost-instagram-design.md` ("ADDENDUM 2026-07-16"). Proven socials code is **ported from `experiments/enrichment_split/src/splitlab/`** (ran live on 200 entities) with named adaptations — do not redesign it. Prod runtime = Lambda: RDS Data API only (no psycopg), httpx allowed (already a vendor dep).

**Tech Stack:** Python 3.12 Lambdas under `src/collector/`, pydantic v2, OpenAI Responses API, Tavily REST via httpx, pytest (`tests/unit/`, fully mocked), React 19 + Mantine frontend.

## Global Constraints

- **Reversible AI-off:** storage models keep `ai_*` fields (`ai_reasoning` becomes `str = ""`); no DB migrations; rollback = switch `auto_enrich_config.prompt_slug` back.
- **Request schemas sent to vendors must not contain `ai_content`/`ai_signals`/`ai_reasoning`** — structured output forces any schema field to be filled, that's the cost lever.
- Socials post-pass fires **only when `instagram_url` is empty after merge**; handle validation on **all** tiers; short-name rule: substring match for normalized names ≥4 chars + cross-network match.
- Pricing constants: web_search **$0.01/call**, Tavily **$0.008/credit** (basic search 1, extract 1 per ≤5 URLs). gpt-5.4-mini tokens are comped but token estimates stay in `pricing.py`.
- `max_tool_calls` default **3**, code-level default (no terraform change in this plan); `reasoning.effort` sent only when configured non-empty.
- No new API routes → no OpenAPI regeneration.
- All new/changed backend tests live in `tests/unit/`, fully mocked; run `pytest -q` (repo root, `.venv/bin/pytest` if `pytest` absent from PATH) before each commit.
- Frontend gates before its commit: `cd frontend && pnpm typecheck && pnpm lint && pnpm test`.
- Commits: Conventional Commits, single `-m` (heredoc via `$(/bin/cat <<'EOF' … EOF)` if multi-line; plain `cat` is aliased to `bat`). No AI trailers.
- Branch: `feat/enrichment-prod-v2` off current `origin/main`.

## File Structure

```
src/collector/label_enrichment/schemas.py          # + LabelInfoRequest; ai_reasoning default
src/collector/artist_enrichment/schemas.py         # + ArtistInfoRequest; ai_reasoning default
src/collector/label_enrichment/prompts/label_v4_no_ai.py    # new
src/collector/artist_enrichment/prompts/artist_v2_no_ai.py  # new
src/collector/label_enrichment/prompts/__init__.py # register v4, default slug
src/collector/artist_enrichment/prompts/__init__.py# register v2_no_ai, default slug
src/collector/label_enrichment/vendors/openai_gpt.py  # knobs + instrumentation
src/collector/label_enrichment/vendors/pricing.py     # fee constants + helper
src/collector/social_links.py                      # NEW: regex + validation + TavilyClient + SocialsResolver
src/collector/label_enrichment/orchestrator.py     # socials post-pass hook
src/collector/artist_enrichment/orchestrator.py    # socials post-pass hook
src/collector/label_enrichment_handler.py          # wire knobs+resolver settings
src/collector/artist_enrichment_handler.py         # wire knobs+resolver settings
src/collector/settings.py                          # openai_max_tool_calls etc.
frontend/src/features/library/…, playlists/…       # hide AI surfaces
scripts/enrichment_stats.py, scripts/openai_usage_report.py
tests/unit/test_label_enrichment_request_schema.py … (per task)
```

Port sources (read-only references): `experiments/enrichment_split/src/splitlab/social_regex.py`, `tavily_client.py`, `facts_pass.py` (tier logic), tests under `experiments/enrichment_split/tests/`.

---

### Task 1: Request schemas + storage defaults (label + artist)

**Files:**
- Modify: `src/collector/label_enrichment/schemas.py`
- Modify: `src/collector/artist_enrichment/schemas.py`
- Test: `tests/unit/test_enrichment_request_schemas.py`

**Interfaces:**
- Produces: `LabelInfoRequest` (all `LabelInfo` fields except `ai_content`, `ai_signals`, `ai_reasoning`) and `ArtistInfoRequest` (same rule vs `ArtistInfo`). Storage models unchanged except `ai_reasoning: str = ""` (was required) in BOTH.

- [ ] **Step 1: Write the failing test**

`tests/unit/test_enrichment_request_schemas.py`:

```python
from collector.artist_enrichment.schemas import ArtistInfo, ArtistInfoRequest
from collector.label_enrichment.schemas import LabelInfo, LabelInfoRequest

AI_FIELDS = {"ai_content", "ai_signals", "ai_reasoning"}


def test_request_models_are_storage_minus_ai():
    assert set(LabelInfoRequest.model_fields) == set(LabelInfo.model_fields) - AI_FIELDS
    assert set(ArtistInfoRequest.model_fields) == set(ArtistInfo.model_fields) - AI_FIELDS


def test_request_payload_validates_into_storage_via_defaults():
    req = LabelInfoRequest(label_name="X", summary="s", confidence=0.5)
    info = LabelInfo.model_validate(req.model_dump())
    assert info.ai_reasoning == "" and info.ai_content.value == "unknown" and info.ai_signals == []

    areq = ArtistInfoRequest(artist_name="Y", summary="s", confidence=0.5)
    ainfo = ArtistInfo.model_validate(areq.model_dump())
    assert ainfo.ai_reasoning == "" and ainfo.ai_signals == []


def test_request_field_types_match_storage():
    for req_model, store_model in ((LabelInfoRequest, LabelInfo), (ArtistInfoRequest, ArtistInfo)):
        for name, f in req_model.model_fields.items():
            assert f.annotation == store_model.model_fields[name].annotation, name
```

- [ ] **Step 2: Run to verify failure** — `pytest tests/unit/test_enrichment_request_schemas.py -q` → ImportError (`LabelInfoRequest`).

- [ ] **Step 3: Implement.** In `label_enrichment/schemas.py`: change `ai_reasoning: str` to `ai_reasoning: str = ""` in `LabelInfo`, then append after `LabelInfo`:

```python
class LabelInfoRequest(BaseModel):
    """Vendor-facing schema: LabelInfo minus AI-detection fields.

    Structured output forces the model to fill every schema field, so the
    ai_* fields must be absent here, not just unmentioned in the prompt.
    Kept as an explicit copy (not generated) so the diff is reviewable;
    test_enrichment_request_schemas pins it to LabelInfo field-for-field.
    """

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

    summary: str
    confidence: float = Field(ge=0, le=1)
    sources: list[str] = Field(default_factory=list)
    notes: str | None = None
```

In `artist_enrichment/schemas.py`: same `ai_reasoning: str = ""` change in `ArtistInfo`, then append `ArtistInfoRequest` = all `ArtistInfo` fields except the three `ai_*`, in the same order, identical annotations/defaults (Identity/Origin/Music/Links/Narrative/Meta blocks — copy each field line verbatim from `ArtistInfo`, skipping the `# AI detection` block).

- [ ] **Step 4: Run tests** — new file passes; then `pytest tests/unit/test_label_enrichment_schemas.py tests/unit/test_artist_enrichment_schemas.py -q` (existing suites must stay green — `ai_reasoning` gained a default, nothing else changed).
- [ ] **Step 5: Full suite** — `pytest -q`. Expected: all green (if an existing test constructs `LabelInfo`/`ArtistInfo` relying on `ai_reasoning` being required, update that test's expectation — the default is the intended new behavior per spec).
- [ ] **Step 6: Commit** — `git commit -m "feat(enrichment): request schemas without ai fields"`.

---

### Task 2: Prompts v4/v2_no_ai + registry defaults

**Files:**
- Create: `src/collector/label_enrichment/prompts/label_v4_no_ai.py`
- Create: `src/collector/artist_enrichment/prompts/artist_v2_no_ai.py`
- Modify: `src/collector/label_enrichment/prompts/__init__.py` (import in `load_builtin_prompts`, `_DEFAULT_PROMPT_SLUG = "label_v4_no_ai"`)
- Modify: `src/collector/artist_enrichment/prompts/__init__.py` (same pattern, default `artist_v2_no_ai`)
- Test: `tests/unit/test_enrichment_prompts_no_ai.py`

**Interfaces:**
- Produces: registered `PromptConfig` slugs `label_v4_no_ai` (v1) and `artist_v2_no_ai` (v1), `schema=LabelInfoRequest`/`ArtistInfoRequest`. Content = v3/v1 text minus every AI mention.

- [ ] **Step 1: Write the failing test**

```python
from collector.artist_enrichment.prompts import load_builtin_prompts as load_artist
from collector.artist_enrichment.prompts import get_prompt as get_artist
from collector.artist_enrichment.schemas import ArtistInfoRequest
from collector.label_enrichment.prompts import load_builtin_prompts as load_label
from collector.label_enrichment.prompts import get_prompt as get_label
from collector.label_enrichment.schemas import LabelInfoRequest


def test_no_ai_prompts_registered_with_request_schemas():
    load_label(); load_artist()
    lbl = get_label("label_v4_no_ai")
    art = get_artist("artist_v2_no_ai")
    assert lbl.schema is LabelInfoRequest
    assert art.schema is ArtistInfoRequest


def test_no_ai_text_anywhere():
    load_label(); load_artist()
    for cfg in (get_label("label_v4_no_ai"), get_artist("artist_v2_no_ai")):
        for text in (cfg.system, cfg.user_template):
            low = text.lower()
            assert "ai-content" not in low and "ai_" not in low
            assert "assess" not in low


def test_defaults_point_to_no_ai():
    from collector.label_enrichment import prompts as lp
    from collector.artist_enrichment import prompts as ap
    assert lp._DEFAULT_PROMPT_SLUG == "label_v4_no_ai"
    assert ap._DEFAULT_PROMPT_SLUG == "artist_v2_no_ai"
```

- [ ] **Step 2: Run to verify failure** — KeyError `label_v4_no_ai`.

- [ ] **Step 3: Implement.** `label_v4_no_ai.py`: copy `label_v3_app_fields.py` structure; system = `V2_SYSTEM_NO_AI + APP_FIELDS_BLOCK` where `V2_SYSTEM_NO_AI` is `label_v2_facts.SYSTEM` with the final line `"- ai_reasoning is required even if status is unknown — explain why."` removed (build it as `label_v2_facts.SYSTEM.rsplit("\n- ai_reasoning", 1)[0]` is fragile — instead copy the SYSTEM text verbatim minus that one bullet into this module as its own constant); `USER_TEMPLATE` = v3's minus the final sentence `"Then assess AI-content status and explain your reasoning."`; `register(PromptConfig(slug="label_v4_no_ai", version="v1", description="v3 app fields without AI-detection.", system=…, user_template=…, schema=LabelInfoRequest))`.
  `artist_v2_no_ai.py`: copy `artist_v1.py`; delete the `- AI detection: …` rule bullet from SYSTEM and the trailing `"Then assess AI-content status and explain your reasoning."` from USER_TEMPLATE; `schema=ArtistInfoRequest`, slug `artist_v2_no_ai`.
  Registries: add `from . import label_v4_no_ai  # noqa: F401` (resp. artist) inside `load_builtin_prompts`, switch `_DEFAULT_PROMPT_SLUG`.
- [ ] **Step 4: Run** new test + existing `tests/unit/test_*_prompts*.py` — green (existing prompts untouched).
- [ ] **Step 5: Full suite**, then commit — `git commit -m "feat(enrichment): no-ai prompt versions as defaults"`.

---

### Task 3: OpenAI adapter knobs + instrumentation + honest pricing

**Files:**
- Modify: `src/collector/label_enrichment/vendors/openai_gpt.py`
- Modify: `src/collector/label_enrichment/vendors/pricing.py`
- Modify: `src/collector/settings.py` (+2 fields), `src/collector/label_enrichment/orchestrator.py:build_adapters_from_run_config` and `src/collector/artist_enrichment/orchestrator.py` equivalent (pass-through), `src/collector/label_enrichment_handler.py` + `src/collector/artist_enrichment_handler.py` (supply settings values)
- Test: `tests/unit/test_openai_adapter_knobs.py`

**Interfaces:**
- Produces: `OpenAIAdapter(api_key, default_model, timeout_s, client=None, max_tool_calls: int | None = 3, reasoning_effort: str = "")`. `usage` gains `web_search_calls: int` and `reasoning_tokens: int`; `cost_usd` = token estimate + `web_search_calls * WEB_SEARCH_FEE_PER_CALL_USD`.
- `pricing.py` gains `WEB_SEARCH_FEE_PER_CALL_USD = 0.01` and `TAVILY_USD_PER_CREDIT = 0.008` (the latter consumed in Task 5/6).
- `settings.py` gains `openai_max_tool_calls: int = Field(default=3, alias="OPENAI_MAX_TOOL_CALLS")` and `openai_reasoning_effort: str = Field(default="", alias="OPENAI_REASONING_EFFORT")` on the enrichment settings class(es) actually read by the two handlers — locate the class each handler instantiates and add there; both handlers pass the values into `build_adapters_from_run_config`, which forwards them to `OpenAIAdapter` only.

- [ ] **Step 1: Write the failing test** (mock client pattern copied from the existing `tests/unit/test_label_enrichment_vendor_openai*.py` if present — reuse its fake-client fixture style; otherwise):

```python
from types import SimpleNamespace

from collector.label_enrichment.vendors.openai_gpt import OpenAIAdapter
from collector.label_enrichment.schemas import LabelInfoRequest


class FakeResponses:
    def __init__(self, raise_on_knobs=False):
        self.last_kwargs = None
        self.calls = 0
        self.raise_on_knobs = raise_on_knobs

    def parse(self, **kwargs):
        self.calls += 1
        self.last_kwargs = kwargs
        if self.raise_on_knobs and ("max_tool_calls" in kwargs or "reasoning" in kwargs):
            import openai
            raise openai.BadRequestError.__new__(openai.BadRequestError)
        parsed = LabelInfoRequest(label_name="X", summary="s", confidence=0.5)
        usage = SimpleNamespace(
            input_tokens=100, output_tokens=50,
            output_tokens_details=SimpleNamespace(reasoning_tokens=17),
        )
        output = [SimpleNamespace(type="web_search_call"),
                  SimpleNamespace(type="web_search_call"),
                  SimpleNamespace(type="message")]
        return SimpleNamespace(output_parsed=parsed, usage=usage, output=output, citations=[])


def make_adapter(fake):
    client = SimpleNamespace(responses=fake)
    return OpenAIAdapter(api_key="k", default_model="gpt-5.4-mini", client=client,
                         max_tool_calls=3, reasoning_effort="low")


def test_knobs_passed_and_usage_instrumented():
    fake = FakeResponses()
    resp = make_adapter(fake).run(system="s", user="u", schema=LabelInfoRequest)
    assert fake.last_kwargs["max_tool_calls"] == 3
    assert fake.last_kwargs["reasoning"] == {"effort": "low"}
    assert resp.usage["web_search_calls"] == 2
    assert resp.usage["reasoning_tokens"] == 17
    assert abs(resp.usage["cost_usd"] - (100/1e6*0.25 + 50/1e6*2.0 + 2*0.01)) < 1e-9


def test_empty_effort_not_sent_and_default_cap():
    fake = FakeResponses()
    client = SimpleNamespace(responses=fake)
    OpenAIAdapter(api_key="k", default_model="gpt-5.4-mini", client=client).run(
        system="s", user="u", schema=LabelInfoRequest)
    assert "reasoning" not in fake.last_kwargs
    assert fake.last_kwargs["max_tool_calls"] == 3


def test_bad_request_on_knobs_retries_bare():
    fake = FakeResponses(raise_on_knobs=True)
    resp = make_adapter(fake).run(system="s", user="u", schema=LabelInfoRequest)
    assert fake.calls == 2
    assert "max_tool_calls" not in fake.last_kwargs and "reasoning" not in fake.last_kwargs
    assert resp.error is None
```

- [ ] **Step 2: Run to verify failure** — TypeError (unexpected kwargs).
- [ ] **Step 3: Implement** in `openai_gpt.py`:
  - `__init__` takes `max_tool_calls: int | None = 3, reasoning_effort: str = ""`, stores them.
  - In `run`: build `kwargs = dict(model=…, input=…, instructions=…, tools=[{"type": "web_search"}], text_format=schema)`; if `self._max_tool_calls`: `kwargs["max_tool_calls"] = self._max_tool_calls`; if `self._reasoning_effort`: `kwargs["reasoning"] = {"effort": self._reasoning_effort}`. Call `responses.parse(**kwargs)`; on `openai.BadRequestError` when knobs were present, retry once with both knobs stripped (keep the existing never-raise outer contract for all other exceptions).
  - After parsing usage: `web_search_calls = sum(1 for item in output if getattr(item, "type", "") == "web_search_call")` (exact match — the experiment's substring match over-counts on future item types); `reasoning_tokens = getattr(getattr(usage, "output_tokens_details", None), "reasoning_tokens", 0) or 0`.
  - `cost = estimate_cost(...) + web_search_calls * WEB_SEARCH_FEE_PER_CALL_USD`; usage dict gains the two new keys (cells store usage jsonb — no migration).
  - `pricing.py`: add the two module constants with a comment (`# measured 2026-07: $10/1k web-search calls; tokens comped for gpt-5.4-mini under the data agreement — estimates kept in case it lapses`).
  - Wire-through: `build_adapters_from_run_config(..., openai_max_tool_calls: int = 3, openai_reasoning_effort: str = "")` → `OpenAIAdapter(...)`; both handlers read the two settings fields and pass them (find the handler call sites of `build_adapters_from_run_config` and add the kwargs).
- [ ] **Step 4: Run** new tests + existing vendor/orchestrator suites.
- [ ] **Step 5: Full suite**, commit — `git commit -m "feat(enrichment): cap web searches, instrument usage, honest cost"`.

---

### Task 4: `social_links.py` — port the proven socials module

**Files:**
- Create: `src/collector/social_links.py`
- Test: `tests/unit/test_social_links.py`

**Port sources (verbatim logic, adapt only as listed):** `experiments/enrichment_split/src/splitlab/social_regex.py` (patterns, `_CANON`, `extract_profiles`, `handle_of`, `validate_instagram_handle`, `_norm`), `tavily_client.py` (credit accounting), `facts_pass.py` lines with the tier-1/2/3 gating (`_known_official_urls`, tier conditions).

**Adaptations (exact):**
1. HTTP via `httpx.Client` (prod pattern; injectable for tests), not urllib: `TavilyClient(api_key, http: httpx.Client | None = None, timeout_s: float = 30.0)`; POST `https://api.tavily.com/{search,extract}` with the same payloads as the splitlab version; `credits_used` identical (basic=1, extract=ceil(n/5)).
2. **Validation on ALL tiers:** every candidate instagram handle — tier 1 and tier 2 included — passes `validate_instagram_handle(handle, entity_name, known_profiles)` before acceptance (splitlab validated tier 3 only; experiment measured tier-1 precision ≈86% without it).
3. **Relaxed short-name rule** in `validate_instagram_handle`: replace `if len(name) >= 5 and (name in h or h in name)` with `if len(name) >= 4 and (name in h or h in name)` (fixes rejected-but-correct `agrodnb`/"Agro", `eneimusique`/"Enei" from the experiment).
4. Twitter pattern: keep the anchored version from splitlab post-fix (`(?:^|[^a-z0-9.])(?:www\.)?(?:twitter|x)\.com/…`).
5. Public API:

```python
@dataclass
class SocialsResult:
    updates: dict[str, str]          # only fields that were empty and got a validated value
    instagram_tier: int | None       # 1/2/3 or None
    tavily_credits: int
    error: str | None = None


class SocialsResolver:
    def __init__(self, tavily_api_key: str, http: "httpx.Client | None" = None): ...
    def resolve(self, *, name: str, style: str, merged: dict) -> SocialsResult:
        """3-tier instagram-first resolution. Never raises. No-op result when
        merged already has instagram_url. Other social URL fields in `updates`
        only where merged's value is empty AND the regex found one on an
        official page (tier 1/2 content)."""
```

Tier flow (identical to splitlab `run_facts_pass` minus the LLM part): tier 1 = one basic search `f'"{name}" {style} {noun}'` (`noun` = `"record label"` / `"artist"` — caller passes `kind` via… add `kind: str` param to `resolve`), `include_raw_content=True`, `max_results=8` → `extract_profiles` over joined `content`/`raw_content`/`url` text → validate IG candidate; tier 2 = `extract()` over up to 5 official URLs from `merged` (`website`, `bandcamp_url`, `soundcloud_url`) if IG still missing → regex+validate; tier 3 = search with `include_domains=["instagram.com"]`, `max_results=5` → `handle_of` each result URL → first validated handle wins. All wrapped in one try/except → `SocialsResult(updates={}, error=str(exc))`.

- [ ] **Step 1: Write the failing test** — port `experiments/enrichment_split/tests/test_social_regex.py` (all 7 tests, adjusted imports) plus tier tests adapted from `tests/test_facts_pass.py` (fake `http` object with a `post(url, json=…)`-compatible stub returning queued responses), plus these two new behaviors:

```python
def test_tier1_candidate_rejected_without_validation_match():
    # search content contains an unrelated instagram link -> must NOT be accepted
    ...  # queue tier1 response with instagram.com/totally_other_act, expect fallthrough to tier2/3


def test_short_name_validation_relaxed():
    from collector.social_links import validate_instagram_handle
    assert validate_instagram_handle("agrodnb", "Agro", {})
    assert validate_instagram_handle("eneimusique", "Enei", {})
    assert not validate_instagram_handle("ugra.music1111", "Audiocore Production", {})
```

(Write the queued-response fake concretely in the test file; model it on splitlab's `tavily_with(responses)` helper.)
- [ ] **Step 2: Run to verify failure** — ImportError.
- [ ] **Step 3: Implement per the adaptations above.** Module docstring must name the port source and the experiment report as provenance.
- [ ] **Step 4: Run** `pytest tests/unit/test_social_links.py -q`.
- [ ] **Step 5: Full suite**, commit — `git commit -m "feat(collector): three-tier socials resolver ported from experiment"`.

---

### Task 5: Orchestrator integration (label + artist)

**Files:**
- Modify: `src/collector/label_enrichment/orchestrator.py` (`enrich_label_for_run`), `src/collector/artist_enrichment/orchestrator.py` (its enrich function)
- Modify: `src/collector/label_enrichment_handler.py`, `src/collector/artist_enrichment_handler.py` (construct `SocialsResolver` when `secrets.tavily_api_key` non-empty; pass into orchestrator; else pass `None`)
- Test: `tests/unit/test_enrichment_socials_postpass.py`

**Interfaces:**
- `enrich_label_for_run(..., socials_resolver: "SocialsResolver | None" = None)` (same for artist). After `merge_cells` and before `upsert_*_info`:

```python
    if socials_resolver is not None and not merged_info.instagram_url:
        socials = socials_resolver.resolve(
            kind="label", name=label_name, style=style, merged=merged_info.model_dump()
        )
        if socials.updates:
            merged_info = merged_info.model_copy(update=socials.updates)
            prov = meta.get("field_provenance") or {}
            for field in socials.updates:
                prov[field] = f"socials_tier{socials.instagram_tier}"
            meta["field_provenance"] = prov
        cost += socials.tavily_credits * TAVILY_USD_PER_CREDIT
```

(artist orchestrator: `kind="artist"`, artist name/style variables; place the cost addition before `increment_run_counters`.)

- [ ] **Step 1: Write the failing test** — drive `enrich_label_for_run` with the existing test-double pattern from `tests/unit/test_label_enrichment_orchestrator*.py` (reuse its fakes for repository/adapters/merge client) plus a fake resolver; assert: (a) resolver NOT called when merged already has instagram; (b) called and updates applied + provenance `socials_tier3` + credits added to `cost_delta` when instagram empty; (c) resolver returning `updates={}` leaves merged/provenance untouched; (d) `socials_resolver=None` keeps old behavior byte-for-byte. Mirror one (b)-style test for the artist orchestrator.
- [ ] **Step 2: Run to verify failure.**
- [ ] **Step 3: Implement** exactly the block above in both orchestrators + handler wiring (resolver built once per invocation: `SocialsResolver(secrets.tavily_api_key)` if the key is non-empty else `None`).
- [ ] **Step 4: Run** new + existing orchestrator suites.
- [ ] **Step 5: Full suite**, commit — `git commit -m "feat(enrichment): socials post-pass fills missing instagram"`.

---

### Task 6: Frontend — hide AI surfaces

**Files:**
- Modify: `frontend/src/features/library/components/{LabelTile,ArtistTile,LabelDetailHeader,ArtistDetailHeader}.tsx` (remove `AiContentBadge` import + usage)
- Modify: `frontend/src/features/library/components/{LabelsTable,ArtistsTable}.tsx` (remove the AI column: the `aiContent` const and its cell/header)
- Modify: `frontend/src/features/playlists/components/PlaylistPlayerPanel.tsx` (remove the `is_ai_suspected` badge block at ~line 166)
- Keep: `frontend/src/features/library/lib/aiContent.tsx` (unused module stays; revert = git)
- Test: update the affected tests under `__tests__/` (remove/adjust assertions that expect AI badges/columns)

- [ ] **Step 1:** For each file, delete the AI-surface JSX + now-unused imports/consts. Search first: `grep -rn "AiContentBadge\|is_ai_suspected\|aiContent" frontend/src --include="*.tsx" | grep -v __tests__ | grep -v aiContent.tsx` — every hit outside `aiContent.tsx` must be gone when you finish.
- [ ] **Step 2:** Update tests: `grep -rn "AiContentBadge\|is_ai_suspected\|AI" frontend/src/features/library/components/__tests__ frontend/src/features/library/routes/__tests__ frontend/src/features/playlists/components/__tests__` — drop the assertions that render/expect AI badges; keep the rest of each test intact.
- [ ] **Step 3: Gates** — `cd frontend && pnpm typecheck && pnpm lint && pnpm test`. All three must pass (unused-import lint will catch leftovers).
- [ ] **Step 4: Commit** — `git commit -m "feat(admin): hide ai-detection surfaces in library and player"`.

---

### Task 7: Analytics scripts

**Files:**
- Create: `scripts/enrichment_stats.py`
- Create: `scripts/openai_usage_report.py`
- Test: `tests/unit/test_enrichment_stats_shaping.py` (pure shaping helpers only — no AWS/OpenAI calls in tests)

**Interfaces:**
- `enrichment_stats.py`: boto3 `rds-data` (ARNs via `--cluster-arn/--secret-arn` flags with env fallbacks `CLOUDER_CLUSTER_ARN`/`CLOUDER_SECRET_ARN`; `--database clouder`). Prints per month and per kind: cells, avg input/output tokens, avg `web_search_calls`, avg `tavily_credits` (jsonb keys may be absent on old rows — `coalesce`), avg cost, latency, error count, and instagram fill-rate of `clouder_label_info`/`clouder_artist_info`. SQL: adapt the queries used for the baseline tables in the design spec (grep them from `docs/superpowers/specs/2026-07-15-enrichment-cost-instagram-design.md` "Baseline" and the report). Structure: `fetch(sql) -> list[dict]` thin wrapper + pure `shape_*` functions (tested) + `main()`.
- `openai_usage_report.py`: stdlib urllib; `OPENAI_ADMIN_KEY` env (die with a clear message naming the required `api.usage.read` scope); pulls `/v1/organization/costs?group_by=line_item,project_id` and `/v1/organization/usage/completions?bucket_width=1d&group_by=model,project_id` since `--since YYYY-MM-DD` (default: first of last month); prints USD by month×line-item (quantities included) and tokens/requests by month×model. Port the pagination + aggregation from this session's phase-0 pull (documented in `2026-07-15-enrichment-openai-usage-analysis.md` "Reproducing"); pure `aggregate_costs(buckets)`/`aggregate_usage(buckets)` helpers (tested with fixture bucket dicts).

- [ ] **Step 1: failing tests** for the pure helpers (fixture rows/buckets → expected aggregates; include a cost result with `"amount": {"value": "0E-6176"}` to pin decimal-string parsing).
- [ ] **Step 2:** verify failure; **Step 3:** implement; **Step 4:** `pytest tests/unit/test_enrichment_stats_shaping.py -q` then full suite.
- [ ] **Step 5: Live smoke (read-only):** `PYTHONPATH=src .venv/bin/python scripts/enrichment_stats.py --months 3` against prod (aws CLI creds; Aurora may need one resume retry) — output sane numbers; `OPENAI_ADMIN_KEY=$(grep '^OPENAI_ADMIN_KEY=' experiments/artists/.env | cut -d= -f2-) .venv/bin/python scripts/openai_usage_report.py` — matches the phase-0 analysis shape. Paste both outputs into the task report file (not the repo).
- [ ] **Step 6: Commit** — `git commit -m "feat(scripts): enrichment stats + openai usage reports"`.

---

### Task 8: Rollout prep + verification

**Files:**
- Modify: `docs/backend/` — add a short section to the most fitting existing doc (grep `docs/backend/` for the enrichment doc; if none, `docs/backend/enrichment.md` may not exist — then add to `docs/backend/gotchas.md`): socials post-pass (when it fires, tiers, validation, provenance `socials_tier{N}`, Tavily fee accounting), the `max_tool_calls`/`OPENAI_*` knobs, and the rollback line (`prompt_slug` switch).
- No code.

- [ ] **Step 1:** Write the doc section (≤30 lines, follow the doc's existing tone).
- [ ] **Step 2:** Full verification battery: `pytest -q` (repo root) AND `cd frontend && pnpm typecheck && pnpm lint && pnpm test`.
- [ ] **Step 3:** Commit — `git commit -m "docs(backend): socials post-pass and enrichment knobs"`.
- [ ] **Step 4:** STOP — deploy (`scripts/package_lambda.sh` + terraform), `auto_enrich_config` prompt_slug switch, and the one manual prod run per kind are OWNER-GATED: report readiness instead of executing them.

## Rollout (after merge — owner-gated, not part of the tasks)

1. Deploy lambdas (`scripts/package_lambda.sh`, `cd infra && terraform apply`).
2. Switch `auto_enrich_config.prompt_slug` → `label_v4_no_ai` / `artist_v2_no_ai` (admin route or SQL UPDATE); vendors stay `["openai"]`.
3. One manual enrichment per kind from the admin UI; check the run's cells show `web_search_calls`≤3±, `tavily_credits` when IG was missing, cost populated.
4. After ~1 week: `scripts/enrichment_stats.py` + `scripts/openai_usage_report.py` vs the experiment report's tables; decide whether to keep `max_tool_calls=3`.
5. Rollback if needed: switch `prompt_slug` back (v3/v1 still registered); socials post-pass disables by emptying the Tavily key or reverting the handler wiring commit.

## Self-Review Notes

- Addendum coverage: №1 prompts/schemas → Tasks 1-2; №2 knobs → Task 3; №3 socials → Tasks 4-5; №4 instrumentation/pricing → Task 3, frontend → Task 6, scripts → Task 7; rollout → Task 8 + section above.
- Deliberately referenced-not-inlined: ArtistInfoRequest field list (copy of ArtistInfo minus ai block — Task 1 names the exact rule and the test pins it), splitlab port sources (proven code, named files), existing test-double patterns (named suites to mirror). Everything else inlined.
- Type consistency: `SocialsResult.updates`/`instagram_tier`/`tavily_credits` (Task 4) match Task 5's integration block; `TAVILY_USD_PER_CREDIT`/`WEB_SEARCH_FEE_PER_CALL_USD` defined in Task 3, consumed in Task 5; `build_adapters_from_run_config` kwargs named identically in Tasks 3.

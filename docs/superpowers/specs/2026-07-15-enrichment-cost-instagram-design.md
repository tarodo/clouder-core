# Enrichment cost reduction + Instagram discovery — design

**Date:** 2026-07-15 (reworked same day after the usage analysis and owner decisions; original approach M superseded by the two-pass split below)
**Status:** approved direction, pending owner review of this revision
**Companion:** `2026-07-15-enrichment-openai-usage-analysis.md` (phase 0 deliverable — measured facts used throughout)
**Scope:** label + artist enrichment (`src/collector/label_enrichment/`, `src/collector/artist_enrichment/`), library/player frontend surfaces, an offline experiment in `experiments/`, analytics scripts.

## Goals

1. Make enrichment cheaper per run — volume grows ~4× next month (~2 000 runs/month).
2. Turn OFF AI-content detection reversibly: stop asking vendors for it, hide it on the frontend.
3. Make Instagram (and other concrete-field) discovery reliable instead of best-effort.
4. Prove the new pipeline in `experiments/` on real prod entities **before** any prod implementation.

## Hard constraints (owner decisions)

- **No scraping on our infrastructure.** Page content may only come from providers that fetch on their side (Tavily `include_raw_content`). The earlier idea of a Lambda-side httpx page fetcher is dropped.
- Reversible AI-detection disable — no schema/DB field deletion, no migrations.
- Vendors stay configurable via `auto_enrich_config`; rollback = config switch.

## Measured facts (2026-07-15, see companion analysis)

- gpt-5.4-mini **tokens are $0** under the org's data-sharing agreement (27M+ tokens, three months, $0.00). Token-based estimates in `pricing.py` describe money not actually spent.
- **Web search tool calls are the entire production bill**: $0.01/call, no free allowance. Stable **3.41–3.43 searches/run → $0.034/run**, ~$17/month at June volume, ~$68/month at 4×.
- Usage API cross-check matches prod cells exactly (June: 500 vs 498).
- Current label field fill-rates (505 labels) — the quality bar for the experiment gate:
  tagline 99%, notable_artists 95%, country 85%, releases_12m 72%, founded_year 67%, website 54%, catalog_size 52%, distribution 51%, bandcamp 50%, discogs_url 24%.
- `instagram_url` missing: labels 56%, artists 70%.

## Design

### 1. Two-pass enrichment (the core change)

One entity run = two independent passes producing two cells; the existing deterministic `merge_cells` aggregator combines them (fields do not overlap, so no narrative-merge LLM call is needed).

**Pass 1 — narrative (OpenAI, agentic web_search).**
- New prompts `label_v4_narrative` / `artist_v2_narrative`; request schemas contain ONLY narrative/fuzzy fields: tagline, summary, bio (artists), primary_styles, notable_artists / notable_collaborators / notable_releases, aliases, real_name/members (artists), status, country, confidence, sources, notes.
- **No URLs and no numeric fields in the request schema** — structured output stops forcing the model to research them, so its searches go entirely to the description. No AI-detection block anywhere.
- `max_tool_calls=2` at launch; the experiment tests whether cap 1 holds quality. `reasoning.effort` — optional latency knob only (tokens are free; it saves no money).

**Pass 2 — facts (Tavily search + free extraction, no agentic search).**
- 1 Tavily **basic** search ($0.008) with `include_raw_content`, domain-biased (discogs.com, bandcamp.com, wikipedia.org + general), query templated from entity name/style (same pattern as the existing `tavily_deepseek` adapter).
- From `raw_content`: **social/profile URLs extracted by regex** (instagram, twitter/x, soundcloud, bandcamp, beatport, RA, discogs, website) — deterministic, $0.
- Numeric + factual fields (founded_year, catalog_size_estimate, releases_last_12_months, last_release_date, distribution, parent/sublabels, artist labels, active_since) extracted by **gpt-5.4-mini without web_search** (tokens $0) from the fetched content, with mandatory source URLs; никаких догадок — null when unsourced.
- **Tier 2 — Tavily Extract on known pages:** if the regex found no instagram, feed the already-known official URLs (website/bandcamp from this run's results or from the existing DB row) to Tavily **Extract** (`/extract`, 1 credit per 5 URLs — Tavily fetches, not us) and regex its `raw_content`. A link on the entity's own page is authoritative.
- **Tier 3 — targeted top-up:** if still missing, one Tavily query restricted to `instagram.com` ($0.008). Results are noisy → accept only with validation: normalized handle-vs-name similarity, or a **cross-network handle match** (e.g. soundcloud.com/`audiocorestudio` ↔ instagram.com/`audiocorestudio`). Otherwise null.
- Live pilot (2026-07-15, 3 prod labels with IG missing): Defiant found at tier 1, Anarkick at tier 2 (confirmed by tier 3), Audiocore validated candidate at tier 3 — 3/3 vs 0/3 in prod, ~$0.07 total.
- Implemented as a new vendor adapter (working name `tavily_facts`) so cells/runs/admin UI machinery works unchanged; artist and label share it like they share the other adapters.

**Merge.** Existing `merge_cells` merges the two cells deterministically. Provenance shows which pass produced each field. Single-parseable-cell and all-failed paths behave as today.

**Why not Brave (considered, rejected):** $5/1k is cheaper per query, but Brave returns search snippets only — it cannot source numeric fields, and covering them would still require Tavily or our own scraping. Its only niche (cheaper Instagram top-up) saves ~$2–3/month at 4× volume — not worth a second provider, key, and adapter.

### 2. AI detection off — reversible

- Neither pass's request schema contains `ai_content` / `ai_signals` / `ai_reasoning`; no prompt text mentions AI detection.
- Storage models keep the fields; `ai_reasoning` becomes `str = ""` so payloads without ai keys validate via defaults. Aggregator and `project_ai_suspected` untouched (with `ai_content=unknown` nothing gets flagged).
- Rollback = switch `auto_enrich_config.prompt_slug`/vendors back to `label_v3_app_fields` / `artist_v1` + openai.

### 3. Frontend — hide AI surfaces

Remove usage (components stay; revert via git): `AiContentBadge` in `LabelTile`, `ArtistTile`, `LabelDetailHeader`, `ArtistDetailHeader`; AI columns in `LabelsTable`/`ArtistsTable`; `is_ai_suspected` badge in `PlaylistPlayerPanel`. `aiContent.tsx` remains as an unused module. Update tests; run the full local gate (typecheck + lint + test).

### 4. Instrumentation + honest pricing

- OpenAI adapter: extract count of `web_search_call` output items → `usage["web_search_calls"]`; `output_tokens_details.reasoning_tokens` → `usage["reasoning_tokens"]`. `max_tool_calls` + `reasoning` params from settings env (`OPENAI_MAX_TOOL_CALLS`, `OPENAI_REASONING_EFFORT`), defensive drop-and-log if the model rejects a knob.
- `tavily_facts` adapter: record credits used → `usage["tavily_credits"]`.
- `pricing.py`: `WEB_SEARCH_FEE_PER_CALL_USD = 0.01` (measured), `TAVILY_USD_PER_CREDIT = 0.008` ($8/1k, owner's plan). `cost_usd` = token estimate + search fees, so run counters and admin UI show true cost. (Token component is currently comped for gpt-5.4-mini; keep it in the estimate in case the agreement lapses.)

### 5. Experiment gate (prove it before prod)

New sandbox `experiments/enrichment_split/` (pattern of `experiments/artists/`, keys from `experiments/artists/.env`: `OPENAI_API_KEY`, `TAVILY_API_KEY`). **No prod code changes until this gate passes.**

- **Sample:** 50 labels + 50 artists pulled from prod via RDS Data API — stratified: half where `instagram_url` is currently null (prove the fix), half random (prove no regression). Existing prod `merged` payloads ship with the sample as the comparison baseline.
- **Run:** the two-pass pipeline exactly as specced (narrative cap 2 AND cap 1 variants; facts pass with top-up), fully local, writing per-entity JSON cells + a summary.
- **Metrics vs baseline:** per-field fill-rate (table above), instagram found-rate + manual spot-check of ~20 handles for correctness, numeric fields sourced-rate, measured cost/run (search calls + credits), latency, and **tier fire-rates** (share of entities resolved at tier 1 / 2 / 3) — this pins the real average credits/entity for the cost model (facts pass ranges 1–2.5 credits depending on tiers fired).
- **Pass thresholds:** narrative fields not worse than baseline (tagline ≥95%, notable ≥90%); instagram found ≥60% overall (vs 44%/30% today) with ≥90% spot-check correctness; founded_year/catalog_size not worse than baseline; measured cost ≤ $0.025/run (cap 2) — and record the cap-1 numbers for the post-rollout decision.
- **Budget:** ~100 entities × ≤$0.04 ≈ **$4**. Report lands in `docs/superpowers/specs/` as `<run-date>-enrichment-split-experiment-report.md` with go/no-go.
- **If it fails:** fall back to mono-OpenAI optimization (no AI block + cap 3 ≈ $44–50/month at 4×), Tavily used only for the Instagram top-up.

### 6. Analytics scripts

- `scripts/enrichment_stats.py` — RDS Data API: per-month cells, tokens, cost, latency, errors, `web_search_calls`/`tavily_credits` (once instrumented), instagram null-rate, per-field fill-rates (the baseline queries from this spec, made repeatable).
- `scripts/openai_usage_report.py` — org Costs + Usage APIs (`OPENAI_ADMIN_KEY`, needs `api.usage.read`), grouped by line item/model/project: real billed cost, web_search line, cross-check vs prod cells.

### 7. Testing

- Unit: narrative/facts request schemas (no ai/url/numeric leakage between passes); storage models validate payloads without ai keys; prompts registered; OpenAI adapter knobs + `web_search_calls`/`reasoning_tokens` extraction (mock client); `tavily_facts` — query building, regex URL extraction on raw-content fixtures (bandcamp page, label site, page with post-links only), numeric extraction plumbing (mock LLM), top-up trigger; pricing with both fees; merge of the two non-overlapping cells + provenance.
- Frontend: tests asserting AI badges/columns gone; full local gate.
- Post-deploy: one manual run per kind; `enrichment_stats.py` after ~1 week vs baseline; decide cap 2 → cap 1 from prod data + experiment's cap-1 evidence.

## Cost model (2 000 runs/month = 4× June)

| Scenario | $/run | $/month |
|---|---:|---:|
| Status quo (3.4 OpenAI searches) | 0.034 | **$68** |
| Mono-OpenAI fallback (no AI block, cap 3) | 0.022–0.025 | $44–50 |
| Two-pass, OpenAI cap 2 + Tavily basic (+IG top-up ~30%) | ~0.030 | $60 |
| **Two-pass, OpenAI cap 1 + Tavily basic (+top-up)** | ~0.020 | **$41** |

The dollar lever is the OpenAI cap; the split's main value is deterministic, provider-priced coverage of concrete fields (the Instagram pain) and predictable per-run cost. Launch at cap 2, move to cap 1 when narrative quality is confirmed.

## Rollout order

1. ~~Phase 0 — measure~~ **done**: usage analysis committed; fees pinned ($0.01/search, $0.008/credit).
2. **Experiment gate** (§5): build sandbox, run 50+50, publish report, go/no-go.
3. Prod implementation (§1, §2, §4): prompts, schemas, `tavily_facts` adapter, knobs, instrumentation.
4. Frontend hide (§3).
5. Switch `auto_enrich_config` (vendors + prompt slugs) — both kinds.
6. Re-measure with `enrichment_stats.py` + `openai_usage_report.py` after a week; decide cap 1.

## Alternatives considered

- **Brave Search** — rejected: snippets-only (can't source numbers), niche saving ~$2–3/month, extra provider/key/adapter.
- **Own scraping (Lambda httpx fetcher)** — rejected by owner: no scraping on our infrastructure; Tavily raw content replaces it.
- **Full BYO search (drop OpenAI web_search entirely, ~$32/month)** — deferred: risks artist disambiguation quality; revisit with experiment data if the facts pass proves strong.
- Backfill of Instagram for already-enriched entities — natural follow-up: rerun the facts pass alone over existing rows once precision is confirmed (cheap: $0.008–0.016/entity, no narrative pass needed).

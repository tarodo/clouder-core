# Enrichment cost reduction + Instagram discovery — design

**Date:** 2026-07-15
**Status:** approved (approach M of S/M/L)
**Scope:** label + artist enrichment (`src/collector/label_enrichment/`, `src/collector/artist_enrichment/`), library/player frontend surfaces, analytics scripts.

## Goals

1. Make label/artist enrichment cheaper per run.
2. Turn OFF AI-content detection ("is this an AI-generated label/artist?") — reversibly: stop asking vendors for it, hide it on the frontend. No destructive removal.
3. Make Instagram link discovery persistent — today it is frequently null even when the account exists.

## Non-goals

- No vendor removal or re-selection (production config is already OpenAI-only; vendors stay configurable).
- No Brave Search adapter in this iteration (deferred; see "Deferred" below).
- No DB migrations, no deletion of `ai_*` columns/fields from storage.
- No dropping of product-visible response fields (schema slimming beyond the `ai_*` request fields is an L-item, decided after analytics).

## Baseline (prod DB, measured 2026-07-15)

Source: `clouder_label_enrichment_cells`, `clouder_artist_enrichment_cells`, `clouder_label_info`, `clouder_artist_info` via RDS Data API.

| Metric | Labels | Artists |
|---|---|---|
| Cells total (May–Jul) | 505 | 494 |
| Volume, Jun / Jul-to-date | 146 / 38 | 352 / 129 |
| OpenAI avg input / output tokens | 16 401 / 707 | 19 867 / 1 063 |
| OpenAI avg token cost per run | $0.0057 | $0.0071 |
| OpenAI avg latency | 29.5 s (incl. May-era) | 12.7 s |
| OpenAI errors | 106, **all 2026-05**; 0 since June | 0 |
| `instagram_url` missing | 284/505 (56%) | 344/494 (70%) |
| …of which website/bandcamp/soundcloud present | 213 (75%) | 279 (81%) |

Key implications:

- Token cost is small (~$3/month at ~480 runs/month). The **unmeasured** cost is web_search tool fees: `pricing.py` counts tokens only. At the published $10/1k-call rate and 3–5 searches/run that is $15–25/month — 5–8× the visible cost. The owner has an OpenAI agreement that may zero this line; phase 0 verifies it via the Costs API.
- The huge input-token count is web-search content injected by OpenAI; capping tool calls cuts input tokens too.
- 75–81% of Instagram gaps are addressable deterministically from already-found official pages.

## Design

### 1. AI detection off — reversible

- New prompt versions: `label_v4_no_ai` and `artist_v2_no_ai`, derived from `label_v3_app_fields` / `artist_v1` with the AI-assessment text removed from both `system` and `user_template` ("Then assess AI-content status…", the `ai_reasoning` rule, the AI-detection rule block).
- **Request schemas** (the part that actually stops the spend): structured output forces the model to fill every schema field, so removing prompt text alone is not enough. New Pydantic models `LabelInfoRequest` / `ArtistInfoRequest` = current models minus `ai_content`, `ai_signals`, `ai_reasoning`. `PromptConfig.schema` for the new prompts points at the request models.
- **Storage models** (`LabelInfo`, `ArtistInfo`) keep all fields; `ai_reasoning` changes from required to `str = ""` so that request-model payloads (no ai keys) validate into storage models via defaults (`ai_content=unknown`, `ai_signals=[]`).
- Aggregator, repository, `project_ai_suspected` are untouched. With `ai_content=unknown` the projection flags nothing.
- **Switch**: update `auto_enrich_config.prompt_slug` (both kinds) to the new slugs and update the defaults payload in `label_enrichment/routes.py` (and artist equivalent). **Rollback** = set `prompt_slug` back to `label_v3_app_fields` / `artist_v1`.

### 2. Frontend — hide AI surfaces

Remove usage (components stay in the codebase; revert via git):

- `AiContentBadge` usage in `LabelTile`, `ArtistTile`, `LabelDetailHeader`, `ArtistDetailHeader`.
- AI column in `LabelsTable`, `ArtistsTable`.
- `is_ai_suspected` badge in `PlaylistPlayerPanel`.
- `frontend/src/features/library/lib/aiContent.tsx` remains (unused module).
- Update affected tests; run the full local CI gate (typecheck + lint + test).

### 3. OpenAI call knobs

In `OpenAIAdapter.run` (`label_enrichment/vendors/openai_gpt.py`), pass:

- `reasoning={"effort": settings.openai_reasoning_effort}` — default `"low"`.
- `max_tool_calls=settings.openai_max_tool_calls` — default `4`.

Both come from `settings.py` env vars (`OPENAI_REASONING_EFFORT`, `OPENAI_MAX_TOOL_CALLS`) wired through both label and artist handlers (shared adapter), tunable without code changes. If the model family rejects a knob, the adapter drops it and logs once (defensive, same never-raise contract).

### 4. Instrumentation + honest pricing

- Adapter extracts from the Responses payload: count of output items with `type == "web_search_call"` → `usage["web_search_calls"]`; `usage.output_tokens_details.reasoning_tokens` → `usage["reasoning_tokens"]`. Cells `usage` is jsonb — no migration.
- `pricing.py` gains `WEB_SEARCH_FEE_PER_CALL_USD` (default `0.01` = published $10/1k; set to the measured value — possibly `0.0` — after phase 0). Adapter adds `web_search_calls × fee` into `usage["cost_usd"]`, so run counters and the admin UI show true cost.

### 5. Instagram fallback (no LLM)

New shared module `src/collector/social_links.py`:

- `extract_instagram_url(html: str) -> str | None` — regex for `instagram.com/<handle>` profile links, excluding non-profile paths (`/p/`, `/reel/`, `/explore/`, `/stories/`); normalizes to `https://www.instagram.com/<handle>`.
- `resolve_instagram(merged: dict, http: httpx.Client) -> str | None` — fetch order: `website` → `bandcamp_url` → `soundcloud_url` (first hit wins). If a page has no IG link but links a link-hub (`linktr.ee`, `lnk.bio`, `linkin.bio`, `linkfire`), fetch that too (depth 1). Limits: ≤3 entity pages + 1 link-hub, 5 s timeout each, 500 KB read cap, explicit User-Agent, all errors swallowed (best-effort, never fails the run).
- Trust model: an Instagram link published on the entity's own official page is authoritative — no name-similarity check.
- Orchestrators (label + artist): after `merge_cells`, if `merged.instagram_url` is empty, call `resolve_instagram`; on success set `merged.instagram_url` and `field_provenance["instagram_url"] = "site_extraction"` before the existing `upsert_*_info`. Single write, no schema change.
- Prompt side: replace "Leave null when uncertain" for socials with: verify the official site / link-hub, run one targeted search `"<name> instagram"`, and only then leave null. Precision requirement ("official accounts only") stays.

### 6. Analytics scripts

- `scripts/enrichment_stats.py` — boto3 RDS Data API (cluster/secret ARNs via env or flags): per-month cells, tokens, cost, latency, error rate, `web_search_calls` (once instrumented), and `instagram_url` null-rate for both kinds. This reproduces the baseline table above and is re-run after rollout.
- `scripts/openai_usage_report.py` — OpenAI org endpoints (`/v1/organization/usage/completions`, `/v1/organization/costs`, grouped by line item/model) using `OPENAI_ADMIN_KEY` env. Shows real billed cost, the web_search line item (verifies the free-search agreement), token breakdown incl. reasoning and cached tokens.
- Prerequisite: an OpenAI **admin/restricted key with `api.usage.read`**. The key currently in `experiments/artists/.env` (`OPENAI_API_KEY`) lacks the scope — verified 2026-07-15 (org endpoints return "Missing scopes: api.usage.read").

### 7. Testing

- Unit: request schemas exclude `ai_*`; storage models validate payloads without ai keys; new prompts registered and AI-free; adapter passes `reasoning`/`max_tool_calls` and extracts `web_search_calls`/`reasoning_tokens` (mock client); pricing includes the search fee; `extract_instagram_url` on HTML fixtures (official site, bandcamp page, linktree page, page without IG, page with post-links only); `resolve_instagram` fetch-order and limits with a mock client; orchestrator wires the fallback + provenance.
- Frontend: update tests asserting AI badges/columns are gone; full local gate (typecheck + lint + test).
- Post-deploy verification: one manual enrichment run per kind; `enrichment_stats.py` re-run after ~1 week and compared to the baseline table.

## Rollout order

1. **Phase 0 — measure**: obtain the `api.usage.read` key, run `openai_usage_report.py`, pin `WEB_SEARCH_FEE_PER_CALL_USD` to the measured value; commit `enrichment_stats.py` (baseline already captured above).
2. Backend: prompts + request schemas + adapter knobs + instrumentation (sections 1, 3, 4).
3. Frontend hide (section 2).
4. Instagram fallback (section 5).
5. Switch `auto_enrich_config.prompt_slug`; re-measure after a week.

## Deferred (explicitly out of scope)

- **Brave Search**: candidate second-tier Instagram fallback (`site:instagram.com "<name>"` for the ~70 labels / ~65 artists with no official page found) and possible Tavily replacement. Free tier (2k queries/month) covers current volume. Decide after phase 0 shows whether OpenAI search is actually free under the owner's agreement.
- `service_tier: "flex"`, response-schema slimming, Tavily `SOCIAL_DOMAINS` instagram fix (only relevant if the Tavily vendor returns).
- Backfill of Instagram links for already-enriched entities (the fallback runs on new/re-runs only; a one-off backfill script can reuse `resolve_instagram` and is a natural follow-up once precision is confirmed).

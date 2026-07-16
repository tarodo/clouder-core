# Enrichment OpenAI usage & cost analysis — 2026-07-15

**Companion to:** `2026-07-15-enrichment-cost-instagram-design.md` (this is its phase 0 deliverable).
**Sources:** OpenAI org Costs API + Usage API (admin key, `api.usage.read`), window 2026-05-01 → 2026-07-15; prod Aurora (`clouder_*_enrichment_cells`, `clouder_*_info`) via RDS Data API.
**Org:** single project ("Default project"); May also contains non-prod sandbox runs from `experiments/artists/` (gpt-5).

## Headline findings

1. **Model tokens cost $0.** Under the org's data-sharing agreement, every gpt-5.4-mini line item (input, cached input, output) bills at $0.00 in all three months — 27M+ tokens, $0. The token-cost estimates in `pricing.py` and the admin UI (`avg ≈ $0.006/run`) describe money that is not actually being spent.
2. **Web search tool calls are the entire production bill: $10.00 per 1 000 calls, no free allowance.** May $15.68 / Jun $16.99 / Jul-to-date $5.73 — in June and July web search is 100% of total org spend.
3. **Stable 3.4 searches per enrichment run** (June: 1 699 searches / 498 runs; July: 573 / 167). Cost per run ≈ **$0.034**, i.e. ~$17/month at June volume — ~6× the "visible" token estimate.
4. Usage API cross-check matches prod exactly: June 500 model requests vs 498 prod cells; July 168 vs 167. May's extra spend ($5.25 tokens + part of searches) is the gpt-5 sandbox, not prod.

## Costs by month (line items, USD)

| Line item | 2026-05 | 2026-06 | 2026-07 (to 15th) |
|---|---:|---:|---:|
| gpt-5 tokens (sandbox experiments) | $5.25 | — | — |
| gpt-5.4-mini input | $0.00 (3.92M tok) | $0.00 (7.70M) | $0.00 (2.58M) |
| gpt-5.4-mini cached input | $0.00 (1.32M) | $0.00 (2.39M) | $0.00 (0.81M) |
| gpt-5.4-mini output | $0.00 (0.23M) | $0.00 (0.50M) | $0.00 (0.17M) |
| **web search tool calls** | **$15.68** (1 568) | **$16.99** (1 699) | **$5.73** (573) |
| **Total** | **$20.93** | **$16.99** | **$5.73** |

## Per-run economics (prod, gpt-5.4-mini)

| Metric | 2026-06 | 2026-07 |
|---|---:|---:|
| Enrichment runs (label + artist cells) | 498 | 167 |
| Model requests (Usage API) | 500 | 168 |
| Web searches | 1 699 | 573 |
| **Searches / run** | **3.41** | **3.43** |
| **Cost / run** | **$0.0341** | **$0.0343** |
| Input tokens / run (incl. cached) | 20.3k | 20.2k |
| Cached input share | 24% | 24% |
| Output tokens / run | 1 006 | 1 039 |

## Implications for the design (amendments to the approved spec)

- **`WEB_SEARCH_FEE_PER_CALL_USD = 0.01` — confirmed.** Instrumented `cost_usd` should be `web_search_calls × 0.01` **plus** token estimate; the report should note tokens are currently comped so the search component is the real number.
- **`max_tool_calls` is the only lever that saves money.** Average is 3.4; a cap of 3 bounds every run at ≤$0.03 and trims the tail. `reasoning.effort=low` saves $0 (tokens are free) — keep it only as an optional latency knob, not a cost measure.
- **AI-block removal now matters for searches, not tokens:** the AI assessment is a distinct research question that plausibly costs ~0.5–1 search/run. Expected combined effect (no AI block + cap 3): **~2–2.5 searches/run → ~$10–12.5/month at June volume (−30–40%)**, before any volume growth.
- **Do NOT add a forced "search `<name> instagram`" instruction to the prompt.** Each such search costs $0.01 and would fire in the 56–70% of runs where IG is missing — it would *raise* spend for a low-yield method. Instagram persistence should come from the free tiers instead:
  1. deterministic extraction from already-found official pages ($0, covers 75–81% of gaps — see design spec §5);
  2. **Brave Search free tier** (2 000 queries/month ≫ our ~300 gap-queries/month) as the second tier for entities with no official page — this is now justified by data and should be promoted from "deferred" into the implementation plan;
  3. prompt text limited to: check link-hubs already present in fetched results; no extra search calls.

## Recommendation summary

| Change | Monthly effect (June volume) |
|---|---|
| Remove AI block from prompts + request schema | −$3…−5 (fewer searches) + free tokens saved don't matter |
| `max_tool_calls = 3` | bounds bill at ≤$15; realistic −$2…−4 |
| Deterministic IG fallback + Brave free tier | +0$ spend; IG coverage from 44%/30% → ~85%+ |
| `reasoning.effort` | $0 — optional latency knob only |
| Expected bill | **~$17 → ~$10–12/month** at current volume, with better IG coverage |

## Reproducing

- OpenAI side: `scripts/openai_usage_report.py` (planned in design §6) — org Costs API `group_by=line_item,project_id` + Usage completions `group_by=model,project_id`, `OPENAI_ADMIN_KEY` env (needs `api.usage.read`; the project key does not have it).
- DB side: `scripts/enrichment_stats.py` (planned in design §6) — cells/info tables; baseline tables live in the design spec.

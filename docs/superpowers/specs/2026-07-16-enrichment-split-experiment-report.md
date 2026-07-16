# Enrichment split experiment — report & go/no-go

**Date:** 2026-07-16
**Spec:** `2026-07-15-enrichment-cost-instagram-design.md` §5 (experiment gate)
**Sample:** 50 labels + 50 artists from prod (`experiments/enrichment_split/sample/sample.yaml`), stratified 25 IG-missing + 25 random per kind.
**Runs:** cap 2 → `20260715-212849-239f` (7 transient timeouts retried once, then 100/100 ok); cap 1 → `20260716-035040-e51f` (100/100 ok, no retries needed). One earlier cap-2 attempt died at 26/100 for infrastructure reasons (runner process killed with its controlling session, not a pipeline defect) and was restarted from scratch.

## Verdict: NO-GO for the full two-pass replacement. GO for two of its parts.

| Component | Verdict | Evidence |
|---|---|---|
| **3-tier Instagram/socials module** (Tavily search-regex → Extract → validated top-up) | **GO** (with one precision fix below) | IG found 86–88% vs 50% baseline; 72–76% in the stratum where prod has nothing; 0–1 regressions per 100 |
| **AI-block removal** (schema + prompt) | **GO** (orthogonal, unaffected by the split outcome) | narrative quality held everywhere it was measured |
| **Narrative-only OpenAI pass + Tavily-facts pass replacing agentic search** | **NO-GO** | numeric/fact fields collapse vs baseline (see below); cost gate missed at both caps; `max_tool_calls` turns out to be a soft lever |

## Gate tables

**cap 2** (avg 1.99 searches + 1.60 credits per entity):

| criterion | measured | threshold | verdict |
|---|---:|---:|---|
| tagline fill | 1.000 | ≥ 0.95 | PASS |
| notable fill | 0.800 | ≥ 0.90 | FAIL |
| instagram found | 0.860 | ≥ 0.60 | PASS |
| avg cost/run | $0.033 | ≤ $0.025 | FAIL |

**cap 1** (avg 1.71 searches + 1.48 credits per entity):

| criterion | measured | threshold | verdict |
|---|---:|---:|---|
| tagline fill | 1.000 | ≥ 0.95 | PASS |
| notable fill | 0.780 | ≥ 0.90 | FAIL |
| instagram found | 0.860 | ≥ 0.60 | PASS |
| avg cost/run | $0.029 | ≤ $0.025 | FAIL |

Additional spec criterion — founded_year / catalog_size not worse than baseline: **FAIL** at both caps (see fill tables).

## Key findings

### 1. The Instagram mechanism works — this was the experiment's main question

- Found: labels 88%/86% (cap2/cap1), artists 86%/86% — baseline 50%/50% (sample-weighted; prod-wide 44%/30%).
- In the `ig_missing` stratum (prod found nothing): 72–76% now found.
- Regressions (had IG in baseline, lost it): 0 at cap 2, 1/100 at cap 1.
- Tier fire-rates (cap 2): tier 1 (regex over search content) 66/87, tier 3 (validated top-up) 17/87, tier 2 (Extract on known pages) 4/87.

**Precision caveat:** automated handle validation confirms 74% of found handles; eyeball review of the 23 flagged puts true precision at ≈86% — slightly under the ≥90% spot-check bar. The misses are all tier 1 (regex accepts any IG link present in any search-result page, e.g. `danny_byrd` grabbed for artist "Daniel Nocturne", `hospitalrecords` for "DnB Doctor"). The validator itself is over-strict for short names (rejects correct `agrodnb` for "Agro", `eneimusique` for "Enei").
**Fix (one line + validator tweak):** apply `validate_instagram_handle` to tiers 1–2 as well, and relax the short-name rule (substring match for names ≥4 chars, plus the existing cross-network rule). Projected: found ≈70–78% (still comfortably over the 60% gate) at >90% precision. Full handle list for owner eyeballing: run `splitlab report <run_id>`.

### 2. The facts pass does NOT replace agentic search for numbers

| field (labels) | two-pass (cap2/cap1) | baseline (single-pass agentic) |
|---|---:|---:|
| founded_year | 26% / 30% | 60% |
| catalog_size_estimate | 20% / 22% | 52% |
| releases_last_12_months | 4% / 8% | 64% |
| notable_artists | 80% / 78% | 96% |
| (artists) active_since | 42% / 42% | 62% |
| (artists) labels | 72% / 72% | 100% |
| (artists) soundcloud_url | 56% / 56% | 82% |

One Tavily basic search + strict "sourced-only" extraction cannot match 2–3.4 agentic searches for numeric facts. Narrative fields are untouched (tagline/summary/bio/styles/notable_releases 98–100% at both caps).

### 3. `max_tool_calls` is a soft cap

At `max_tool_calls=1`, 71/100 entities still recorded 2 web-search calls; averages: cap 1 → 1.71, cap 2 → 1.99 searches/entity. The cap trims the tail but does not halve spend; cost projections built on "cap 1 = 1 search" are invalid. (Whether OpenAI bills sub-searches within one tool call as one or many is checkable in a few days via the Costs API line item vs our counted 199+171 calls.)

### 4. Reliability

7/100 entities hit transient timeouts on the first cap-2 attempt (OpenAI request timeout ×2, Tavily read timeout ×5, all during one window); a single retry recovered 7/7. Prod already has SQS retry semantics; the sandbox runner's per-entity error isolation (added after review caught its absence) is what kept the run alive.

## Spend

| item | amount |
|---|---:|
| cap-2 run (incl. 7 retries) | $3.27 (floor: the 7 timed-out first attempts' partial spend is not counted) |
| cap-1 run | $2.89 |
| aborted first cap-2 attempt (26 cells) + smoke | ≈ $0.85 |
| **total live** | **≈ $7.0** (ceiling $8) |

Tavily credits counted by us: 377 across all runs (~$3.02 of the above). The `/usage` endpoint lags badly (showed 105 while we had made 377 calls; showed 0 yesterday after 8 calls) — final reconciliation belongs in the owner's dashboard; our per-cell counter remains the source of truth, as designed.

## Recommendation for the prod plan

Adopt the pre-agreed fallback shape, now backed by data:

1. **Single OpenAI pass** (as today) with the **full schema minus `ai_*`** and `max_tool_calls=3` as a tail guardrail — keeps baseline numeric fill (60%/52%/64%…), removes AI-block spend; expect ~2.5–3.4 searches/entity.
2. **Bolt on the 3-tier socials module** after the OpenAI pass, with validation on ALL tiers: tier 1 search fires only when IG is still missing; tier 2 Extract reuses URLs the OpenAI pass already found; tier 3 top-up as measured. Expected added cost ≈ 1–1.5 credits on the ~50% of entities lacking IG ≈ +$0.006/entity avg.
3. Estimated prod economics at 4× volume (2 000 runs/mo): ≈ $0.030–0.036/entity ≈ **$60–72/mo with IG coverage ~85%+** — versus today's $68/mo at 44%/30% IG coverage. The AI-block removal's search savings (~0.5–1 search/entity) are the main downside lever and land inside that range's low end.
4. Re-run this sandbox's metrics script after prod rollout to confirm (the baseline tables here are the reference).

## Reproducing

Requires the original `outputs/` directory on the machine that ran the experiment — run artifacts are gitignored, so a fresh clone cannot regenerate these tables without re-running (≈$6).

```
cd experiments/enrichment_split
.venv/bin/splitlab report 20260715-212849-239f   # cap 2
.venv/bin/splitlab report 20260716-035040-e51f   # cap 1
```

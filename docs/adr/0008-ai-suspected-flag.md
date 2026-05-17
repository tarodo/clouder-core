# ADR-0008: `is_ai_suspected` soft propagated flag
Status: Accepted
Date: 2026-05-17

## Context

CLOUDER uses Perplexity AI to screen labels for AI-generated content. The result of each search is stored in `ai_search_results` as a structured JSONB payload including `ai_content` (e.g. `suspected`, `confirmed`, `none_detected`, `unknown`) and a `confidence` score from 0 to 1.

DJs want to filter out AI-content labels quickly in the curate workflow. Querying `ai_search_results` with a JOIN on every track render is expensive and the JSONB query is non-trivial. A boolean flag directly on the entity (`is_ai_suspected`) provides a cheap index-scannable filter.

The key design question was whether the flag should be the authoritative record of AI status or a derivative. Making it authoritative would mean external updates (e.g. a manual override or a re-run of the AI search) need to update the flag directly and maintain consistency. Making it a derivative means the authoritative data always lives in `ai_search_results` and the flag is a cached projection — simpler to reason about, easier to re-derive, but potentially stale.

The decision was to treat the flag as a soft derivative ("propagated"). After every `ai_search_results` write, `propagate_ai_flag` reads the result and conditionally updates the flag on the canonical entity. A confidence threshold (`AI_FLAG_CONFIDENCE_THRESHOLD`, default 0.6) gates the update to avoid polluting the flag with low-confidence guesses. `ai_content=unknown` is always a no-op regardless of confidence; `none_detected` with sufficient confidence explicitly clears the flag (sets to `false`), supporting correction flows.

An alternative was to propagate immediately on every AI result write with no threshold. This would increase flag noise — Perplexity occasionally returns low-confidence `suspected` verdicts for legitimate labels. The threshold makes the flag useful as a filter rather than a curiosity marker.

## Decision

`is_ai_suspected` is a soft flag set on `clouder_labels`, `clouder_artists`, and `clouder_tracks` after `propagate_ai_flag` runs, only when `confidence >= AI_FLAG_CONFIDENCE_THRESHOLD` (default `0.6`). `ai_content=unknown` is a no-op; `none_detected` explicitly clears the flag. The authoritative finding lives in `ai_search_results`; the flag is a query-time filter.

## Consequences

- The flag can be stale: if `AI_FLAG_CONFIDENCE_THRESHOLD` is raised after flags are set, existing flags are not retroactively cleared. Re-running the AI search pipeline for affected entities is the only way to re-sync.
- `GET /labels`, `GET /artists`, and `GET /tracks` do not project `is_ai_suspected`. To verify the current flag value, query Aurora directly: `SELECT COUNT(*) FROM clouder_labels WHERE is_ai_suspected = true`. Adding the field to API responses requires updating the SQL and OpenAPI spec.
- Current production prompts target labels (`entity_type='label'`). Artist and track propagation uses the same `propagate_ai_flag` function but is triggered only by artist-specific prompt slugs, which are not yet in production use.
- `ai_search_results.result` is JSONB, not flat columns. The full `LabelSearchResult` payload (including `size`, `age`, `founded_year`, `sources`) is available for manual review or future UI surfacing.
- Setting `AI_FLAG_CONFIDENCE_THRESHOLD` to 0 on the Lambda env var would cause every AI result with any content verdict to update the flag, including weak `suspected` findings. This is not recommended.

**Cross-references:** `../data/canonicalization.md`, `../data/search-and-enrichment.md`.

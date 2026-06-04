# ADR-0016: Label enrichment subsystem (multi-vendor consensus, async)
Status: Accepted
Date: 2026-06-04

## Context

The original label-search subsystem was Perplexity-only, single-prompt, auto-fired
during Beatport ingest. It shipped fragile signals and clogged the canonical schema,
and it was removed wholesale. A sandbox at `experiments/labels/` produced a stronger
multi-vendor pipeline (Gemini, OpenAI, Tavily+DeepSeek) with a consensus aggregator
and a richer `LabelInfo` schema (tagline, status, primary styles, social URLs).

Two forces shaped the production design. A single run of N labels × M vendors blows
through the API Gateway 29-second budget (Gemini alone averages ~58 s per call), so
the work must be asynchronous. And label profiles should be enriched automatically as
users curate, not only when an admin runs a batch by hand.

## Decision

A new `src/collector/label_enrichment/` package owns the subsystem.

- **Multi-vendor consensus.** The worker calls all configured vendors in parallel
  (`ThreadPoolExecutor`) for one label; an aggregator picks per-field winners
  (majority vote for facts, a single LLM call for the narrative).
- **Async via SQS, one message per label.** The API Lambda inserts a runs row and
  enqueues one message per label; the worker processes them (mirrors the Beatport
  ingest pattern). Per-label (not per-cell) granularity keeps every cell for a label
  in one place for `merge_cells` and stays within the 15-min Lambda budget
  (~60–90 s/label observed). SQS reserved concurrency (default 10) caps cross-label
  parallelism.
- **Persistence + provenance.** `clouder_label_enrichment_runs`, `_cells`, and
  `clouder_label_info` (full merged `LabelInfo` as JSONB plus denormalized
  filter/sort columns). `is_ai_suspected` on `clouder_labels` is re-populated as a
  denormalized projection of the new pipeline.
- **Auto-enrich = inline best-effort (approach A).** A helper is called from the
  curation path *after* commit and only enqueues work (a few Data API calls + an SQS
  batch, sub-second). The LLM search runs in the background worker; curation never
  waits and an auto-enrich failure never breaks curation. Dedup uses
  `label_auto_enrich_state` (atomic claim, attempts counter, in-flight guard): skip
  if a merged result exists or a search is in-flight; exactly one retry on failure.
  A singleton `auto_enrich_config` (per kind) master toggle defaults OFF. Runs are
  tagged `source='manual'|'auto'`.
- **User preferences.** `clouder_user_label_prefs` (`user_id`, `label_id`, `status`
  in `liked`/`disliked`, PK `(user_id, label_id)`). `PUT /labels/{id}/preference`
  and `GET /me/label-preferences`. Absence of a row means `none`; writing `none`
  deletes the row.

## Consequences

- Vendor cost scales with labels × vendors; reserved concurrency is the throttle.
- `is_ai_suspected` is a denormalized projection — re-derive it whenever label info
  changes; do not treat it as a source of truth.
- Auto-enrich is intentionally post-commit and best-effort; keep it off the
  critical path.
- This shape is mirrored one-to-one by artist enrichment (ADR-0017). Relates to
  ADR-0008 (`is_ai_suspected` soft flag).

**Cross-references:** `../data/search-and-enrichment.md`, `../data/data-model.md`,
`../backend/handlers.md`, `../frontend/features.md`. Source specs (now archived):
`../archive/specs/2026-05-17-label-ai-sandbox-design.md`,
`../archive/specs/2026-05-18-label-enrichment-backend-design.md`,
`../archive/specs/2026-05-18-label-enrichment-pipeline-design.md`,
`../archive/specs/2026-05-19-label-frontend-design.md`,
`../archive/specs/2026-05-19-user-label-preferences-design.md`,
`../archive/specs/2026-05-25-auto-label-enrichment-design.md`.

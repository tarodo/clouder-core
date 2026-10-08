# Experiments

Isolated sandboxes, each with its own virtualenv and tests. Production code under
`src/collector/` is never imported from here; a sandbox earns its way into production
through a design spec and a PR.

| Sandbox | Question | Outcome |
|---|---|---|
| [`labels/`](labels/README.md) | Which vendors and prompts give the most accurate label profiles, and can several vendors be merged into one answer? | A multi-vendor pipeline (Gemini, OpenAI, Tavily + DeepSeek) with a consensus aggregator beat the single-vendor search it replaced → label enrichment in production ([ADR-0016](../docs/adr/0016-label-enrichment.md)). |
| [`artists/`](artists/README.md) | Does the same approach hold for artists? | Yes, with artist-specific prompts → artist enrichment as a parallel package ([ADR-0017](../docs/adr/0017-artist-enrichment.md)). |
| [`enrichment_split/`](enrichment_split/README.md) | Can a two-pass run (narrative + facts) with a tiered social-link search cut cost per entity and find more Instagram profiles, measured on 50 + 50 real entities against their production baselines? | The two-pass design shipped as enrichment v2 (PR #219, tiered socials resolver in `src/collector/social_links.py`; the one-off `scripts/backfill_instagram.py` fills older entities). |

Each sandbox README has its setup and commands; outputs are git-ignored.

# Artist AI Sandbox

Local-only experiment harness for comparing AI vendors and prompts on the
"music artist info enrichment" task. Production code under `src/collector/`
is not touched by this directory.

Design spec: `docs/archive/specs/2026-05-26-artist-search-design.md`

## Setup

```bash
cd experiments/artists
python3.12 -m venv .venv
.venv/bin/pip install -e ".[dev]"
cp .env.example .env
# edit .env and add your API keys (any subset is fine; missing vendors are skipped)
```

## Run

```bash
# default: openai / gpt-5.4-mini across all fixtures
.venv/bin/artlab run --prompts artist_v1

# subset
.venv/bin/artlab run --prompts artist_v1 --vendors openai --fixtures anna

# multi-vendor compare, then consensus merge (needs DEEPSEEK_API_KEY)
.venv/bin/artlab run --prompts artist_v1 --vendors openai,perplexity
.venv/bin/artlab aggregate <run_id>

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
- `reports/<run_id>.md` — side-by-side + consensus markdown report

`outputs/` and `reports/` are gitignored.

## Tests

```bash
.venv/bin/pytest
```

All tests use mocked SDK clients. No live API call.

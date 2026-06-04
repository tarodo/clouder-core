# Label AI Sandbox

Local-only experiment harness for comparing AI vendors and prompts on the
"music label info enrichment" task. Production code under `src/collector/`
is not touched by this directory.

Design spec: `docs/archive/specs/2026-05-17-label-ai-sandbox-design.md`

## Setup

```bash
cd experiments/labels
python3.12 -m venv .venv
.venv/bin/pip install -e ".[dev]"
cp .env.example .env
# edit .env and add your API keys (any subset is fine; missing vendors are skipped)
```

## Run

Default concurrency is 8 (paid-tier quotas). See the Concurrency section below for details.

```bash
# full matrix
.venv/bin/lab run

# subset
.venv/bin/lab run --prompts label_v2_facts --vendors anthropic --fixtures drumcode

# inspect
.venv/bin/lab list prompts
.venv/bin/lab list vendors
.venv/bin/lab list fixtures

# regenerate report only
.venv/bin/lab report <run_id>
```

Outputs land in:
- `outputs/<run_id>/<prompt>__<vendor>__<fixture>.json` — one raw cell each
- `outputs/<run_id>/manifest.json` — what was run
- `reports/<run_id>.md` — side-by-side markdown report

`outputs/` and `reports/` are gitignored.

## Recommended pipeline

For an end-to-end experiment producing a consensus label record:

```bash
# 1. Run two complementary vendors with the app-targeted prompt
.venv/bin/lab run --prompts label_v3_app_fields --vendors tavily_deepseek,gemini

# 2. Merge per-fixture cells into one consensus LabelInfo
.venv/bin/lab aggregate <run_id>

# 3. Inspect
open reports/<run_id>.md
```

Approximate cost for 8 fixtures: $0.007 (Tavily+DeepSeek) + $0.04 (Gemini) +
$0.003 (narrative merge) = **~$0.05** per full run.

When a merged cell shows `confidence < 0.5` or `ai_content=unknown`, rerun
that specific fixture against a higher-quality vendor and re-aggregate:

```bash
.venv/bin/lab run --fixtures <id> --vendors anthropic --prompts label_v3_app_fields
.venv/bin/lab aggregate <newer_run_id>
```

Cheap baseline + on-demand expert arbiter pattern.

### Concurrency

`CONCURRENCY` (env var) controls how many vendor calls run in parallel.
Default is 8 — fine for paid-tier OpenAI (500 RPM), Gemini (1000 RPM),
and Anthropic basic-tier with the built-in 429 retry. Cells are submitted
interleaved by vendor so a single vendor doesn't get all of one wave.
Bump higher if you've raised your vendor quotas; the Anthropic adapter
will retry 429s automatically with backoff.

## Tests

```bash
.venv/bin/pytest
```

All tests use mocked SDK clients. No live API call.

## Adding a prompt

1. Create `src/lab/prompts/label_<slug>.py`
2. `register(PromptConfig(...))` in the module
3. Import it from `load_builtin_prompts()` in `src/lab/prompts/__init__.py`

## Adding a vendor

1. Create `src/lab/vendors/<vendor>.py` implementing the `VendorAdapter` protocol
2. Add it to `build_vendors()` in `src/lab/cli.py`
3. Add an `<VENDOR>_API_KEY` entry to `.env.example` and `Settings` in `config.py`

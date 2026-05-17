# Label AI Sandbox

Local-only experiment harness for comparing AI vendors and prompts on the
"music label info enrichment" task. Production code under `src/collector/`
is not touched by this directory.

Design spec: `docs/superpowers/specs/2026-05-17-label-ai-sandbox-design.md`

## Setup

```bash
cd experiments/labels
python3.12 -m venv .venv
.venv/bin/pip install -e ".[dev]"
cp .env.example .env
# edit .env and add your API keys (any subset is fine; missing vendors are skipped)
```

## Run

Default concurrency is 1 to stay within Anthropic's basic-tier 30k input-tokens/min limit; pass `--concurrency N` explicitly for higher tiers.

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

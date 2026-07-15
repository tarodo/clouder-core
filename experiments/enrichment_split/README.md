# Enrichment Split Lab

Offline experiment: two-pass enrichment (OpenAI narrative + Tavily facts,
3-tier Instagram) on 50+50 real prod entities vs their prod baselines.
Spec: docs/superpowers/specs/2026-07-15-enrichment-cost-instagram-design.md §5.
Prod code is not touched.

## Setup
    cd experiments/enrichment_split
    python3.12 -m venv .venv
    .venv/bin/pip install -e ".[dev]"
    cp ../artists/.env .env   # OPENAI_API_KEY + TAVILY_API_KEY

## Use
    .venv/bin/splitlab pull-sample                # 50+50 from prod (needs aws creds)
    .venv/bin/splitlab run --cap 2                # live two-pass run
    .venv/bin/splitlab run --cap 2 --limit 3      # smoke on 3 entities
    .venv/bin/splitlab report <run_id>            # metrics + gate verdict

`outputs/` is gitignored; `sample/sample.yaml` is checked in.

## Tests (all mocked, no live calls)
    .venv/bin/pytest -q

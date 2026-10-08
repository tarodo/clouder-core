# Entry points for local work; CI runs the same commands (.github/workflows/pr.yml).
VENV   ?= .venv/bin
PY     := PYTHONPATH=src $(VENV)/python
TEST_DATABASE_URL ?= postgresql://postgres:postgres@localhost:55433/postgres

.PHONY: help bootstrap local-db demo test test-db lint typecheck cov lock openapi package frontend-test screenshots dbt-ci

help:            ## list targets
	@grep -E '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | sed 's/:.*## /\t/'

bootstrap:       ## create .venv with the locked dev deps
	python3.12 -m venv .venv && $(VENV)/pip install -r requirements-dev.txt

local-db:        ## Postgres in Docker (docker-compose.yml), migrated — for test-db and demo
	docker compose up -d --wait db
	PYTHONPATH=src ALEMBIC_DATABASE_URL=$(subst postgresql://,postgresql+psycopg://,$(TEST_DATABASE_URL)) $(VENV)/alembic upgrade head

demo:            ## run one synthetic week through the real pipeline on the local Postgres
	$(PY) scripts/demo_pipeline.py --database-url $(TEST_DATABASE_URL)

test:            ## backend tests (real-Postgres tests skip without TEST_DATABASE_URL)
	$(VENV)/pytest -q

test-db:         ## real-Postgres tests (migrates the schema first)
	PYTHONPATH=src ALEMBIC_DATABASE_URL=$(subst postgresql://,postgresql+psycopg://,$(TEST_DATABASE_URL)) $(VENV)/alembic upgrade head
	TEST_DATABASE_URL=$(TEST_DATABASE_URL) $(VENV)/pytest -q tests/db

lint:            ## ruff
	$(VENV)/ruff check src tests scripts

typecheck:       ## mypy (config in pyproject.toml)
	$(VENV)/mypy

cov:             ## tests with the 80 % coverage gate
	$(VENV)/pytest -q --cov

lock:            ## re-lock Python deps after editing a requirements-*.in file
	uv pip compile --universal --python-version 3.12 requirements-lambda.in -o requirements-lambda.txt
	uv pip compile --universal --python-version 3.12 requirements-dev.in -o requirements-dev.txt

openapi:         ## regenerate docs/api/openapi.yaml and the frontend types
	$(PY) scripts/generate_openapi.py
	cd frontend && pnpm api:types

package:         ## build dist/collector.zip for Terraform
	PATH=$(abspath $(VENV)):$$PATH bash scripts/package_lambda.sh

frontend-test:   ## frontend typecheck, lint and unit tests
	cd frontend && pnpm typecheck && pnpm lint && pnpm test

screenshots:     ## regenerate the README screenshots (docs/assets)
	cd frontend && pnpm screenshots

dbt-ci:          ## dbt build on DuckDB with fixtures, as in CI
	cd dbt && export DBT_PROFILES_DIR=. && dbt seed --target ci && dbt run --target ci --empty \
	  && dbt build --target ci --full-refresh --exclude resource_type:seed

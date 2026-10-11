# README Numbers, Hygiene and the v2.2.0 Release — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The README states today's numbers and the delivery/scale story the last phases made true; local Postgres no longer pins port 55433; GitHub Actions are pinned by commit SHA; the demo work gets its release (`v2.2.0`) and the CHANGELOG catches up, with the hardening of 2026-10-11 under "Unreleased" until `v2.3.0` (after phases 5 and 6).

**Architecture:** Text and config only, plus one annotated tag and a GitHub Release. Numbers come from read-only sources measured on 2026-10-11: `scripts/dora.py`, CloudWatch (30-day Lambda totals), the catalog export's row counts, the test runs.

**Tech Stack:** Markdown, docker-compose, Make, GitHub Actions YAML, git-cliff (via `uvx`), `gh`.

**Spec:** `~/Desktop/HIRING_AUDIT_2026-10-11.ru.md` §1.4 п. 7, §11 Level 1–2 (P0 `v2.2.0`, P1 README numbers, P2 SHA pins, compose port, frontend version), §12.3–12.7 and 12.10, §0.3 phase 7.

## Global Constraints

- Branch `chore/readme-release` from `origin/main`. README counts guarded by `tests/unit/test_readme.py`.
- Measured 2026-10-11: backend 2,229 unit/integration tests + 59 real-PostgreSQL; frontend 1,222; Lambda 159,142 invocations in 30 days (09-11 → 10-11), 66 errors (0.041 %); DORA-style 90 days: 7.2 deploys/week, median lead time 11 min, 2 of 94 deploy runs failed, recovery 8 min; 307 merged PRs; catalog export 2026-10-11: 143,048 canonical tracks.
- Tags: annotated, dated at the merge commit (`GIT_COMMITTER_DATE`), on `main` merge commits only. `v2.2.0` = merge of #309 (`7d9342fe`).
- No money; English; commit messages from `caveman:caveman-commit`; no AI attribution.

## Review Focus

1. A number in the README that the sources do not support (each one traced above).
2. SHA pins that do not match the tag they claim (comment `# vN` must resolve to the same SHA).
3. `make test-db` / `make demo` / `docker compose up` still agree on the port after the change.
4. The CHANGELOG regenerated from the tags includes every merged PR exactly once.
5. Text that claims phases 5–6 results before they exist (the restore drill and the deploy-role switch are still pending).

---

### Task 1: README and scalability

- [ ] At a glance: `~98k canonical tracks` → `~143k canonical tracks`; `~3,300 automated tests` → `~3,500 automated tests`; `every merge to \`main\` deploys to production.` → `every merge to \`main\` deploys to production behind a smoke test with automatic rollback.`
- [ ] Software engineering bullet: `About 3,300 automated tests: ~2,090 backend (…), ~1,230 frontend` → `About 3,500 automated tests: ~2,290 backend (including 59 against a real PostgreSQL 16), ~1,220 frontend`.
- [ ] Cloud & infrastructure bullet on GitHub Actions → the 12.5 text (read-only plan role, environment-gated deploy role, migrations first, smoke test and alias rollback).
- [ ] AWS services: Lambda and IAM rows → 12.6 texts (concurrency caps per queue; `live` alias; plan/deploy roles).
- [ ] By the numbers: catalog row → `~143k canonical tracks (catalog export, 2026-10-11)`; Lambda row → `159k in 30 days (2026-09-11 → 10-11), 0.041 % errors`; Delivery row → `300+ merged pull requests; … Last 90 days to 2026-10-11, DORA-style (…): 7.2 deploys a week, median lead time 11 min from first commit to production, 2 of 94 deploy runs failed (recovered in 8 min); one green deploy caused a production incident — 2 min 40 s of errors on one route (postmortem)`.
- [ ] Data pipeline: after "When something fails", the 12.7 paragraph, written to the measured truth: the export hit its timeout as the catalog grew; keyset paging bought 6 %, the time was CPU (256 → 1024 MB: 296 s → 124 s); keyset stays for correctness.
- [ ] Known limitations: `about 98k tracks` → `about 143k tracks`; add the 12.10 line (deploy role still AdministratorAccess until the scoped policy in `infra/bootstrap/` is applied).
- [ ] `docs/scalability.md` line 3: `about 98k canonical tracks` → `about 143k canonical tracks (2026-10-11)`.
- [ ] Run `tests/unit/test_readme.py`, `test_docs_freshness.py`, `test_docs_links.py`; commit (`docs(readme): numbers and delivery as of 2026-10-11`).

### Task 2: Hygiene

- [ ] `docker-compose.yml`: `ports: ["55433:5432"]` → `ports: ["${PG_PORT:-55433}:5432"]`; `Makefile`: `PG_PORT ?= 55433` and `TEST_DATABASE_URL ?= postgresql://postgres:postgres@localhost:$(PG_PORT)/postgres`; README "Running it locally" mentions `PG_PORT=55499 make local-db` when 55433 is taken. Check with `docker compose config | grep published` (with and without `PG_PORT`).
- [ ] `frontend/package.json` `"version": "0.0.0"` → `"2.2.0"` (the release this branch ships under); `pnpm install --lockfile-only` is not needed (version is not in the lockfile) — confirm `pnpm install --frozen-lockfile` still passes.
- [ ] Workflows: replace every `uses: owner/repo@vN` with `uses: owner/repo@<40-char sha> # vN`, the SHA resolved with `gh api repos/<owner>/<repo>/git/ref/tags/<vN>` (dereference annotated tags via `.../git/tags/<sha>`). Add a guard test `tests/unit/test_workflow_pins.py`: every `uses:` in `.github/workflows/*.yml` is `@<40 hex>` followed by `# v…`.
- [ ] Commit (`chore: pin actions, free the Postgres port`).

### Task 3: Release v2.2.0 and the changelog

- [ ] `GIT_COMMITTER_DATE="$(git log -1 --format=%cI 7d9342fe)" git tag -a v2.2.0 7d9342fe -m "v2.2.0 — Try it in the browser"`; push the tag; `gh release create v2.2.0 --title "v2.2.0 — Try it in the browser" --notes "<demo on GitHub Pages: sample data, two styles, covers, a player with music; landing page; lineage moved to /lineage/>"` (not `--latest` until checked; it should become Latest).
- [ ] `make changelog`; check the `[2.2.0]` section lists #301–#309 and `Unreleased` lists #310–#315 and this PR's predecessors; commit (`docs(changelog): v2.2.0 and unreleased`).
- [ ] PR, checks, merge, deploy; board phase 7 → `in progress (v2.3.0 after phases 5–6)`.

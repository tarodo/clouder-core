# Catalog Export on Keyset Pagination + Lakehouse Documents — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The nightly catalog export pages by primary key instead of `OFFSET`, logs its time per table, and the nightly dbt build runs the commit that was deployed; the lakehouse documents gain a grain table, the reason the freshness gate runs after the build, and the Aurora-side lineage.

**Architecture:** `_EXPORTS` becomes (table, columns, key columns); each page after the first adds `WHERE (keys) > (:k0, …)` built from the last row, so every page is an index range scan and rows inserted or deleted during the export are neither duplicated nor skipped. CodeBuild reads the commit to build from an SSM String parameter that the deploy writes after its smoke test.

**Tech Stack:** Python 3.12 (Data API client), pytest (unit + real PostgreSQL 16 in `tests/db`), Terraform, GitHub Actions, Markdown.

**Spec:** `~/Desktop/HIRING_AUDIT_2026-10-11.ru.md` §1.4 п. 3, §5 (Data modeling, Orchestration, Data lineage), §0.3 phase 2. Evidence: the export ran 211 s → 231 → 257 → 300+ s over four nights (06–09.10), timed out at 300 s on 10.10 and 11.10 (3 attempts each), and took 314.6 s by hand at 900 s; ≈ 870 Data API pages of 500 rows; the code comment says to switch to keyset "if that ever changes". CodeBuild clones `main` (`GIT_REF = "main"`).

## Global Constraints

- Worktree `../clouder-core-loop`, branch `feat/export-keyset` from `origin/main`. Tools from the main checkout's `.venv/bin/` (paths below are relative to it). Real-PostgreSQL tests: a throwaway `postgres:16` on port 55511 (`TEST_DATABASE_URL=postgresql://postgres:postgres@localhost:55511/postgres`, migrate first); port 55433 belongs to another project.
- Runtime DB access only through the RDS Data API (ADR-0001): no `psycopg` in `src/collector/`.
- Data API response cap ≈ 1 MB per call: keep the 500-row page.
- `log_event` drops fields missing from `ALLOWED_LOG_FIELDS`.
- Commit messages from `caveman:caveman-commit`; Conventional Commits; no AI attribution. English in the repo; no money figures.
- `README.md` counts are guarded (`tests/unit/test_readme.py`): count Terraform resources after Task 3.

## Review Focus

1. **Composite keys** (`clouder_track_artists` on track_id, artist_id, role; `category_tracks` on category_id, track_id): the row comparison must use all key columns in `ORDER BY` order, or rows sharing a prefix are lost. Pinned in Task 1 (unit) and Task 2 (real PostgreSQL).
2. **A row deleted or inserted during the export** must not shift pages (the `OFFSET` failure). Pinned in Task 1 (`test_rows_deleted_mid_export_are_not_skipped`).
3. **An empty table / a table of exactly one page** must stop after one call without an extra empty query loop. Pinned in Task 1.
4. **The SSM parameter is missing or still `main` on the first night** → the build must still work (the parameter is created with `main`; `git fetch` accepts a branch or a SHA). Pinned in Task 3 (buildspec test).
5. **A failed smoke test** must not advance the nightly build's commit → the "record" step runs after the smoke test and only on success. Pinned in Task 3.

---

### Task 1: Keyset pagination and per-table timing

**Files:**
- Modify: `src/collector/catalog_export_handler.py`
- Modify: `src/collector/logging_utils.py` (`ALLOWED_LOG_FIELDS` += `"table_name"`)
- Modify: `tests/unit/test_catalog_export_handler.py`

**Interfaces:**
- Produces: `_EXPORTS: tuple[tuple[str, str, tuple[str, ...]], ...]` = (table, comma-separated columns, key columns); `_sql(table: str, columns: str, keys: tuple[str, ...], after: tuple | None) -> str`; `export_catalog(data_api, s3_client, bucket, snapshot_dt, page=_PAGE) -> dict[str, int]` (unchanged signature). Parameters for a page after the first: `{"limit": page, "k0": …, "k1": …}`.

- [ ] **Step 1: Rewrite the fake and the tests to the keyset contract** (failing first)

In `tests/unit/test_catalog_export_handler.py`, replace `FakeDataAPI` with a keyset-aware fake and add three tests:

```python
class FakeDataAPI:
    """Mimics DataAPIClient.execute for keyset pages: WHERE (keys) > (:k0, …) ORDER BY keys."""

    def __init__(self, rows_by_table: dict[str, list[dict]]) -> None:
        self.rows_by_table = rows_by_table
        self.calls: list[tuple[str, dict]] = []
        self.after_call = None  # hook: lambda table, n_calls -> None (mutate rows mid-export)

    def execute(self, sql, params=None, transaction_id=None):
        self.calls.append((sql, params))
        table = next(t for t in self.rows_by_table if f"FROM {t} " in sql)
        keys = next(k for t, _, k in ceh._EXPORTS if t == table)
        rows = sorted(self.rows_by_table[table], key=lambda r: tuple(r[k] for k in keys))
        if "WHERE" in sql:
            after = tuple(params[f"k{i}"] for i in range(len(keys)))
            rows = [r for r in rows if tuple(r[k] for k in keys) > after]
        page = rows[: params["limit"]]
        if self.after_call:
            self.after_call(table, len(self.calls))
        return page
```

```python
def test_pages_by_key_never_by_offset() -> None:
    tracks = [{"id": f"t{i}", "title": f"T{i}"} for i in range(5)]
    api = FakeDataAPI(_empty_tables({"clouder_tracks": tracks}))

    export_catalog(api, FakeS3(), "lake", "2026-10-11", page=2)

    track_calls = [(sql, p) for sql, p in api.calls if "FROM clouder_tracks " in sql]
    assert all("OFFSET" not in sql for sql, _ in api.calls)
    assert "WHERE" not in track_calls[0][0]
    assert track_calls[1][1] == {"limit": 2, "k0": "t1"}  # last id of page one
    assert track_calls[2][1] == {"limit": 2, "k0": "t3"}


def test_composite_keys_compare_every_key_column() -> None:
    rows = [
        {"track_id": "a", "artist_id": "x", "role": "main"},
        {"track_id": "a", "artist_id": "x", "role": "remixer"},
        {"track_id": "a", "artist_id": "y", "role": "main"},
        {"track_id": "b", "artist_id": "x", "role": "main"},
    ]
    api = FakeDataAPI(_empty_tables({"clouder_track_artists": rows}))
    s3 = FakeS3()

    counts = export_catalog(api, s3, "lake", "2026-10-11", page=1)

    assert counts["clouder_track_artists"] == 4
    sql = next(s for s, p in api.calls if "FROM clouder_track_artists " in s and "WHERE" in s)
    assert "(track_id, artist_id, role) > (:k0, :k1, :k2)" in sql
    assert "ORDER BY track_id, artist_id, role" in sql


def test_rows_deleted_mid_export_are_not_skipped() -> None:
    # OFFSET paging skips a row when an earlier one is deleted between pages.
    tracks = [{"id": f"t{i}"} for i in range(6)]
    api = FakeDataAPI(_empty_tables({"clouder_tracks": tracks}))

    def delete_first_after_page_one(table, n_calls):
        if table == "clouder_tracks" and n_calls == 1:
            api.rows_by_table["clouder_tracks"].pop(0)  # t0, already exported

    api.after_call = delete_first_after_page_one
    s3 = FakeS3()

    export_catalog(api, s3, "lake", "2026-10-11", page=2)

    exported = [
        json.loads(line)["id"]
        for key in sorted(k for k in s3.objects if "clouder_tracks" in k)
        for line in s3.objects[key].decode().splitlines()
    ]
    assert exported == ["t0", "t1", "t2", "t3", "t4", "t5"]
```

Keep the existing tests; they keep working against the new fake (`test_paging_writes_one_ndjson_part_per_page`, `test_empty_table_writes_no_object`, `test_ndjson_serializes_dates_via_default_str`, `test_default_page_is_data_api_safe`, `test_no_psycopg_or_columnar_imports`, `test_exported_tables_match_glue_tbl_enum`). Change `test_categories_query_selects_deleted_at` and `test_exported_tables_match_glue_tbl_enum` to the new tuple shape:

```python
def test_categories_query_selects_deleted_at() -> None:
    # deleted_at must be exported so dbt can filter soft-deletes (recon gotcha).
    columns = next(c for t, c, _ in ceh._EXPORTS if t == "categories")
    assert "deleted_at" in columns
```

and in `test_exported_tables_match_glue_tbl_enum` use `{t for t, _, _ in _EXPORTS}`.

Add the logging test:

```python
def test_table_timing_survives_the_log_allow_list() -> None:
    import collector.logging_utils as lu

    for field in ("table_name", "total_count", "api_pages_fetched", "duration_ms"):
        assert field in lu.ALLOWED_LOG_FIELDS, field
```

- [ ] **Step 2: Run them to make sure they fail**

Run: `PYTHONPATH=src .venv/bin/pytest tests/unit/test_catalog_export_handler.py -q`
Expected: failures — the fake unpacks 3-tuples from `_EXPORTS` (ValueError), `table_name` missing from the allow-list.

- [ ] **Step 3: Implement**

Replace the top of `src/collector/catalog_export_handler.py` (docstring, `_EXPORTS`, the `ponytail:` comment, `export_catalog`) with:

```python
"""Daily Aurora catalog snapshot to the analytics lake (bronze/catalog_export/).

Runs the dim read queries through the RDS Data API (ADR-0001: Aurora is reached
only via the Data API at runtime), pages by primary key (keyset) and writes
line-delimited JSON to S3. Intentionally lightweight: no columnar or DataFrame
dependency is bundled, so the collector zip stays small — a Glue table types the
columns and Athena casts on read (spec section 6).
"""
```

```python
# (table, columns, primary key). Pages continue after the last row's key, so each
# page is an index range scan and a row inserted or deleted mid-export cannot shift
# the pages. OFFSET paging cost grew with every page: at ~430k rows the export hit
# its 300 s timeout two nights running (2026-10-10, 10-11).
_EXPORTS: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    (
        "clouder_tracks",
        "id, title, bpm, key_name, key_camelot, spotify_release_date, publish_date, "
        "album_id, style_id, isrc, release_type, is_ai_suspected, origin, created_at, "
        "updated_at",
        ("id",),
    ),
    (
        "clouder_artists",
        "id, name, normalized_name, is_ai_suspected, created_at, updated_at",
        ("id",),
    ),
    ("clouder_track_artists", "track_id, artist_id, role", ("track_id", "artist_id", "role")),
    (
        "clouder_labels",
        "id, name, normalized_name, is_ai_suspected, created_at, updated_at",
        ("id",),
    ),
    (
        "clouder_albums",
        "id, title, label_id, release_date, release_type, created_at, updated_at",
        ("id",),
    ),
    (
        "categories",
        "id, user_id, style_id, name, normalized_name, position, created_at, updated_at, "
        "deleted_at",
        ("id",),
    ),
    (
        "category_tracks",
        "category_id, track_id, added_at, source_triage_block_id",
        ("category_id", "track_id"),
    ),
    # Style names for the per-style analytics (incl. hidden styles). Written last: the
    # nightly freshness check treats its presence as a complete snapshot.
    ("clouder_styles", "id, name, normalized_name, created_at, updated_at", ("id",)),
)

# The Data API caps a response at ~1 MB: 500 rows of the widest dim (clouder_tracks,
# 15 columns) stay well under it. If a wider dim ever raises "Database response
# exceeded size limit", halve this.
_PAGE = 500


def _sql(table: str, columns: str, keys: tuple[str, ...], after: tuple[Any, ...] | None) -> str:
    order = ", ".join(keys)
    where = ""
    if after is not None:
        marks = ", ".join(f":k{i}" for i in range(len(keys)))
        where = f" WHERE ({order}) > ({marks})"
    return f"SELECT {columns} FROM {table}{where} ORDER BY {order} LIMIT :limit"
```

```python
def export_catalog(
    data_api: DataAPIClient,
    s3_client: Any,
    bucket: str,
    snapshot_dt: str,
    page: int = _PAGE,
) -> dict[str, int]:
    counts: dict[str, int] = {}
    for table, columns, keys in _EXPORTS:
        started = time.monotonic()
        after: tuple[Any, ...] | None = None
        part = total = 0
        while True:
            params: dict[str, Any] = {"limit": page}
            if after is not None:
                params.update({f"k{i}": v for i, v in enumerate(after)})
            rows = data_api.execute(_sql(table, columns, keys, after), params)
            if not rows:
                break
            key = f"bronze/catalog_export/snapshot_dt={snapshot_dt}/{table}/part-{part:05d}.json"
            s3_client.put_object(
                Bucket=bucket,
                Key=key,
                Body=_ndjson(rows),
                ContentType="application/x-ndjson",
            )
            total += len(rows)
            part += 1
            if len(rows) < page:
                break
            after = tuple(rows[-1][k] for k in keys)
        counts[table] = total
        log_event(
            "INFO",
            "catalog_export_table_written",
            s3_bucket=bucket,
            table_name=table,
            total_count=total,
            api_pages_fetched=part,
            duration_ms=int((time.monotonic() - started) * 1000),
        )
    return counts
```

Add `import time` to the imports. In `src/collector/logging_utils.py` add `"table_name",` to `ALLOWED_LOG_FIELDS` (next to `"entity_type"`).

- [ ] **Step 4: Run the tests**

Run: `PYTHONPATH=src .venv/bin/pytest tests/unit/test_catalog_export_handler.py tests/unit/test_logging_utils.py -q && .venv/bin/ruff check src tests && .venv/bin/mypy`
Expected: all pass; mypy clean.

- [ ] **Step 5: Commit** (e.g. `perf(export): page the catalog by primary key`)

---

### Task 2: The keyset SQL against a real PostgreSQL

**Files:**
- Create: `tests/db/test_catalog_export_pg.py`

**Interfaces:**
- Consumes: `export_catalog`, `_EXPORTS` from Task 1; fixture `pg` (`tests/db/conftest.py`, a `PgDataAPIClient` over a truncated, migrated DB); `scripts/demo_pipeline.py:run(dsn, tracks=N)` (fills the canonical tables with a synthetic week).

- [ ] **Step 1: Write the test**

```python
"""The keyset export SQL on real PostgreSQL: every row once, composite keys included."""

from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path

from collector.catalog_export_handler import _EXPORTS, export_catalog

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "demo_pipeline.py"


class FakeS3:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    def put_object(self, **kw):
        self.objects[kw["Key"]] = kw["Body"]
        return {}


def _fill(dsn: str) -> None:
    spec = importlib.util.spec_from_file_location("demo_pipeline", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.run(dsn, tracks=60)


def test_every_row_exported_once_with_small_pages(pg) -> None:
    _fill(os.environ["TEST_DATABASE_URL"])
    s3 = FakeS3()

    counts = export_catalog(pg, s3, "lake", "2026-10-11", page=7)

    for table, _, keys in _EXPORTS:
        expected = pg.execute(f"SELECT count(*) AS n FROM {table}")[0]["n"]
        rows = [
            json.loads(line)
            for key, body in s3.objects.items()
            if f"/{table}/" in key
            for line in body.decode().splitlines()
        ]
        assert counts[table] == expected == len(rows), table
        assert len({tuple(r[k] for k in keys) for r in rows}) == len(rows), table
    assert counts["clouder_tracks"] == 60
    assert counts["clouder_track_artists"] > 60  # several artists per track: composite key paged
```

- [ ] **Step 2: Run it on a throwaway PostgreSQL**

```bash
docker run -d --rm --name export-pg -e POSTGRES_PASSWORD=postgres -p 55511:5432 postgres:16
# wait for pg_isready, then:
PYTHONPATH=src ALEMBIC_DATABASE_URL=postgresql+psycopg://postgres:postgres@localhost:55511/postgres .venv/bin/alembic upgrade head
TEST_DATABASE_URL=postgresql://postgres:postgres@localhost:55511/postgres PYTHONPATH=src .venv/bin/pytest tests/db/test_catalog_export_pg.py -q
```

Expected: 1 passed. This is a contract test of the generated SQL against the real grammar and row-comparison semantics (Task 1's unit tests own the RED step); ledger it as such. Then `docker stop export-pg`.

- [ ] **Step 3: Commit** (e.g. `test(export): keyset SQL on real Postgres`)

---

### Task 3: The nightly dbt build runs the deployed commit

**Files:**
- Modify: `infra/lakehouse.tf` (SSM parameter, CodeBuild env var, buildspec install, dbt role statement)
- Modify: `.github/workflows/deploy.yml` (step after `Smoke test`)
- Modify: `tests/unit/test_lakehouse_infra.py`, `tests/unit/test_deploy_order.py`
- Modify: `README.md` (Terraform resource count)

**Interfaces:**
- Produces: SSM String parameter `/clouder/dbt/git_ref` (`aws_ssm_parameter.dbt_git_ref`), CodeBuild env `GIT_REF` of type `PARAMETER_STORE`; deploy step name `Record the deployed commit for the nightly build`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_lakehouse_infra.py`:

```python
def test_nightly_build_runs_the_deployed_commit() -> None:
    tf = (INFRA / "lakehouse.tf").read_text()
    param = tf[tf.index('resource "aws_ssm_parameter" "dbt_git_ref"') :]
    param = param[: param.index("\n}\n")]
    assert 'name  = "/clouder/dbt/git_ref"' in param or 'name = "/clouder/dbt/git_ref"' in param
    assert "ignore_changes = [value]" in param  # the deploy owns the value
    env = tf[tf.index('name  = "GIT_REF"') - 200 : tf.index('name  = "GIT_REF"') + 200]
    assert 'type  = "PARAMETER_STORE"' in env and "aws_ssm_parameter.dbt_git_ref.name" in env
    spec = tf[tf.index("buildspec = <<-YAML") :]
    # A SHA cannot be cloned with --branch; fetch accepts a SHA or a branch.
    assert 'git -C repo fetch --depth 1 https://github.com/tarodo/clouder-core.git "$GIT_REF"' in spec
    assert "--branch" not in spec
    assert "ssm:GetParameters" in tf
```

(If `INFRA` is not defined in that test module, define it as `Path(__file__).resolve().parents[2] / "infra"` — read the file's header first and reuse its existing constant.)

Append to `tests/unit/test_deploy_order.py`:

```python
def test_deploy_records_its_commit_after_the_smoke_test() -> None:
    steps = yaml.safe_load(DEPLOY.read_text())["jobs"]["deploy"]["steps"]
    names = [s.get("name", "") for s in steps]
    record = names.index("Record the deployed commit for the nightly build")
    assert names.index("Smoke test") < record < names.index("Roll back API aliases")
    run = steps[record]["run"]
    assert "/clouder/dbt/git_ref" in run and "$GITHUB_SHA" in run
    assert "if" not in steps[record]  # default success(): a failed smoke never advances it
```

- [ ] **Step 2: Run them to make sure they fail**

Run: `PYTHONPATH=src .venv/bin/pytest tests/unit/test_lakehouse_infra.py tests/unit/test_deploy_order.py -q`
Expected: 2 failed (missing resource / step).

- [ ] **Step 3: Implement**

In `infra/lakehouse.tf`, before the CodeBuild project:

```hcl
# The commit the nightly build runs: the deploy writes it after a green smoke test,
# so dbt models never run ahead of (or behind) what is in production.
resource "aws_ssm_parameter" "dbt_git_ref" {
  name  = "/clouder/dbt/git_ref"
  type  = "String"
  value = "main" # first night only; the deploy owns the value after that

  lifecycle {
    ignore_changes = [value]
  }
}
```

Replace the `GIT_REF` environment variable:

```hcl
    environment_variable {
      name  = "GIT_REF"
      type  = "PARAMETER_STORE"
      value = aws_ssm_parameter.dbt_git_ref.name
    }
```

Replace the clone line in the buildspec install commands:

```yaml
            - git init -q repo
            - git -C repo fetch --depth 1 https://github.com/tarodo/clouder-core.git "$GIT_REF"
            - git -C repo checkout -q FETCH_HEAD
```

Add a statement to `data "aws_iam_policy_document" "dbt"`:

```hcl
  statement {
    sid       = "ReadDeployedCommit"
    actions   = ["ssm:GetParameters"]
    resources = [aws_ssm_parameter.dbt_git_ref.arn]
  }
```

In `.github/workflows/deploy.yml`, after the `Smoke test` step:

```yaml
      # The nightly dbt build (CodeBuild) runs this commit, not whatever main is at 00:30.
      - name: Record the deployed commit for the nightly build
        working-directory: .
        run: |
          aws ssm put-parameter --name /clouder/dbt/git_ref --value "$GITHUB_SHA" \
            --type String --overwrite >/dev/null
```

Fix the README count: `grep -c '^resource "' infra/*.tf | awk -F: '{s+=$2} END {print s}'` → replace `242 Terraform resource definitions` (both places) with the printed number (expected 243).

- [ ] **Step 4: Run tests, fmt, validate**

Run: `PYTHONPATH=src .venv/bin/pytest tests/unit/test_lakehouse_infra.py tests/unit/test_deploy_order.py tests/unit/test_readme.py -q && (cd infra && terraform fmt -check && terraform validate)`
Expected: all pass; valid.

- [ ] **Step 5: Commit** (e.g. `feat(lakehouse): nightly dbt runs the deployed commit`)

---

### Task 4: Lakehouse and lineage documents

**Files:**
- Modify: `docs/data/lakehouse.md`
- Modify: `docs/data/README.md`

- [ ] **Step 1: Grain table** — in `docs/data/lakehouse.md`, right after the `What changed` ASCII diagram, insert:

```markdown
| Model | One row per | Key | Built |
|---|---|---|---|
| `stg_events` (view) | bronze event as delivered, Firehose redeliveries included; deleted users dropped | — | on read |
| `silver.events` | event (`event_id`), earliest copy kept | `event_id` | incremental MERGE, 2-day lookback |
| `silver.dim_track_history` | version of a track's catalog attributes | `track_id`, `valid_from` | incremental SCD2 from the daily snapshots |
| `gold.fct_play` | play: a `playback_play` and the pauses, resumes and end that follow it | `play_event_id` | rebuilt nightly |
```

- [ ] **Step 2: Nightly build paragraph** — replace the sentence `CodeBuild clones `main`, installs the pinned dbt versions and runs `dbt build` (unit tests stay in CI), then `dbt source freshness`.` with:

```markdown
CodeBuild checks out the commit the last green deploy recorded in SSM (`/clouder/dbt/git_ref`), installs the pinned dbt versions and runs `dbt build` (unit tests stay in CI), then `dbt source freshness`.
```

and after `…instead of passing on a stale style dictionary.` add:

```markdown
The check runs after the build on purpose: `silver.events` does not depend on the export, and `dim_track_history` cannot be damaged by a short snapshot — a track missing from one night's snapshot keeps its open version (absence never closes a version), and the next complete snapshot catches up.
```

- [ ] **Step 3: Fix the drifted rollback sentence** — replace `set in `.github/workflows/deploy.yml` after the first green build (2026-10-07); removing that `-var` is the rollback.` with ``set in `infra/prod.tfvars` after the first green build (2026-10-07); clearing it there is the rollback.``

- [ ] **Step 4: Export section** — append before `## How to run`:

```markdown
**Catalog export.** `clouder-prod-catalog-export` (00:00 UTC) writes one snapshot a day under `bronze/catalog_export/snapshot_dt=<date>/<table>/`, `clouder_styles` last. It pages by primary key (`WHERE (keys) > (last row) ORDER BY keys LIMIT 500`) through the Data API and logs rows, pages and milliseconds per table (`catalog_export_table_written`). It paged with `OFFSET` until 2026-10-11: each page re-scanned every earlier row, the run grew from 211 s to over 300 s in four nights as auto-ingest filled the catalog, and timed out two nights running; after the switch: <filled in Task 5>.
```

- [ ] **Step 5: Aurora-side lineage** — in `docs/data/README.md`, before `See also`, add:

````markdown
## Lineage, Aurora side

```text
Beatport API
  │ auto-ingest / admin ingest            ingest_runs(run_id, style_id, iso_year, iso_week, raw_s3_key)
  ▼
s3 raw/bp/releases/style_id=/year=/week=/releases.json.gz   (raw_s3_key)
  │ contract screen (contracts.py) ──▶ raw/bp/releases/_quarantine/run_id=<run_id>/
  ▼
source_entities(source, entity_type, external_id, last_run_id)  ·  source_relations(from_*, to_*, last_run_id)
  │ canonicalize.py, set-based
  ▼
identity_map(source, entity_type, external_id → clouder_entity_type, clouder_id, match_type, confidence)
  ▼
clouder_tracks / clouder_artists / clouder_albums / clouder_labels / clouder_track_artists / clouder_styles   (id = clouder_id)
  ├─▶ vendor_track_map(clouder_track_id, vendor → vendor_track_id, match_type, confidence) · match_review_queue
  ├─▶ per-user overlay: categories → category_tracks(category_id, track_id), triage_*, playlists
  └─▶ catalog export (nightly) → bronze/catalog_export/snapshot_dt=/<table>/ → silver.dim_track_history(track_id, valid_from) → gold.fct_play
```

Every canonical row can be traced back to the raw object it came from: `identity_map` → `source_entities.last_run_id` → `ingest_runs.raw_s3_key`. The lake side is in the [dbt lineage](https://tarodo.github.io/clouder-core/lineage/).
````

- [ ] **Step 6: Guards and commit**

Run: `PYTHONPATH=src .venv/bin/pytest tests/unit/test_docs_freshness.py tests/unit/test_docs_links.py tests/unit/test_repo_hygiene.py -q && PYTHONPATH=src .venv/bin/pytest -q`
Expected: all pass. Commit (e.g. `docs(lakehouse): grain, export paging, lineage`).

---

### Task 5: Ship, measure, verify

- [ ] **Step 1: PR** — push, `gh pr create` with title/body from `caveman:caveman-commit`; wait for checks; read the Terraform plan (expected: 1 SSM parameter added; CodeBuild project and dbt role policy updated in place; Lambda code updated; nothing destroyed).
- [ ] **Step 2: Merge, watch the deploy** — success, smoke 9/9, the new "Record the deployed commit" step green; `aws ssm get-parameter --name /clouder/dbt/git_ref --query Parameter.Value` equals the merge commit.
- [ ] **Step 3: Measure** — `aws lambda invoke --cli-read-timeout 0 --function-name clouder-prod-catalog-export --payload '{"snapshot_dt":"<today UTC>"}' --cli-binary-format raw-in-base64-out /dev/stdout`; then Logs Insights over `catalog_export_table_written` for table_name, total_count, api_pages_fetched, duration_ms. Compare with 314.6 s (2026-10-11 03:34 UTC, OFFSET).
- [ ] **Step 4: Run the nightly transform once by hand** — `aws stepfunctions start-execution --state-machine-arn $(cd infra && terraform output -raw transform_state_machine_arn)`; expected SUCCEEDED, the CodeBuild log shows the fetch of the recorded SHA.
- [ ] **Step 5: Write the numbers** — fill the `<filled in Task 5>` placeholder in `docs/data/lakehouse.md` with the measured total and the slowest table; small docs PR (or the next phase's branch if it is already open); merge.
- [ ] **Step 6: Board** — phase 2 → `done` with the plan path, PRs and the before/after numbers. Check the next nightly export (00:00 UTC) on the following loop tick.

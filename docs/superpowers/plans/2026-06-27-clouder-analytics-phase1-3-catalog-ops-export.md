# Phase 1 · Increment 3 — Catalog + Ops Export Lambdas — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to execute this plan. Steps use checkbox (- [ ]) syntax.

**Goal:** Land the two daily batch exporters of the analytics contour: `catalog_export` (Aurora dims → `bronze/catalog_export/` NDJSON, Data API only, no `psycopg`/`pyarrow`/`awswrangler`) and `ops_log_export` (worker/dispatch/collector CloudWatch logs → `bronze/ops/` NDJSON, reading the event name from the structlog `message` key). Plus their two lightweight Glue tables, two least-privilege IAM roles, and two `aws_lambda_function` entries off the shared zip.

**Architecture:** Both are standalone Lambdas in the existing collector package (shared zip `local.lambda_zip_file`, distinct entry points — same pattern as `auto_enrich_dispatch_worker`). Each has a pure injectable core (`export_catalog(data_api, s3, ...)`, `export_ops_logs(logs, s3, ...)`) unit-tested with fakes, and a thin `lambda_handler` that builds boto3/Data-API clients from env. They are **EventBridge-triggered** (the schedule/Step-Functions wiring lands in Increment 4) — **not** API routes, so the three-place route rule, the `/v1` CloudFront/Vite prefix, OpenAPI regen, and `schema.d.ts` are all out of scope this increment. `catalog_export` reaches Aurora **only** via the RDS Data API (`data_api.execute()`, ADR-0001). NDJSON (not Parquet) keeps the collector zip free of `pyarrow`/`awswrangler` (~120MB) — a Glue table types columns and Athena casts on read (§6).

**Tech Stack:** Python 3.12 (collector package), `boto3` (`rds-data`, `s3`, `logs`, lazy-imported), `structlog` logging via `logging_utils.log_event`, pytest unit tests with hand-rolled fakes, Terraform (`aws_glue_catalog_table`, `aws_iam_role`, `aws_lambda_function`, `aws_cloudwatch_log_group`).

**Spec:** docs/superpowers/specs/2026-06-27-clouder-analytics-pipeline-design.md — §6 (catalog dim sourcing), §7 (gold dims), §11 + §16.1 (ops domain / Dashboard 5), §13 (per-function least-privilege IAM), §17 step 3 (rollout). Grounded against `logging_utils.py:111` (EventRenamer→`message`), `logging_utils.py:153-155,168` (`_sanitize_event` keeps `level`, `log_event` injects it), `repositories.py:866-905` (LIMIT/OFFSET paging), `data_api.py` (`DataAPIClient.execute`), `db_models.py:111-245` + `alembic/versions/20260427_14_categories.py` (real columns), `infra/{lambda,iam,logging,main}.tf`.

---

## File structure

| File | Create/Modify | One responsibility |
|---|---|---|
| `src/collector/catalog_export_handler.py` | Create | Page Aurora dim tables through the Data API; write NDJSON to `bronze/catalog_export/snapshot_dt=…/<table>/part-NNNNN.json`. No psycopg/columnar deps. |
| `src/collector/ops_log_export_handler.py` | Create | Pull a 24h window from the worker/dispatch/collector log groups via `filter_log_events`; keep curated ops events (event name read from `message`); project to `_OPS_FIELDS`; write NDJSON to `bronze/ops/dt=…/<group-slug>.json`. |
| `tests/unit/test_catalog_export_handler.py` | Create | Exercise paging, NDJSON serialization, `deleted_at` export, the Data-API-safe default page size, and the no-heavy-imports AST guard. |
| `tests/unit/test_ops_log_export_handler.py` | Create | Exercise the epoch-ms window, reading event name from `message` (not `event`), ops/non-ops/non-JSON filtering, per-group NDJSON, and `nextToken` pagination. |
| `infra/analytics.tf` | Create | Shared analytics-lakehouse foundation: the lake S3 bucket + `clouder_analytics` Glue database. (Single declaration home; Increment 2's Firehose/bronze-events table and Increment 5's analytics-api reference these.) |
| `infra/analytics_export.tf` | Create | This increment's resources: the two lightweight Glue tables, two least-privilege IAM roles+policies, two log groups, two `aws_lambda_function` entries (shared zip), and local names. |

No modification to `infra/main.tf` (the two lambda names live in a `locals` block inside `analytics_export.tf` — keeps the increment's footprint contained). No `generate_openapi.py`/`schema.d.ts`/`vite.config.ts`/`frontend.tf` changes (no API route this increment).

---

## Tasks

### Task 0: Branch off origin/main

**Files:** none (git only).

- [ ] Local `main` may lag `origin/main` (worktree-stale-main gotcha). Fetch and branch:
  ```bash
  git -C /Users/roman/Projects/clouder-projects/clouder-core/.claude/worktrees/service_improve fetch origin
  git -C /Users/roman/Projects/clouder-projects/clouder-core/.claude/worktrees/service_improve checkout -b feat/analytics-catalog-ops-export origin/main
  ```
  Expected output: `Switched to a new branch 'feat/analytics-catalog-ops-export'`. (Branch name carries no user/agent prefix — CLAUDE.md policy.)

---

### Task 1: `catalog_export` handler (Data API → NDJSON)

**Files:**
- Create `src/collector/catalog_export_handler.py`
- Test: Create `tests/unit/test_catalog_export_handler.py`
- Existing seams cited: `src/collector/data_api.py:14-49` (`DataAPIClient.execute`), `src/collector/data_api.py:110-120` (`create_default_data_api_client`), `src/collector/settings.py:111-118,244` (`DataApiSettings`/`get_data_api_settings`), `src/collector/repositories.py:866-905` (LIMIT/OFFSET paging precedent — note: that path uses small UI-supplied page sizes), real columns from `db_models.py:111-245` + `alembic/versions/20260427_14_categories.py:21-41,63-76`.

- [ ] **Write the failing test file** `tests/unit/test_catalog_export_handler.py` (FULL code):
  ```python
  import ast
  import json
  import pathlib
  from datetime import date, datetime, timezone

  import collector.catalog_export_handler as ceh
  from collector.catalog_export_handler import export_catalog


  class FakeS3:
      def __init__(self) -> None:
          self.objects: dict[str, bytes] = {}

      def put_object(self, **kw):
          self.objects[kw["Key"]] = kw["Body"]
          return {}


  class FakeDataAPI:
      """Mimics DataAPIClient.execute with offset paging over canned rows."""

      def __init__(self, rows_by_table: dict[str, list[dict]]) -> None:
          self.rows_by_table = rows_by_table
          self.calls: list[tuple[str, dict]] = []

      def execute(self, sql, params=None, transaction_id=None):
          self.calls.append((sql, params))
          table = next(t for t in self.rows_by_table if f"FROM {t} " in sql)
          off, lim = params["offset"], params["limit"]
          return self.rows_by_table[table][off : off + lim]


  def _empty_tables(except_for: dict[str, list[dict]]) -> dict[str, list[dict]]:
      tables = [
          "clouder_tracks", "clouder_artists", "clouder_track_artists",
          "clouder_labels", "clouder_albums", "categories", "category_tracks",
      ]
      out = {t: [] for t in tables}
      out.update(except_for)
      return out


  def test_paging_writes_one_ndjson_part_per_page() -> None:
      tracks = [{"id": f"t{i}", "title": f"T{i}"} for i in range(5)]
      api = FakeDataAPI(_empty_tables({"clouder_tracks": tracks}))
      s3 = FakeS3()

      counts = export_catalog(api, s3, "lake", "2026-06-27", page=2)

      assert counts["clouder_tracks"] == 5
      keys = sorted(k for k in s3.objects if "clouder_tracks" in k)
      assert keys == [
          "bronze/catalog_export/snapshot_dt=2026-06-27/clouder_tracks/part-00000.json",
          "bronze/catalog_export/snapshot_dt=2026-06-27/clouder_tracks/part-00001.json",
          "bronze/catalog_export/snapshot_dt=2026-06-27/clouder_tracks/part-00002.json",
      ]
      assert s3.objects[keys[0]].decode().count("\n") == 2  # full page
      assert s3.objects[keys[2]].decode().count("\n") == 1  # leftover row


  def test_default_page_is_data_api_safe() -> None:
      # The wired default page size must stay under the RDS Data API ~1MB
      # per-ExecuteStatement response cap for wide dims (clouder_tracks ~15 cols).
      # A 5000-row page of a wide dim would risk "Database response exceeded size
      # limit" at runtime; this pins the default so the green suite means the
      # production page size is actually checked, not just the page=2 test path.
      assert 0 < ceh._PAGE <= 1000


  def test_empty_table_writes_no_object() -> None:
      api = FakeDataAPI(_empty_tables({}))
      s3 = FakeS3()

      counts = export_catalog(api, s3, "lake", "2026-06-27", page=2)

      assert counts == {
          "clouder_tracks": 0, "clouder_artists": 0, "clouder_track_artists": 0,
          "clouder_labels": 0, "clouder_albums": 0, "categories": 0,
          "category_tracks": 0,
      }
      assert s3.objects == {}


  def test_ndjson_serializes_dates_via_default_str() -> None:
      rows = [{"id": "t1", "created_at": datetime(2026, 6, 27, tzinfo=timezone.utc),
               "publish_date": date(2026, 6, 1)}]
      api = FakeDataAPI(_empty_tables({"clouder_tracks": rows}))
      s3 = FakeS3()

      export_catalog(api, s3, "lake", "2026-06-27", page=10)

      key = "bronze/catalog_export/snapshot_dt=2026-06-27/clouder_tracks/part-00000.json"
      parsed = json.loads(s3.objects[key].decode().splitlines()[0])
      assert parsed["publish_date"] == "2026-06-01"
      assert parsed["created_at"].startswith("2026-06-27")


  def test_categories_query_selects_deleted_at() -> None:
      # deleted_at must be exported so dbt can filter soft-deletes (recon gotcha).
      assert "deleted_at" in dict(ceh._EXPORTS)["categories"]


  def test_no_psycopg_or_columnar_imports() -> None:
      tree = ast.parse(pathlib.Path(ceh.__file__).read_text())
      imported: set[str] = set()
      for node in ast.walk(tree):
          if isinstance(node, ast.Import):
              imported.update(a.name.split(".")[0] for a in node.names)
          elif isinstance(node, ast.ImportFrom) and node.module:
              imported.add(node.module.split(".")[0])
      assert imported & {
          "psycopg", "psycopg2", "pyarrow", "awswrangler", "pandas"
      } == set()
  ```
  (The guard test is an **AST import scan** — immune to docstring wording, so the docstring may say anything. Satisfies MUST-FIX #3: the check is on imports, not raw text. `test_default_page_is_data_api_safe` pins the wired production page size so the green suite covers the default, not only the `page=2` path.)

- [ ] **Run it, expect FAIL** (module does not exist yet):
  ```bash
  PYTHONPATH=/Users/roman/Projects/clouder-projects/clouder-core/.claude/worktrees/service_improve/src \
  /Users/roman/Projects/clouder-projects/clouder-core/.venv/bin/python -m pytest \
  /Users/roman/Projects/clouder-projects/clouder-core/.claude/worktrees/service_improve/tests/unit/test_catalog_export_handler.py -q
  ```
  Expected: collection error, last lines contain `ModuleNotFoundError: No module named 'collector.catalog_export_handler'` and the summary `1 error` (exit code 2).

- [ ] **Write the minimal implementation** `src/collector/catalog_export_handler.py` (FULL code):
  ```python
  """Daily Aurora catalog snapshot to the analytics lake (bronze/catalog_export/).

  Runs the dim read queries through the RDS Data API (ADR-0001: Aurora is reached
  only via the Data API at runtime), pages with LIMIT/OFFSET ordered by primary
  key, and writes line-delimited JSON to S3. Intentionally lightweight: no
  columnar or DataFrame dependency is bundled, so the collector zip stays small —
  a Glue table types the columns and Athena casts on read (spec section 6).
  """
  from __future__ import annotations

  import json
  import os
  from datetime import datetime, timezone
  from typing import Any, Iterable

  from .data_api import DataAPIClient, create_default_data_api_client
  from .logging_utils import log_event
  from .settings import get_data_api_settings

  # (table, sql). Each SQL takes :limit/:offset and ORDERs BY primary key so paging
  # is stable and keyset-upgradeable. Columns are the real db_models.py /
  # categories-migration names. See _PAGE for the page-size constraint.
  _EXPORTS: tuple[tuple[str, str], ...] = (
      ("clouder_tracks",
       "SELECT id, title, bpm, key_name, key_camelot, spotify_release_date, "
       "publish_date, album_id, style_id, isrc, release_type, is_ai_suspected, "
       "origin, created_at, updated_at "
       "FROM clouder_tracks ORDER BY id LIMIT :limit OFFSET :offset"),
      ("clouder_artists",
       "SELECT id, name, normalized_name, is_ai_suspected, created_at, updated_at "
       "FROM clouder_artists ORDER BY id LIMIT :limit OFFSET :offset"),
      ("clouder_track_artists",
       "SELECT track_id, artist_id, role "
       "FROM clouder_track_artists ORDER BY track_id, artist_id, role "
       "LIMIT :limit OFFSET :offset"),
      ("clouder_labels",
       "SELECT id, name, normalized_name, is_ai_suspected, created_at, updated_at "
       "FROM clouder_labels ORDER BY id LIMIT :limit OFFSET :offset"),
      ("clouder_albums",
       "SELECT id, title, label_id, release_date, release_type, created_at, "
       "updated_at FROM clouder_albums ORDER BY id LIMIT :limit OFFSET :offset"),
      ("categories",
       "SELECT id, user_id, style_id, name, normalized_name, position, "
       "created_at, updated_at, deleted_at "
       "FROM categories ORDER BY id LIMIT :limit OFFSET :offset"),
      ("category_tracks",
       "SELECT category_id, track_id, added_at, source_triage_block_id "
       "FROM category_tracks ORDER BY category_id, track_id "
       "LIMIT :limit OFFSET :offset"),
  )

  # ponytail: the BINDING constraint on page size is the RDS Data API ~1MB
  # per-ExecuteStatement response cap, NOT OFFSET scan cost. 1000 rows of the
  # widest dim (clouder_tracks, ~15 columns) stays comfortably under 1MB at the
  # stated daily-snapshot volume (spec section 6). If a wider dim ever raises
  # "Database response exceeded size limit", halve this. OFFSET cost is a non-issue
  # at this volume; switch to PK-range keyset only if that ever changes.
  _PAGE = 1000


  def _ndjson(rows: Iterable[dict[str, Any]]) -> bytes:
      # default=str renders datetime/date/Decimal deterministically (ISO-ish);
      # Athena/dbt cast on read.
      return "".join(
          json.dumps(r, ensure_ascii=False, separators=(",", ":"), default=str) + "\n"
          for r in rows
      ).encode("utf-8")


  def export_catalog(
      data_api: DataAPIClient,
      s3_client: Any,
      bucket: str,
      snapshot_dt: str,
      page: int = _PAGE,
  ) -> dict[str, int]:
      counts: dict[str, int] = {}
      for table, sql in _EXPORTS:
          offset = part = total = 0
          while True:
              rows = data_api.execute(sql, {"limit": page, "offset": offset})
              if not rows:
                  break
              key = (
                  f"bronze/catalog_export/snapshot_dt={snapshot_dt}/{table}/"
                  f"part-{part:05d}.json"
              )
              s3_client.put_object(
                  Bucket=bucket, Key=key, Body=_ndjson(rows),
                  ContentType="application/x-ndjson",
              )
              total += len(rows)
              part += 1
              if len(rows) < page:
                  break
              offset += page
          counts[table] = total
          log_event("INFO", "catalog_export_table_written",
                    s3_bucket=bucket, total_count=total)
      return counts


  def lambda_handler(event: Any, context: Any) -> dict[str, Any]:
      import boto3

      settings = get_data_api_settings()
      if not settings.is_configured:
          raise RuntimeError("Aurora Data API not configured")
      data_api = create_default_data_api_client(
          resource_arn=str(settings.aurora_cluster_arn),
          secret_arn=str(settings.aurora_secret_arn),
          database=settings.aurora_database,
      )
      bucket = os.environ["ANALYTICS_LAKE_BUCKET"]
      snapshot_dt = (event or {}).get("snapshot_dt") or datetime.now(
          timezone.utc
      ).strftime("%Y-%m-%d")
      counts = export_catalog(data_api, boto3.client("s3"), bucket, snapshot_dt)
      log_event("INFO", "catalog_export_completed", item_count=sum(counts.values()))
      return {"snapshot_dt": snapshot_dt, "counts": counts}
  ```

- [ ] **Run it, expect PASS**:
  ```bash
  PYTHONPATH=/Users/roman/Projects/clouder-projects/clouder-core/.claude/worktrees/service_improve/src \
  /Users/roman/Projects/clouder-projects/clouder-core/.venv/bin/python -m pytest \
  /Users/roman/Projects/clouder-projects/clouder-core/.claude/worktrees/service_improve/tests/unit/test_catalog_export_handler.py -q
  ```
  Expected: last line `6 passed` (exit code 0).

- [ ] **Commit.** Generate the subject via the `caveman:caveman-commit` skill (CLAUDE.md forbids hand-written subjects), then commit with a non-indented heredoc body (EOF at column 0, no `Co-Authored-By`):
  ```bash
  git -C /Users/roman/Projects/clouder-projects/clouder-core/.claude/worktrees/service_improve add src/collector/catalog_export_handler.py tests/unit/test_catalog_export_handler.py
  git -C /Users/roman/Projects/clouder-projects/clouder-core/.claude/worktrees/service_improve commit -m "$(cat <<'EOF'
  feat(analytics): add catalog_export handler

  Page Aurora dims through the Data API to bronze/catalog_export NDJSON.
  No psycopg/pyarrow/awswrangler in the collector zip; Glue types on read.
  EOF
  )"
  ```
  (Subject above is illustrative — use the caveman-commit output. Conventional Commits required.) Expected: `git` prints `2 files changed`.

---

### Task 2: `ops_log_export` handler (CloudWatch Logs → NDJSON)

**Files:**
- Create `src/collector/ops_log_export_handler.py`
- Test: Create `tests/unit/test_ops_log_export_handler.py`
- Existing seams cited: `logging_utils.py:111` (EventRenamer renames `event`→`message`), `logging_utils.py:153-155` (`_sanitize_event` keeps `level`), `logging_utils.py:168` (`log_event` passes `level=level.upper()`), `logging_utils.py:14-102` (`ALLOWED_LOG_FIELDS` — `duration_ms`, `source_hint`, `completed_phases`, `failed_after`, `vendor`, `phase`, `attempt`, `status_code`), real event names emitted by the workers (`label_enrichment_completed`, `canonicalization_completed`, `auto_enrich_dispatched`, etc. — confirmed by grep).

- [ ] **Write the failing test file** `tests/unit/test_ops_log_export_handler.py` (FULL code):
  ```python
  import json

  import collector.ops_log_export_handler as ole
  from collector.ops_log_export_handler import _day_window, _ops_records, export_ops_logs


  class FakeS3:
      def __init__(self) -> None:
          self.objects: dict[str, bytes] = {}

      def put_object(self, **kw):
          self.objects[kw["Key"]] = kw["Body"]
          return {}


  class FakeLogs:
      def __init__(self, by_group, paginate=False) -> None:
          self.by_group = by_group
          self.paginate = paginate
          self.calls: list[dict] = []

      def filter_log_events(self, **kw):
          self.calls.append(kw)
          msgs = self.by_group.get(kw["logGroupName"], [])
          if self.paginate and "nextToken" not in kw:
              half = len(msgs) // 2
              return {"events": [{"message": m} for m in msgs[:half]], "nextToken": "more"}
          if self.paginate:
              half = len(msgs) // 2
              return {"events": [{"message": m} for m in msgs[half:]]}
          return {"events": [{"message": m} for m in msgs]}


  def _line(message, **fields):
      # REAL structlog JSON shape: event name under 'message' (EventRenamer),
      # top-level timestamp/level, allowlisted metric fields alongside.
      return json.dumps({"timestamp": "2026-06-27T10:00:00Z", "level": "INFO",
                         "message": message, **fields})


  def test_day_window_epoch_ms() -> None:
      assert _day_window("2026-06-27") == (1782518400000, 1782604800000)


  def test_reads_event_name_from_message_not_event() -> None:
      real = _line("label_enrichment_completed", duration_ms=1234, labels_total=3)
      synthetic = json.dumps({"timestamp": "t", "level": "INFO",
                              "event": "label_enrichment_completed", "duration_ms": 9})

      records = _ops_records([real, synthetic])

      assert len(records) == 1  # synthetic {"event":...} has no 'message' -> dropped
      assert records[0]["message"] == "label_enrichment_completed"
      assert records[0]["duration_ms"] == 1234
      assert "labels_total" not in records[0]  # not in _OPS_FIELDS -> projected out


  def test_drops_non_ops_event_and_non_json() -> None:
      assert "collection_completed" not in ole._OPS_EVENTS  # negative-event contract
      keep = _line("auto_enrich_dispatched", source_hint="triage", claimed=4)
      non_ops = _line("collection_completed", item_count=7)
      junk = "START RequestId: abc Version: $LATEST"

      records = _ops_records([keep, non_ops, junk])

      assert [r["message"] for r in records] == ["auto_enrich_dispatched"]
      assert records[0]["source_hint"] == "triage"


  def test_export_writes_per_group_ndjson_with_window() -> None:
      grp = "/aws/lambda/beatport-prod-label-enricher-worker"
      logs = FakeLogs({
          grp: [
              _line("label_enrichment_completed", duration_ms=10),
              _line("label_enrichment_worker_invoked", sqs_record_count=2),
          ],
          "/aws/lambda/beatport-prod-collector-api": [],
      })
      s3 = FakeS3()

      counts = export_ops_logs(
          logs, s3, "lake",
          [grp, "/aws/lambda/beatport-prod-collector-api"],
          "2026-06-27", 1782518400000, 1782604800000,
      )

      assert counts[grp] == 2
      assert counts["/aws/lambda/beatport-prod-collector-api"] == 0
      assert logs.calls[0]["startTime"] == 1782518400000
      assert logs.calls[0]["endTime"] == 1782604800000
      assert "bronze/ops/dt=2026-06-27/beatport-prod-label-enricher-worker.json" in s3.objects
      assert "bronze/ops/dt=2026-06-27/beatport-prod-collector-api.json" not in s3.objects  # empty -> no object


  def test_paginates_with_next_token() -> None:
      grp = "/aws/lambda/beatport-prod-auto-enrich-dispatch-worker"
      logs = FakeLogs({grp: [
          _line("auto_enrich_dispatched", claimed=1),
          _line("auto_enrich_dispatched", claimed=2),
          _line("auto_enrich_dispatched", claimed=3),
          _line("auto_enrich_dispatched", claimed=4),
      ]}, paginate=True)
      s3 = FakeS3()

      counts = export_ops_logs(logs, s3, "lake", [grp],
                               "2026-06-27", 1782518400000, 1782604800000)

      assert counts[grp] == 4
      assert len(logs.calls) == 2
      assert logs.calls[1]["nextToken"] == "more"
  ```
  (Epoch-ms constants verified: `2026-06-27T00:00:00Z = 1782518400000`, `2026-06-28T00:00:00Z = 1782604800000`. Fixtures use the REAL `{"message": ...}` structlog shape; the synthetic `{"event": ...}` row is the negative case that proves we read `message`. `ole` is referenced via `ole._OPS_EVENTS` to pin the negative-event contract — no dead import. Satisfies MUST-FIX #1, #4.)

- [ ] **Run it, expect FAIL**:
  ```bash
  PYTHONPATH=/Users/roman/Projects/clouder-projects/clouder-core/.claude/worktrees/service_improve/src \
  /Users/roman/Projects/clouder-projects/clouder-core/.venv/bin/python -m pytest \
  /Users/roman/Projects/clouder-projects/clouder-core/.claude/worktrees/service_improve/tests/unit/test_ops_log_export_handler.py -q
  ```
  Expected: collection error, last lines contain `ModuleNotFoundError: No module named 'collector.ops_log_export_handler'`, summary `1 error` (exit code 2).

- [ ] **Write the minimal implementation** `src/collector/ops_log_export_handler.py` (FULL code):
  ```python
  """Daily ops/pipeline-health export: enrichment + latency metrics from the
  worker / auto-enrich-dispatch / collector CloudWatch log groups to the
  analytics lake (bronze/ops/), for Dashboard 5 (spec sections 11, 16.1).

  Each Lambda log line is one structlog JSON object. structlog's EventRenamer
  maps the event name to the 'message' key (logging_utils.py:111), so the event
  name is read from 'message', never 'event'. We keep the curated ops events and
  project each record down to _OPS_FIELDS.
  """
  from __future__ import annotations

  import json
  import os
  from datetime import datetime, timezone
  from typing import Any

  from .logging_utils import log_event

  # Event names worth landing for Dashboard 5 — read from the 'message' key.
  # These are the real strings the workers emit (grep-confirmed). ponytail:
  # curated allowlist of ~13 names; widen by one line if a dashboard needs more.
  _OPS_EVENTS = frozenset({
      "canonicalization_worker_invoked", "canonicalization_completed",
      "spotify_worker_invoked", "spotify_search_completed",
      "vendor_match_worker_invoked",
      "label_enrichment_worker_invoked", "label_enrichment_completed",
      "artist_enrichment_worker_invoked", "artist_enrichment_completed",
      "auto_enrich_dispatch_started", "auto_enrich_dispatched",
      "auto_enrich_skipped_disabled", "auto_enrich_enqueue_partial_failure",
  })

  # Fields projected into bronze/ops. NOTE on the two non-allowlist keys we keep:
  # 'timestamp' is set by TimeStamper, and 'level' is injected by log_event
  # (level=level.upper(), logging_utils.py:168) and preserved by _sanitize_event
  # (logging_utils.py:153-155) — both are TOP-LEVEL structlog keys, and NEITHER is
  # an ALLOWED_LOG_FIELDS metric field. 'message' is the event name (EventRenamer
  # renamed event->message, logging_utils.py:111). The rest ARE real
  # ALLOWED_LOG_FIELDS metric fields (logging_utils.py:14-102).
  _OPS_FIELDS = (
      "timestamp", "level", "message",
      "duration_ms", "source_hint", "completed_phases", "failed_after",
      "vendor", "phase", "attempt", "status_code",
      "candidate_labels", "candidate_artists", "claimed", "skipped", "run_id",
  )


  def _project(record: dict[str, Any]) -> dict[str, Any]:
      return {k: record[k] for k in _OPS_FIELDS if k in record}


  def _ops_records(messages: list[str]) -> list[dict[str, Any]]:
      out: list[dict[str, Any]] = []
      for raw in messages:
          try:
              rec = json.loads(raw)
          except (ValueError, TypeError):
              continue
          if not isinstance(rec, dict):
              continue
          if rec.get("message") not in _OPS_EVENTS:  # event name lives under 'message'
              continue
          out.append(_project(rec))
      return out


  def _day_window(dt: str) -> tuple[int, int]:
      day = datetime.strptime(dt, "%Y-%m-%d").replace(tzinfo=timezone.utc)
      start_ms = int(day.timestamp() * 1000)
      return start_ms, start_ms + 86_400_000


  def export_ops_logs(
      logs_client: Any,
      s3_client: Any,
      bucket: str,
      log_groups: list[str],
      dt: str,
      start_ms: int,
      end_ms: int,
  ) -> dict[str, int]:
      counts: dict[str, int] = {}
      for group in log_groups:
          messages: list[str] = []
          kwargs: dict[str, Any] = {
              "logGroupName": group, "startTime": start_ms, "endTime": end_ms,
          }
          while True:
              resp = logs_client.filter_log_events(**kwargs)
              messages.extend(e["message"] for e in resp.get("events", []))
              token = resp.get("nextToken")
              if not token:
                  break
              kwargs["nextToken"] = token
          records = _ops_records(messages)
          counts[group] = len(records)
          if not records:
              continue
          slug = group.rsplit("/", 1)[-1]
          body = "".join(
              json.dumps(r, ensure_ascii=False, separators=(",", ":")) + "\n"
              for r in records
          ).encode("utf-8")
          s3_client.put_object(
              Bucket=bucket, Key=f"bronze/ops/dt={dt}/{slug}.json", Body=body,
              ContentType="application/x-ndjson",
          )
      return counts


  def lambda_handler(event: Any, context: Any) -> dict[str, Any]:
      import boto3

      bucket = os.environ["ANALYTICS_LAKE_BUCKET"]
      groups = [g.strip() for g in os.environ["OPS_LOG_GROUPS"].split(",") if g.strip()]
      dt = (event or {}).get("dt") or datetime.now(timezone.utc).strftime("%Y-%m-%d")
      start_ms, end_ms = _day_window(dt)
      counts = export_ops_logs(
          boto3.client("logs"), boto3.client("s3"), bucket, groups, dt, start_ms, end_ms,
      )
      log_event("INFO", "ops_log_export_completed", item_count=sum(counts.values()))
      return {"dt": dt, "counts": counts}
  ```

- [ ] **Run it, expect PASS**:
  ```bash
  PYTHONPATH=/Users/roman/Projects/clouder-projects/clouder-core/.claude/worktrees/service_improve/src \
  /Users/roman/Projects/clouder-projects/clouder-core/.venv/bin/python -m pytest \
  /Users/roman/Projects/clouder-projects/clouder-core/.claude/worktrees/service_improve/tests/unit/test_ops_log_export_handler.py -q
  ```
  Expected: last line `5 passed` (exit code 0).

- [ ] **Commit** (caveman-commit subject, heredoc body, no AI trailer):
  ```bash
  git -C /Users/roman/Projects/clouder-projects/clouder-core/.claude/worktrees/service_improve add src/collector/ops_log_export_handler.py tests/unit/test_ops_log_export_handler.py
  git -C /Users/roman/Projects/clouder-projects/clouder-core/.claude/worktrees/service_improve commit -m "$(cat <<'EOF'
  feat(analytics): add ops_log_export handler

  Pull worker/dispatch/collector log groups to bronze/ops NDJSON; event
  name read from the structlog 'message' key (EventRenamer), 24h window.
  EOF
  )"
  ```
  Expected: `2 files changed`.

---

### Task 3: Terraform — Glue tables, IAM roles, Lambda functions, log groups

**Files:**
- Create `infra/analytics.tf` (shared foundation: lake bucket + Glue database)
- Create `infra/analytics_export.tf` (two Glue tables, two roles/policies, two log groups, two lambdas, local names)
- Existing seams cited: `infra/main.tf:1-37` (`local.name_prefix`, `local.lambda_zip_file`, `data.aws_caller_identity.current`), `infra/lambda.tf:289-315` (`auto_enrich_dispatch_worker` shape to mirror), `infra/iam.tf:1-17` (`data.aws_iam_policy_document.lambda_assume`, role pattern), `infra/logging.tf:1-59` (log-group names to read), `infra/rds.tf` (`aws_rds_cluster.aurora`, `master_user_secret`), `infra/s3.tf` (bucket pattern). No test for HCL beyond `terraform validate`.

- [ ] **Run the baseline `terraform validate`** to confirm the config is currently valid before adding files (records the starting state):
  ```bash
  terraform -chdir=/Users/roman/Projects/clouder-projects/clouder-core/.claude/worktrees/service_improve/infra init -backend=false -input=false
  terraform -chdir=/Users/roman/Projects/clouder-projects/clouder-core/.claude/worktrees/service_improve/infra validate
  ```
  Expected: `Success! The configuration is valid.`
  **Network requirement (no offline shortcut):** `terraform validate` needs the AWS provider, which `init` downloads from registry.terraform.io — this requires network access. `infra/.terraform/` does **not** exist in this worktree, so there is no `.terraform-already-present` fallback: `init` must run and succeed first. If the sandbox has no network, the HCL gate (this step and the post-create `validate` below) must be run in an environment that can reach the Terraform registry — do not claim `validate` can run offline here.

- [ ] **Create `infra/analytics.tf`** (shared foundation — FULL code):
  ```hcl
  # Shared analytics-lakehouse foundation: the lake bucket + Glue database.
  # ponytail: single declaration home. Increment 2's Firehose/bronze-events table
  # and Increment 5's analytics-api reference these (aws_s3_bucket.analytics_lake,
  # aws_glue_catalog_database.clouder_analytics) rather than re-declaring them.
  resource "aws_s3_bucket" "analytics_lake" {
    bucket = "${local.name_prefix}-analytics-lake-${data.aws_caller_identity.current.account_id}"
  }

  resource "aws_s3_bucket_public_access_block" "analytics_lake" {
    bucket                  = aws_s3_bucket.analytics_lake.id
    block_public_acls       = true
    block_public_policy     = true
    ignore_public_acls      = true
    restrict_public_buckets = true
  }

  resource "aws_glue_catalog_database" "clouder_analytics" {
    name = "clouder_analytics"
  }
  ```

- [ ] **Create `infra/analytics_export.tf`** (this increment's resources — FULL code):
  ```hcl
  locals {
    catalog_export_lambda_name = "${local.name_prefix}-catalog-export"
    ops_log_export_lambda_name = "${local.name_prefix}-ops-log-export"

    # Source log groups ops_log_export reads. MUST include collector-api (source_hint
    # / dispatch surface) and the auto-enrich-dispatch worker, alongside the
    # canonicalization / spotify / vendor / label / artist enricher workers.
    ops_source_log_groups = [
      aws_cloudwatch_log_group.collector.name,
      aws_cloudwatch_log_group.canonicalization_worker.name,
      aws_cloudwatch_log_group.spotify_search_worker.name,
      aws_cloudwatch_log_group.vendor_match_worker.name,
      aws_cloudwatch_log_group.label_enricher_worker.name,
      aws_cloudwatch_log_group.artist_enricher_worker.name,
      aws_cloudwatch_log_group.auto_enrich_dispatch_worker.name,
    ]
    ops_source_log_group_arns = [
      "${aws_cloudwatch_log_group.collector.arn}:*",
      "${aws_cloudwatch_log_group.canonicalization_worker.arn}:*",
      "${aws_cloudwatch_log_group.spotify_search_worker.arn}:*",
      "${aws_cloudwatch_log_group.vendor_match_worker.arn}:*",
      "${aws_cloudwatch_log_group.label_enricher_worker.arn}:*",
      "${aws_cloudwatch_log_group.artist_enricher_worker.arn}:*",
      "${aws_cloudwatch_log_group.auto_enrich_dispatch_worker.arn}:*",
    ]
  }

  # ── Lightweight Glue tables (types-on-read; dbt builds typed models later) ──

  resource "aws_glue_catalog_table" "catalog_export" {
    database_name = aws_glue_catalog_database.clouder_analytics.name
    name          = "bronze_catalog_export"
    table_type    = "EXTERNAL_TABLE"

    # ponytail: minimal registration over the NDJSON snapshot prefix; the typed
    # per-dim models are dbt's job (Increment 4). Permissive superset columns —
    # the JSON SerDe null-fills absent keys (schema-on-read).
    parameters = {
      classification              = "json"
      "projection.enabled"        = "true"
      "projection.snapshot_dt.type"   = "date"
      "projection.snapshot_dt.format" = "yyyy-MM-dd"
      "projection.snapshot_dt.range"  = "2026-01-01,NOW"
      "projection.tbl.type"   = "enum"
      "projection.tbl.values" = "clouder_tracks,clouder_artists,clouder_track_artists,clouder_labels,clouder_albums,categories,category_tracks"
      "storage.location.template" = "s3://${aws_s3_bucket.analytics_lake.bucket}/bronze/catalog_export/snapshot_dt=$${snapshot_dt}/$${tbl}"
    }

    partition_keys {
      name = "snapshot_dt"
      type = "string"
    }
    partition_keys {
      name = "tbl"
      type = "string"
    }

    storage_descriptor {
      location      = "s3://${aws_s3_bucket.analytics_lake.bucket}/bronze/catalog_export/"
      input_format  = "org.apache.hadoop.mapred.TextInputFormat"
      output_format = "org.apache.hadoop.hive.ql.io.HiveIgnoreKeyTextOutputFormat"

      ser_de_info {
        serialization_library = "org.openx.data.jsonserde.JsonSerDe"
      }

      columns {
        name = "id"
        type = "string"
      }
      columns {
        name = "title"
        type = "string"
      }
      columns {
        name = "name"
        type = "string"
      }
      columns {
        name = "deleted_at"
        type = "string"
      }
      columns {
        name = "created_at"
        type = "string"
      }
      columns {
        name = "updated_at"
        type = "string"
      }
    }
  }

  resource "aws_glue_catalog_table" "ops" {
    database_name = aws_glue_catalog_database.clouder_analytics.name
    name          = "bronze_ops"
    table_type    = "EXTERNAL_TABLE"

    parameters = {
      classification           = "json"
      "projection.enabled"     = "true"
      "projection.dt.type"     = "date"
      "projection.dt.format"   = "yyyy-MM-dd"
      "projection.dt.range"    = "2026-01-01,NOW"
      "storage.location.template" = "s3://${aws_s3_bucket.analytics_lake.bucket}/bronze/ops/dt=$${dt}"
    }

    partition_keys {
      name = "dt"
      type = "string"
    }

    storage_descriptor {
      location      = "s3://${aws_s3_bucket.analytics_lake.bucket}/bronze/ops/"
      input_format  = "org.apache.hadoop.mapred.TextInputFormat"
      output_format = "org.apache.hadoop.hive.ql.io.HiveIgnoreKeyTextOutputFormat"

      ser_de_info {
        serialization_library = "org.openx.data.jsonserde.JsonSerDe"
      }

      columns {
        name = "timestamp"
        type = "string"
      }
      columns {
        name = "level"
        type = "string"
      }
      columns {
        name = "message"
        type = "string"
      }
      columns {
        name = "duration_ms"
        type = "bigint"
      }
      columns {
        name = "source_hint"
        type = "string"
      }
      columns {
        name = "completed_phases"
        type = "string"
      }
      columns {
        name = "failed_after"
        type = "string"
      }
      columns {
        name = "vendor"
        type = "string"
      }
      columns {
        name = "status_code"
        type = "bigint"
      }
    }
  }

  # ── Log groups for the two export Lambdas ──

  resource "aws_cloudwatch_log_group" "catalog_export" {
    name              = "/aws/lambda/${local.catalog_export_lambda_name}"
    retention_in_days = var.log_retention_days
  }

  resource "aws_cloudwatch_log_group" "ops_log_export" {
    name              = "/aws/lambda/${local.ops_log_export_lambda_name}"
    retention_in_days = var.log_retention_days
  }

  # ── catalog_export: own least-privilege role ──
  # NOTE: this is a DELIBERATE least-privilege choice. The existing enrichment
  # workers reuse the shared collector role (iam.tf, aws_iam_role.collector_lambda);
  # these exporters do NOT — each gets its own role so the analytics contour never
  # widens the collector's blast radius (spec section 13).

  resource "aws_iam_role" "catalog_export" {
    name               = "${local.name_prefix}-catalog-export-role"
    assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
  }

  data "aws_iam_policy_document" "catalog_export" {
    statement {
      sid       = "AllowOwnLogs"
      effect    = "Allow"
      actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
      resources = ["${aws_cloudwatch_log_group.catalog_export.arn}:*"]
    }
    statement {
      sid    = "AllowRdsDataApiRead"
      effect = "Allow"
      actions = [
        "rds-data:ExecuteStatement",
        "rds-data:BatchExecuteStatement",
      ]
      resources = [aws_rds_cluster.aurora.arn]
    }
    statement {
      sid       = "AllowReadDatabaseSecret"
      effect    = "Allow"
      actions   = ["secretsmanager:GetSecretValue"]
      resources = [try(aws_rds_cluster.aurora.master_user_secret[0].secret_arn, "*")]
    }
    statement {
      sid       = "AllowS3WriteCatalogExport"
      effect    = "Allow"
      actions   = ["s3:PutObject"]
      resources = ["${aws_s3_bucket.analytics_lake.arn}/bronze/catalog_export/*"]
    }
  }

  resource "aws_iam_role_policy" "catalog_export" {
    name   = "${local.name_prefix}-catalog-export-policy"
    role   = aws_iam_role.catalog_export.id
    policy = data.aws_iam_policy_document.catalog_export.json
  }

  resource "aws_lambda_function" "catalog_export" {
    function_name    = local.catalog_export_lambda_name
    role             = aws_iam_role.catalog_export.arn
    runtime          = "python3.12"
    handler          = "collector.catalog_export_handler.lambda_handler"
    filename         = local.lambda_zip_file
    timeout          = 300
    memory_size      = 256
    source_code_hash = filebase64sha256(local.lambda_zip_file)

    environment {
      variables = {
        ANALYTICS_LAKE_BUCKET = aws_s3_bucket.analytics_lake.bucket
        AURORA_CLUSTER_ARN    = aws_rds_cluster.aurora.arn
        AURORA_SECRET_ARN     = try(aws_rds_cluster.aurora.master_user_secret[0].secret_arn, "")
        AURORA_DATABASE       = var.aurora_database_name
        LOG_LEVEL             = "INFO"
      }
    }

    depends_on = [aws_cloudwatch_log_group.catalog_export]
  }

  # ── ops_log_export: own least-privilege role ──

  resource "aws_iam_role" "ops_log_export" {
    name               = "${local.name_prefix}-ops-log-export-role"
    assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
  }

  data "aws_iam_policy_document" "ops_log_export" {
    statement {
      sid       = "AllowOwnLogs"
      effect    = "Allow"
      actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
      resources = ["${aws_cloudwatch_log_group.ops_log_export.arn}:*"]
    }
    statement {
      sid       = "AllowReadSourceLogGroups"
      effect    = "Allow"
      actions   = ["logs:FilterLogEvents"]
      resources = local.ops_source_log_group_arns
    }
    statement {
      sid       = "AllowS3WriteOps"
      effect    = "Allow"
      actions   = ["s3:PutObject"]
      resources = ["${aws_s3_bucket.analytics_lake.arn}/bronze/ops/*"]
    }
  }

  resource "aws_iam_role_policy" "ops_log_export" {
    name   = "${local.name_prefix}-ops-log-export-policy"
    role   = aws_iam_role.ops_log_export.id
    policy = data.aws_iam_policy_document.ops_log_export.json
  }

  resource "aws_lambda_function" "ops_log_export" {
    function_name    = local.ops_log_export_lambda_name
    role             = aws_iam_role.ops_log_export.arn
    runtime          = "python3.12"
    handler          = "collector.ops_log_export_handler.lambda_handler"
    filename         = local.lambda_zip_file
    timeout          = 120
    memory_size      = 256
    source_code_hash = filebase64sha256(local.lambda_zip_file)

    environment {
      variables = {
        ANALYTICS_LAKE_BUCKET = aws_s3_bucket.analytics_lake.bucket
        OPS_LOG_GROUPS        = join(",", local.ops_source_log_groups)
        LOG_LEVEL             = "INFO"
      }
    }

    depends_on = [aws_cloudwatch_log_group.ops_log_export]
  }
  ```
  (No EventBridge/Step-Functions trigger here — the schedule wiring is Increment 4, spec §9/§17 step 4. These functions are manually invocable now. `rds-data` actions are read-only — no `Begin/Commit/RollbackTransaction` since `export_catalog` never opens a transaction.)

- [ ] **Run `terraform validate`, expect PASS** (the AWS provider is already downloaded by the baseline `init` above; this step does not re-init):
  ```bash
  terraform -chdir=/Users/roman/Projects/clouder-projects/clouder-core/.claude/worktrees/service_improve/infra validate
  ```
  Expected: `Success! The configuration is valid.` (If validation complains the zip path does not exist, build it once: `bash /Users/roman/Projects/clouder-projects/clouder-core/.claude/worktrees/service_improve/scripts/package_lambda.sh` — `filebase64sha256(local.lambda_zip_file)` reads the artifact at plan time, but `terraform validate` does not, so this is only needed if a later `plan` is run.)

- [ ] **Re-run the full unit suite for both handlers, expect 11 passed** (guards against regressions from any import churn):
  ```bash
  PYTHONPATH=/Users/roman/Projects/clouder-projects/clouder-core/.claude/worktrees/service_improve/src \
  /Users/roman/Projects/clouder-projects/clouder-core/.venv/bin/python -m pytest \
  /Users/roman/Projects/clouder-projects/clouder-core/.claude/worktrees/service_improve/tests/unit/test_catalog_export_handler.py \
  /Users/roman/Projects/clouder-projects/clouder-core/.claude/worktrees/service_improve/tests/unit/test_ops_log_export_handler.py -q
  ```
  Expected: last line `11 passed` (exit code 0).

- [ ] **Commit** (caveman-commit subject, heredoc body, no AI trailer):
  ```bash
  git -C /Users/roman/Projects/clouder-projects/clouder-core/.claude/worktrees/service_improve add infra/analytics.tf infra/analytics_export.tf
  git -C /Users/roman/Projects/clouder-projects/clouder-core/.claude/worktrees/service_improve commit -m "$(cat <<'EOF'
  feat(infra): wire catalog/ops export lambdas + glue tables

  Analytics lake bucket + clouder_analytics Glue DB, two lightweight Glue
  tables, two own least-privilege roles (deliberate — not the shared
  collector role), and the two export lambdas off the shared zip.
  EOF
  )"
  ```
  Expected: `2 files changed`.

---

## Done when

- `tests/unit/test_catalog_export_handler.py` → `6 passed`; `tests/unit/test_ops_log_export_handler.py` → `5 passed`; both together `11 passed`.
- `catalog_export`'s wired default page size `_PAGE` is Data-API-safe (≤ 1000, asserted by `test_default_page_is_data_api_safe`) — the production page size is covered by the suite, not only the `page=2` path. The binding constraint is the RDS Data API ~1MB per-ExecuteStatement response cap (named in the `_PAGE` comment), not OFFSET cost.
- `terraform -chdir=…/infra validate` → `Success! The configuration is valid.` (requires a successful `init` with registry network access — no offline shortcut, `.terraform/` is absent here).
- `catalog_export_handler.py` imports neither `psycopg`/`psycopg2` nor `pyarrow`/`awswrangler`/`pandas` (AST guard test).
- `ops_log_export` reads the event name from `message`, its `_OPS_FIELDS` includes `message`+`timestamp`+`level` (with the corrected comment: `timestamp` is set by TimeStamper, `level` is injected by `log_event` and kept by `_sanitize_event` — neither is an `ALLOWED_LOG_FIELDS` metric field), and `OPS_LOG_GROUPS` includes collector-api + the auto-enrich-dispatch worker.
- Three commits, each via `caveman:caveman-commit`, on `feat/analytics-catalog-ops-export`.

**Deliberately out of scope this increment** (so the plan does not over-reach): the `/v1` CloudFront/Vite prefix, OpenAPI/`schema.d.ts` regen, the playback `play(idx?, overrideTrack?, source?)` change, and the funnel `track_ids` unnest — those belong to the SDK/telemetry-route (Inc 2) and dbt (Inc 4) increments. These exporters are EventBridge-triggered, not API routes, so the three-place route rule does not apply here; the EventBridge schedule + Step Functions wiring lands in Increment 4.
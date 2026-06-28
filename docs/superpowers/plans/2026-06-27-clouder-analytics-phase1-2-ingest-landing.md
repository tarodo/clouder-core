# Telemetry Ingest Landing (Phase 1 · Increment 2) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to execute this plan. Steps use checkbox (- [ ]) syntax.

**Goal:** Stand up the analytics ingest *landing* hop: a standalone `telemetry` Lambda behind the existing API Gateway + custom authorizer that validates a batch of behavior/playback envelopes, server-stamps `user_id`+`ts_server`, strips client identity/secret keys, and `PutRecordBatch`-es valid events as NDJSON to a Kinesis Firehose stream that converts JSON→Parquet and dynamic-partitions into an S3 medallion lake `bronze/events/dt=…/event_name=…/`. Registers the `/v1` API prefix end-to-end (OpenAPI + CloudFront + Vite) so the browser actually reaches the gateway. No SDK, no dbt, no catalog/ops export, no dashboards — those are other increments.

**Architecture:** Standalone Lambda (own least-privilege Firehose-only role), mirroring the `auth_handler`/`analytics-api` standalone pattern — **not** a branch in `collector.handler._route()`. Shares the one `scripts/package_lambda.sh` zip (different handler entry point `collector.telemetry_handler.lambda_handler`). Firehose Direct PUT → S3 (Parquet via Glue bronze table + partition projection). Aurora is never touched.

**Tech Stack:** Python 3.12 + Pydantic v2 (`extra="forbid"` envelope + per-event prop allowlist), boto3 Firehose (lazy client), structlog allowlist logging (`logging_utils`), Terraform (Lambda, IAM, API Gateway v2, Kinesis Firehose, Glue Catalog, S3 + lifecycle), pytest, `openapi-typescript`, Vite proxy + CloudFront ordered_cache_behavior.

**Spec:** docs/superpowers/specs/2026-06-27-clouder-analytics-pipeline-design.md (§5.1–§5.5, §13, §14, §17 step 2)

---

## File structure

| File | Create/Modify | Responsibility |
|---|---|---|
| `src/collector/telemetry_schemas.py` | Create | `TelemetryEnvelope` Pydantic model (`extra="forbid"`), `EVENT_NAMES` enum, `PROP_ALLOWLIST` per event, `validate_event()` — strips client `user_id`/secret keys, stamps server `user_id`+`ts_server`, key-allowlists props. Returns `props` as a **dict** (the handler serializes it for the Glue string column). |
| `src/collector/telemetry_handler.py` | Create | Standalone `lambda_handler`: parse `{events}`, reject >256 / >256KB, per-event validate-or-drop, **JSON-stringify each event's `props`** (matches the `string`-typed bronze column — the Firehose JSON SerDe will not coerce an object onto a string column), Firehose `PutRecordBatch` NDJSON, 202 `{accepted,rejected}`. |
| `tests/unit/test_telemetry_schemas.py` | Create | Unit tests for `validate_event` (enum, allowlist, secret-strip, server-stamp, per-event params). |
| `tests/unit/test_telemetry_handler.py` | Create | Handler tests (counts, NDJSON, **props-as-JSON-string**, oversize, drop-not-batch, injected Firehose mock, no-bp_token). |
| `scripts/generate_openapi.py` | Modify | Add `TELEMETRY_ENVELOPE` schema dict + register it in `components.schemas`; add `/v1/telemetry` POST to `ROUTES` (full contract, `_error(400,…)` not a nonexistent `responses/Error` ref). |
| `docs/api/openapi.yaml` | Modify (regenerated) | Generated artifact — must contain `/v1/telemetry` + `TelemetryEnvelope`. |
| `frontend/src/api/schema.d.ts` | Modify (regenerated) | `pnpm api:types` output — CI diff-gate against openapi.yaml. |
| `infra/main.tf` | Modify | Add `telemetry_lambda_name` local (~L34 locals block). |
| `infra/telemetry.tf` | Create | S3 lake bucket + lifecycle, Glue db + bronze `events` table (partition projection), Firehose stream (300s/64MB, JSON→Parquet, dynamic dt+event_name), Firehose role, telemetry Lambda + own role + log group + integration + route (`POST /v1/telemetry`, CUSTOM authorizer) + invoke permission. |
| `infra/outputs.tf` | Modify | Add `analytics_lake_bucket` + `telemetry_lambda_name` outputs (the Task 6 runbook reads them via `terraform output -raw`). |
| `infra/frontend.tf` | Modify | Add `"/v1*"` to `api_gw_pure_path_patterns` (~L124-140). |
| `frontend/vite.config.ts` | Modify | Add `'/v1'` to `BACKEND_ONLY_PREFIXES` (~L14-27). |

**Out of scope (named, not silently partial):**
- **SDK** (`frontend/src/lib/telemetry/`, the `play(idx?, overrideTrack?, source?)` source arg, `{suppressAuthFailure:true}` on `api()`) → **Increment 1**.
- **`catalog_export` + `ops_log_export` Lambdas AND their lightweight `bronze/catalog_export` + `bronze/ops` Glue tables** (the §5.5 "also get lightweight Glue tables" clause) → **Increment 3**. This increment ships only the `bronze/events` Glue table that Firehose format-conversion structurally requires; the other two JSON prefixes have no producer yet, so their Glue tables ship with their producer.
- **dbt silver/gold** incl. per-track `track_ids` UNNEST for `playlisted`/`published`, Saturday-week `dim_date`, and `ops_log_export` reading the structlog **`message`** key → **Increment 4**.
- **`analytics-api` + `/admin/analytics` dashboards** → **Increment 5**. The `/v1` prefix is registered here (telemetry lands first); `/v1/analytics/*` routes reuse the same prefix in Increment 5.

---

## Tasks

### Task 0: Branch

**Files:** none.

- [ ] Worktree's local `main` may lag origin (known gotcha). Fetch and branch from origin:
  ```bash
  git -C /Users/roman/Projects/clouder-projects/clouder-core/.claude/worktrees/service_improve fetch origin
  git -C /Users/roman/Projects/clouder-projects/clouder-core/.claude/worktrees/service_improve switch -c feat/telemetry-ingest-landing origin/main
  ```
- [ ] Run, expect: `Switched to a new branch 'feat/telemetry-ingest-landing'`.

---

### Task 1: Envelope validation (`telemetry_schemas.py`)

**Files:**
- Create `/Users/roman/Projects/clouder-projects/clouder-core/.claude/worktrees/service_improve/src/collector/telemetry_schemas.py`
- Test: `/Users/roman/Projects/clouder-projects/clouder-core/.claude/worktrees/service_improve/tests/unit/test_telemetry_schemas.py`

- [ ] Write the failing test file (FULL):
  ```python
  # tests/unit/test_telemetry_schemas.py
  import json

  import pytest
  from pydantic import ValidationError

  from collector.telemetry_schemas import (
      EVENT_NAMES,
      PROP_ALLOWLIST,
      validate_event,
  )

  TS_SERVER = "2026-06-27T10:00:00.000000+00:00"

  def _envelope(event_name="track_view", props=None, context=None):
      return {
          "event_name": event_name,
          "event_id": "01J0ULID",
          "session_id": "sess-1",
          "ts_client": "2026-06-27T10:00:00.123Z",
          "context": context if context is not None else {"device": "desktop", "route": "/curate/:id"},
          "props": props if props is not None else {"track_id": "t1", "dwell_ms": 1200},
      }

  def test_valid_event_stamps_user_and_ts():
      out = validate_event(_envelope(), user_id="u-1", ts_server=TS_SERVER)
      assert out["context"]["user_id"] == "u-1"
      assert out["ts_server"] == TS_SERVER
      assert out["event_name"] == "track_view"
      assert out["props"] == {"track_id": "t1", "dwell_ms": 1200}

  def test_props_returned_as_dict_not_stringified():
      # validate_event keeps props a dict; the HANDLER serializes it for Glue.
      out = validate_event(_envelope(), user_id="u-1", ts_server=TS_SERVER)
      assert isinstance(out["props"], dict)

  def test_unknown_event_name_raises():
      with pytest.raises(ValueError):
          validate_event(_envelope(event_name="not_a_real_event"), user_id="u-1", ts_server=TS_SERVER)

  def test_client_user_id_in_context_is_ignored_and_server_stamps():
      ev = _envelope(context={"user_id": "EVIL", "device": "mobile"})
      out = validate_event(ev, user_id="u-real", ts_server=TS_SERVER)
      assert out["context"]["user_id"] == "u-real"
      assert "EVIL" not in json.dumps(out)

  def test_secret_and_unknown_props_dropped():
      ev = _envelope(props={"track_id": "t1", "dwell_ms": 5, "access_token": "x", "junk": 1})
      out = validate_event(ev, user_id="u-1", ts_server=TS_SERVER)
      assert set(out["props"]) == {"track_id", "dwell_ms"}
      assert "access_token" not in json.dumps(out)

  def test_extra_top_level_key_rejected():
      ev = _envelope()
      ev["bp_token"] = "secret"
      with pytest.raises(ValidationError):
          validate_event(ev, user_id="u-1", ts_server=TS_SERVER)

  def test_missing_event_id_rejected():
      ev = _envelope()
      del ev["event_id"]
      with pytest.raises(ValidationError):
          validate_event(ev, user_id="u-1", ts_server=TS_SERVER)

  _VALID_PROPS = {
      "triage_session_start": {"block_id": "b", "bucket_id": "k"},
      "triage_session_end": {"session_ms": 1, "tracks_seen": 2, "tracks_categorized": 1, "undo_rate": 0.0},
      "track_view": {"track_id": "t", "dwell_ms": 1},
      "track_categorized": {"track_id": "t", "decision_ms": 1, "category_key": "NEW", "action": "moved_to_bucket", "surface": "triage"},
      "playback_play": {"track_id": "t", "position_ms": 0, "duration_ms": 200, "source": "triage_player"},
      "playback_pause": {"track_id": "t", "position_ms": 5, "duration_ms": 200, "seek_count": 0},
      "playback_seek": {"track_id": "t", "from_position_ms": 1, "to_position_ms": 9},
      "playback_ended": {"track_id": "t", "duration_ms": 200, "listen_through_ratio": 1.0},
      "playback_skip": {"track_id": "t", "position_ms": 9, "duration_ms": 200},
      "hotkey_used": {"hotkey_code": "Space", "action": "toggle_play", "source": "playback"},
      "playlist_add": {"track_ids": ["a", "b"], "playlist_id": "p", "track_count": 2, "source_category_id": None},
      "playlist_reorder": {"playlist_id": "p", "track_count": 3, "reorder_count": 1},
      "playlist_publish": {"track_ids": ["a"], "playlist_id": "p", "track_count": 1, "confirm_overwrite": False, "skipped_count": 0, "target": "spotify"},
  }

  @pytest.mark.parametrize("event_name", sorted(EVENT_NAMES))
  def test_each_event_accepts_its_allowlisted_props(event_name):
      ev = _envelope(event_name=event_name, props=dict(_VALID_PROPS[event_name]))
      out = validate_event(ev, user_id="u-1", ts_server=TS_SERVER)
      assert set(out["props"]) <= PROP_ALLOWLIST[event_name]
      assert set(out["props"]) == set(_VALID_PROPS[event_name])
  ```
- [ ] Run, expect FAIL (module missing):
  ```bash
  PYTHONPATH=/Users/roman/Projects/clouder-projects/clouder-core/.claude/worktrees/service_improve/src \
    /Users/roman/Projects/clouder-projects/clouder-core/.venv/bin/pytest \
    /Users/roman/Projects/clouder-projects/clouder-core/.claude/worktrees/service_improve/tests/unit/test_telemetry_schemas.py -q
  ```
  Expected: collection error `ModuleNotFoundError: No module named 'collector.telemetry_schemas'`.
- [ ] Write the implementation (FULL):
  ```python
  # src/collector/telemetry_schemas.py
  """Server-side validation for the telemetry envelope (spec §3.1/§3.2).

  Schema-on-read: props are key-allowlisted per event_name, not deeply typed —
  new props ship without a migration. The envelope is strict (extra forbidden),
  so any secret-shaped or unexpected top-level key is rejected outright.
  `context.user_id` is never trusted: it is dropped on parse and re-stamped by
  the handler from the authorizer. props is returned as a dict; the handler
  serializes it to a JSON string to match the bronze Glue column type.
  """

  from __future__ import annotations

  from typing import Any, Mapping

  from pydantic import BaseModel, ConfigDict, Field

  # Mirrors the Glue partition-projection enum in infra/telemetry.tf.
  # ponytail: adding an event = one line here + one line in that enum. ~13 names.
  EVENT_NAMES: frozenset[str] = frozenset(
      {
          "triage_session_start",
          "triage_session_end",
          "track_view",
          "track_categorized",
          "playback_play",
          "playback_pause",
          "playback_seek",
          "playback_ended",
          "playback_skip",
          "hotkey_used",
          "playlist_add",
          "playlist_reorder",
          "playlist_publish",
      }
  )

  # Per-event allowed prop keys (spec §3.2). Unknown keys are dropped (forward-
  # compat), secret-shaped keys are stripped everywhere via _SECRET_KEYS.
  PROP_ALLOWLIST: dict[str, frozenset[str]] = {
      "triage_session_start": frozenset({"block_id", "bucket_id"}),
      "triage_session_end": frozenset(
          {"session_ms", "tracks_seen", "tracks_categorized", "undo_rate"}
      ),
      "track_view": frozenset({"track_id", "dwell_ms"}),
      "track_categorized": frozenset(
          {"track_id", "decision_ms", "category_key", "action", "surface"}
      ),
      "playback_play": frozenset({"track_id", "position_ms", "duration_ms", "source"}),
      "playback_pause": frozenset(
          {"track_id", "position_ms", "duration_ms", "seek_count"}
      ),
      "playback_seek": frozenset({"track_id", "from_position_ms", "to_position_ms"}),
      "playback_ended": frozenset({"track_id", "duration_ms", "listen_through_ratio"}),
      "playback_skip": frozenset({"track_id", "position_ms", "duration_ms"}),
      "hotkey_used": frozenset({"hotkey_code", "action", "source"}),
      "playlist_add": frozenset(
          {"track_ids", "playlist_id", "track_count", "source_category_id"}
      ),
      "playlist_reorder": frozenset({"playlist_id", "track_count", "reorder_count"}),
      "playlist_publish": frozenset(
          {
              "track_ids",
              "playlist_id",
              "track_count",
              "confirm_overwrite",
              "skipped_count",
              "target",
          }
      ),
  }

  _SECRET_KEYS = {"bp_token", "authorization", "token", "access_token", "secret"}


  class EnvelopeContext(BaseModel):
      # extra="ignore": a client-sent context.user_id is silently dropped; the
      # server re-stamps it. Only coarse, non-PII context fields are kept.
      model_config = ConfigDict(extra="ignore")
      device: str | None = None
      route: str | None = None
      app_version: str | None = None


  class TelemetryEnvelope(BaseModel):
      model_config = ConfigDict(extra="forbid")
      event_name: str = Field(min_length=1)
      event_id: str = Field(min_length=1)
      session_id: str = Field(min_length=1)
      ts_client: str = Field(min_length=1)
      context: EnvelopeContext = Field(default_factory=EnvelopeContext)
      props: dict[str, Any] = Field(default_factory=dict)


  def _strip_secrets(d: Mapping[str, Any]) -> dict[str, Any]:
      return {k: v for k, v in d.items() if k.lower() not in _SECRET_KEYS}


  def validate_event(
      raw: Any, *, user_id: str | None, ts_server: str
  ) -> dict[str, Any]:
      """Validate one raw event; return the cleaned, server-stamped envelope.

      ``props`` is returned as a dict — the handler serializes it to a JSON
      string before emitting (it lands on a ``string``-typed Glue column).
      Raises pydantic.ValidationError / ValueError on a bad event so the handler
      can drop it individually and increment ``rejected``.
      """
      env = TelemetryEnvelope.model_validate(raw)
      if env.event_name not in EVENT_NAMES:
          raise ValueError(f"unknown event_name: {env.event_name}")
      allowed = PROP_ALLOWLIST[env.event_name]
      clean_props = {
          k: v for k, v in _strip_secrets(env.props).items() if k in allowed
      }
      return {
          "event_name": env.event_name,
          "event_id": env.event_id,
          "session_id": env.session_id,
          "ts_client": env.ts_client,
          "ts_server": ts_server,
          "context": {
              "user_id": user_id,  # SERVER-STAMPED; client value ignored
              "device": env.context.device,
              "route": env.context.route,
              "app_version": env.context.app_version,
          },
          "props": clean_props,
      }
  ```
- [ ] Run, expect PASS:
  ```bash
  PYTHONPATH=/Users/roman/Projects/clouder-projects/clouder-core/.claude/worktrees/service_improve/src \
    /Users/roman/Projects/clouder-projects/clouder-core/.venv/bin/pytest \
    /Users/roman/Projects/clouder-projects/clouder-core/.claude/worktrees/service_improve/tests/unit/test_telemetry_schemas.py -q
  ```
  Expected last line: `20 passed`.
- [ ] Commit: stage the two files, generate the subject via the **caveman:caveman-commit** skill, then:
  ```bash
  git -C /Users/roman/Projects/clouder-projects/clouder-core/.claude/worktrees/service_improve add src/collector/telemetry_schemas.py tests/unit/test_telemetry_schemas.py
  git -C /Users/roman/Projects/clouder-projects/clouder-core/.claude/worktrees/service_improve commit -m "<caveman-commit subject>"
  ```
  (Conventional Commits; no `Co-Authored-By` trailer.)

---

### Task 2: Telemetry handler (`telemetry_handler.py`)

**Files:**
- Create `/Users/roman/Projects/clouder-projects/clouder-core/.claude/worktrees/service_improve/src/collector/telemetry_handler.py`
- Test: `/Users/roman/Projects/clouder-projects/clouder-core/.claude/worktrees/service_improve/tests/unit/test_telemetry_handler.py`

- [ ] Write the failing test file (FULL). Firehose is injected via the `firehose_client=` kwarg (DI — no boto3 patching):
  ```python
  # tests/unit/test_telemetry_handler.py
  import json
  from types import SimpleNamespace
  from unittest.mock import MagicMock

  import pytest

  from collector import telemetry_handler


  @pytest.fixture(autouse=True)
  def _env(monkeypatch):
      monkeypatch.setenv("TELEMETRY_FIREHOSE_STREAM_NAME", "beatport-prod-telemetry")
      yield


  def _ctx():
      return SimpleNamespace(aws_request_id="lambda-req-1")


  def _event(events, *, user_id="u-1", body=None):
      payload = body if body is not None else json.dumps({"events": events})
      return {
          "version": "2.0",
          "requestContext": {
              "requestId": "api-req-1",
              "routeKey": "POST /v1/telemetry",
              "authorizer": {"lambda": {"user_id": user_id, "is_admin": False}},
          },
          "headers": {"x-correlation-id": "cid-1"},
          "body": payload,
      }


  def _track_view(track="t1"):
      return {
          "event_name": "track_view",
          "event_id": f"ev-{track}",
          "session_id": "s1",
          "ts_client": "2026-06-27T10:00:00.000Z",
          "context": {"device": "desktop", "route": "/curate/:id"},
          "props": {"track_id": track, "dwell_ms": 900},
      }


  def _ok_firehose():
      fh = MagicMock()
      fh.put_record_batch.return_value = {"FailedPutCount": 0, "RequestResponses": []}
      return fh


  def test_happy_path_202_with_counts():
      fh = _ok_firehose()
      resp = telemetry_handler.lambda_handler(
          _event([_track_view("a"), _track_view("b")]), _ctx(), firehose_client=fh
      )
      assert resp["statusCode"] == 202
      assert json.loads(resp["body"]) == {"accepted": 2, "rejected": 0}
      assert fh.put_record_batch.call_count == 1


  def test_firehose_records_are_ndjson_one_line_each():
      fh = _ok_firehose()
      telemetry_handler.lambda_handler(
          _event([_track_view("a"), _track_view("b")]), _ctx(), firehose_client=fh
      )
      records = fh.put_record_batch.call_args.kwargs["Records"]
      assert len(records) == 2
      for rec in records:
          data = rec["Data"].decode("utf-8")
          assert data.endswith("\n")
          assert data.count("\n") == 1
          json.loads(data)  # each line is standalone valid JSON


  def test_props_serialized_as_json_string_for_glue_column():
      # The bronze Glue `props` column is type `string`; Firehose's JSON SerDe
      # will not coerce an object onto a string column (record would be routed to
      # bronze/_errors/). The handler must emit props as a JSON STRING, not a dict.
      fh = _ok_firehose()
      telemetry_handler.lambda_handler(_event([_track_view("a")]), _ctx(), firehose_client=fh)
      line = fh.put_record_batch.call_args.kwargs["Records"][0]["Data"].decode("utf-8")
      record = json.loads(line)
      assert isinstance(record["props"], str)
      assert json.loads(record["props"]) == {"track_id": "a", "dwell_ms": 900}
      # ts_server / event_name remain top-level scalars for partition extraction.
      assert isinstance(record["event_name"], str)
      assert isinstance(record["ts_server"], str)


  def test_invalid_event_dropped_not_whole_batch():
      fh = _ok_firehose()
      bad = _track_view("bad")
      bad["event_name"] = "nope"
      resp = telemetry_handler.lambda_handler(
          _event([_track_view("a"), bad]), _ctx(), firehose_client=fh
      )
      assert json.loads(resp["body"]) == {"accepted": 1, "rejected": 1}
      assert len(fh.put_record_batch.call_args.kwargs["Records"]) == 1


  def test_all_invalid_skips_firehose():
      fh = _ok_firehose()
      bad = _track_view("bad")
      bad["event_name"] = "nope"
      resp = telemetry_handler.lambda_handler(_event([bad]), _ctx(), firehose_client=fh)
      assert json.loads(resp["body"]) == {"accepted": 0, "rejected": 1}
      assert fh.put_record_batch.call_count == 0


  def test_user_id_stamped_from_authorizer_not_client():
      fh = _ok_firehose()
      ev = _track_view("a")
      ev["context"]["user_id"] = "CLIENT_SPOOF"
      telemetry_handler.lambda_handler(
          _event([ev], user_id="u-real"), _ctx(), firehose_client=fh
      )
      line = fh.put_record_batch.call_args.kwargs["Records"][0]["Data"].decode("utf-8")
      record = json.loads(line)
      assert record["context"]["user_id"] == "u-real"
      assert "CLIENT_SPOOF" not in line


  def test_unparseable_body_returns_400():
      fh = _ok_firehose()
      resp = telemetry_handler.lambda_handler(
          _event([], body="{not json"), _ctx(), firehose_client=fh
      )
      assert resp["statusCode"] == 400
      assert fh.put_record_batch.call_count == 0


  def test_missing_events_key_returns_400():
      fh = _ok_firehose()
      resp = telemetry_handler.lambda_handler(
          _event([], body=json.dumps({"nope": []})), _ctx(), firehose_client=fh
      )
      assert resp["statusCode"] == 400


  def test_batch_over_256_events_returns_400():
      fh = _ok_firehose()
      events = [_track_view(str(i)) for i in range(257)]
      resp = telemetry_handler.lambda_handler(_event(events), _ctx(), firehose_client=fh)
      assert resp["statusCode"] == 400
      assert fh.put_record_batch.call_count == 0


  def test_body_over_256kb_returns_413():
      fh = _ok_firehose()
      big = "x" * (256 * 1024 + 1)
      resp = telemetry_handler.lambda_handler(
          _event([], body=big), _ctx(), firehose_client=fh
      )
      assert resp["statusCode"] == 413
      assert fh.put_record_batch.call_count == 0


  def test_bp_token_never_reaches_firehose():
      fh = _ok_firehose()
      ev = _track_view("a")
      ev["props"]["bp_token"] = "SECRET"
      telemetry_handler.lambda_handler(_event([ev]), _ctx(), firehose_client=fh)
      line = fh.put_record_batch.call_args.kwargs["Records"][0]["Data"].decode("utf-8")
      assert "SECRET" not in line
      assert "bp_token" not in line
  ```
- [ ] Run, expect FAIL (module missing):
  ```bash
  PYTHONPATH=/Users/roman/Projects/clouder-projects/clouder-core/.claude/worktrees/service_improve/src \
    /Users/roman/Projects/clouder-projects/clouder-core/.venv/bin/pytest \
    /Users/roman/Projects/clouder-projects/clouder-core/.claude/worktrees/service_improve/tests/unit/test_telemetry_handler.py -q
  ```
  Expected: `ModuleNotFoundError: No module named 'collector.telemetry_handler'`.
- [ ] Write the implementation (FULL):
  ```python
  # src/collector/telemetry_handler.py
  """Standalone telemetry ingest Lambda (spec §5.1/§5.2).

  Validates a batch of behavior/playback envelopes, server-stamps identity, and
  forwards valid events to Kinesis Firehose as NDJSON. Strictly isolated: its own
  least-privilege role (firehose:PutRecordBatch only), its own integration/route.
  Never touches the collector, the worker queue, or Aurora; never reads bp_token.
  Shares the collector zip — entry point is collector.telemetry_handler.lambda_handler.
  """

  from __future__ import annotations

  import json
  import os
  import time
  from datetime import datetime, timezone
  from typing import Any, Mapping

  from pydantic import ValidationError

  from .logging_utils import log_event
  from .telemetry_schemas import validate_event

  _MAX_EVENTS = 256
  _MAX_BODY_BYTES = 256 * 1024


  def create_default_firehose_client():  # pragma: no cover - thin boto3 factory
      import boto3

      return boto3.client("firehose")


  def _authorizer_context(event: Mapping[str, Any]) -> dict[str, Any]:
      rc = event.get("requestContext")
      if isinstance(rc, Mapping):
          authorizer = rc.get("authorizer")
          if isinstance(authorizer, Mapping):
              ctx = authorizer.get("lambda")
              if isinstance(ctx, Mapping):
                  return dict(ctx)
      return {}


  def _correlation_id(event: Mapping[str, Any]) -> str:
      headers = event.get("headers")
      if isinstance(headers, Mapping):
          for k, v in headers.items():
              if isinstance(k, str) and k.lower() == "x-correlation-id" and isinstance(v, str) and v:
                  return v
      rc = event.get("requestContext")
      if isinstance(rc, Mapping):
          rid = rc.get("requestId")
          if isinstance(rid, str):
              return rid
      return "telemetry"


  def _response(status: int, body: dict[str, Any], correlation_id: str) -> dict[str, Any]:
      return {
          "statusCode": status,
          "headers": {
              "content-type": "application/json",
              "x-correlation-id": correlation_id,
          },
          "body": json.dumps(body),
      }


  def lambda_handler(event: Mapping[str, Any], context: Any, *, firehose_client: Any = None) -> dict[str, Any]:
      started = time.monotonic()
      correlation_id = _correlation_id(event)
      user_id = _authorizer_context(event).get("user_id")

      raw = event.get("body") or ""
      if len(raw.encode("utf-8")) > _MAX_BODY_BYTES:
          log_event(
              "WARNING", "telemetry_body_too_large",
              correlation_id=correlation_id, user_id=user_id, status_code=413,
          )
          return _response(413, {"error_code": "payload_too_large", "message": "body exceeds 256KB"}, correlation_id)

      try:
          parsed = json.loads(raw)
          events = parsed["events"]
          if not isinstance(events, list):
              raise ValueError("events must be a list")
      except (json.JSONDecodeError, KeyError, TypeError, ValueError):
          log_event(
              "WARNING", "telemetry_unparseable_body",
              correlation_id=correlation_id, user_id=user_id, status_code=400,
          )
          return _response(400, {"error_code": "invalid_body", "message": "expected {events: [...]}"}, correlation_id)

      if len(events) > _MAX_EVENTS:
          log_event(
              "WARNING", "telemetry_batch_too_large",
              correlation_id=correlation_id, user_id=user_id, status_code=400, count=len(events),
          )
          return _response(400, {"error_code": "batch_too_large", "message": "max 256 events"}, correlation_id)

      ts_server = datetime.now(timezone.utc).isoformat()
      records: list[dict[str, bytes]] = []
      rejected = 0
      for raw_event in events:
          try:
              clean = validate_event(raw_event, user_id=user_id, ts_server=ts_server)
          except (ValidationError, ValueError, TypeError):
              rejected += 1
              continue
          # props lands on a `string`-typed bronze Glue column (schema-on-read).
          # The Firehose JSON SerDe will not coerce an object onto a string
          # column — emit props as a JSON string; dbt casts it back in silver.
          clean["props"] = json.dumps(clean["props"], separators=(",", ":"))
          line = (json.dumps(clean, separators=(",", ":")) + "\n").encode("utf-8")
          records.append({"Data": line})

      accepted = len(records)
      if records:
          client = firehose_client or create_default_firehose_client()
          stream = os.environ["TELEMETRY_FIREHOSE_STREAM_NAME"]
          # ponytail: single PutRecordBatch — the 256-event cap is well under
          # Firehose's 500-record limit, so no chunking is needed here.
          result = client.put_record_batch(DeliveryStreamName=stream, Records=records)
          failed = result.get("FailedPutCount", 0)
          if failed:
              # Loss-tolerant: log counts (allowlisted fields only), never retry inline.
              log_event(
                  "WARNING", "telemetry_firehose_partial_failure",
                  correlation_id=correlation_id, user_id=user_id, count=accepted, failed_after=failed,
              )

      log_event(
          "INFO", "telemetry_ingest",
          correlation_id=correlation_id, user_id=user_id, status_code=202,
          duration_ms=int((time.monotonic() - started) * 1000), count=accepted,
      )
      return _response(202, {"accepted": accepted, "rejected": rejected}, correlation_id)
  ```
- [ ] Run, expect PASS:
  ```bash
  PYTHONPATH=/Users/roman/Projects/clouder-projects/clouder-core/.claude/worktrees/service_improve/src \
    /Users/roman/Projects/clouder-projects/clouder-core/.venv/bin/pytest \
    /Users/roman/Projects/clouder-projects/clouder-core/.claude/worktrees/service_improve/tests/unit/test_telemetry_handler.py -q
  ```
  Expected last line: `11 passed`.
- [ ] Full unit suite still green (no regression):
  ```bash
  PYTHONPATH=/Users/roman/Projects/clouder-projects/clouder-core/.claude/worktrees/service_improve/src \
    /Users/roman/Projects/clouder-projects/clouder-core/.venv/bin/pytest \
    /Users/roman/Projects/clouder-projects/clouder-core/.claude/worktrees/service_improve/tests/unit -q
  ```
  Expected: exit 0, final line `... passed` (the pre-existing count + 31 new = 20 schemas + 11 handler).
- [ ] Commit: stage `src/collector/telemetry_handler.py` + `tests/unit/test_telemetry_handler.py`, generate subject via **caveman:caveman-commit**, then `git ... commit -m "<subject>"`.

---

### Task 3: OpenAPI `/v1/telemetry` route + `TelemetryEnvelope` component

**Files:**
- Modify `/Users/roman/Projects/clouder-projects/clouder-core/.claude/worktrees/service_improve/scripts/generate_openapi.py` (add schema dict near other inline schemas ~L1245; add ROUTES entry before the closing `]` at ~L3727; register schema in `build_openapi()` components ~L3861-3892)
- Regenerated: `docs/api/openapi.yaml`, `frontend/src/api/schema.d.ts`
- Test (assertion): inline `python -c` + `git diff --stat`

- [ ] Add the `TELEMETRY_ENVELOPE` schema dict (place it just above `# ── routes ──` at ~L1247). FULL, no ellipsis — the frontend CI diff-checks against it:
  ```python
  # ── telemetry (analytics ingest, spec §3.1) ───────────────────────────────
  TELEMETRY_ENVELOPE = {
      "type": "object",
      "required": ["event_name", "event_id", "session_id", "ts_client"],
      "description": (
          "One behavior/playback event. `context.user_id` is server-stamped from "
          "the authorizer and any client value is ignored; `props` keys are "
          "allowlisted per event_name server-side (schema-on-read)."
      ),
      "properties": {
          "event_name": {
              "type": "string",
              "enum": [
                  "triage_session_start", "triage_session_end", "track_view",
                  "track_categorized", "playback_play", "playback_pause",
                  "playback_seek", "playback_ended", "playback_skip",
                  "hotkey_used", "playlist_add", "playlist_reorder",
                  "playlist_publish",
              ],
          },
          "event_id": {"type": "string", "description": "Client ULID; idempotency key."},
          "session_id": {"type": "string", "description": "Fresh per tab; not persisted."},
          "ts_client": {"type": "string", "format": "date-time"},
          "context": {
              "type": "object",
              "properties": {
                  "device": {"type": ["string", "null"], "enum": ["desktop", "mobile", "tablet", None]},
                  "route": {"type": ["string", "null"], "description": "Matched route pattern (no PII)."},
                  "app_version": {"type": ["string", "null"]},
              },
              "additionalProperties": False,
          },
          "props": {"type": "object", "description": "Per-event payload; allowlisted server-side."},
      },
      "additionalProperties": False,
  }
  ```
- [ ] Add the ROUTES entry immediately before the closing `]` of `ROUTES` (~L3727). **Use `_error(400, …)`** — this repo has no `components/responses/Error` (the spec's draft snippet's `$ref` would be a broken ref):
  ```python
      # ── telemetry (analytics ingest) ───────────────────────────────────
      {
          "method": "post",
          "path": "/v1/telemetry",
          "auth": AUTH,
          "summary": "Ingest telemetry events.",
          "description": (
              "Accepts a batch of behavior/playback events. The server stamps "
              "user_id (from the authorizer) + ts_server and forwards valid events "
              "to the analytics pipeline. Invalid events are dropped individually; "
              "the batch still returns 202 with accepted/rejected counts. A 256KB "
              "body cap is enforced in the Lambda (operational guard, like the "
              "503 cold-start note) and is not part of this contract."
          ),
          "requestBody": {
              "required": True,
              "content": {"application/json": {"schema": {
                  "type": "object",
                  "required": ["events"],
                  "properties": {"events": {
                      "type": "array",
                      "maxItems": 256,
                      "items": {"$ref": "#/components/schemas/TelemetryEnvelope"},
                  }},
                  "additionalProperties": False,
              }}},
          },
          "responses": {
              "202": _make_response(
                  202,
                  "Accepted. Counts of stored vs dropped events.",
                  {
                      "type": "object",
                      "required": ["accepted", "rejected"],
                      "properties": {
                          "accepted": {"type": "integer"},
                          "rejected": {"type": "integer"},
                      },
                  },
              ),
              "400": _error(400, "Unparseable body or batch over 256 events."),
              **COMMON_AUTH_ERRORS,
          },
      },
  ```
- [ ] Register the component in `build_openapi()` `components.schemas` dict (add one line alongside `"PlaylistCommentsResponse": PLAYLIST_COMMENTS_RESPONSE,` at ~L3891):
  ```python
                  "TelemetryEnvelope": TELEMETRY_ENVELOPE,
  ```
- [ ] Regenerate the OpenAPI doc:
  ```bash
  PYTHONPATH=/Users/roman/Projects/clouder-projects/clouder-core/.claude/worktrees/service_improve/src \
    /Users/roman/Projects/clouder-projects/clouder-core/.venv/bin/python \
    /Users/roman/Projects/clouder-projects/clouder-core/.claude/worktrees/service_improve/scripts/generate_openapi.py
  ```
  Expected: `wrote .../docs/api/openapi.yaml  (<bytes>)`.
- [ ] Assert the route + component landed and no broken `$ref` (every `$ref` target resolves):
  ```bash
  PYTHONPATH=/Users/roman/Projects/clouder-projects/clouder-core/.claude/worktrees/service_improve/src \
    /Users/roman/Projects/clouder-projects/clouder-core/.venv/bin/python - <<'EOF'
  import re, yaml, pathlib
  d = yaml.safe_load(pathlib.Path("/Users/roman/Projects/clouder-projects/clouder-core/.claude/worktrees/service_improve/docs/api/openapi.yaml").read_text())
  assert "/v1/telemetry" in d["paths"], "route missing"
  assert "TelemetryEnvelope" in d["components"]["schemas"], "component missing"
  text = pathlib.Path("/Users/roman/Projects/clouder-projects/clouder-core/.claude/worktrees/service_improve/docs/api/openapi.yaml").read_text()
  refs = {m.split("/")[-1] for m in re.findall(r"#/components/schemas/(\w+)", text)}
  missing = refs - set(d["components"]["schemas"])
  assert not missing, f"broken schema refs: {missing}"
  assert "#/components/responses/" not in text, "nonexistent responses ref leaked"
  print("OPENAPI OK")
  EOF
  ```
  Expected: `OPENAPI OK`.
- [ ] Regenerate the frontend types and run the CI gates (these run from `frontend/`; the harness resets cwd, so use a single compound command):
  ```bash
  cd /Users/roman/Projects/clouder-projects/clouder-core/.claude/worktrees/service_improve/frontend && pnpm api:types && pnpm typecheck && pnpm lint
  ```
  Expected: `schema.d.ts` rewritten, `tsc -b --noEmit` exits 0, `eslint src` exits 0 (no errors). If `pnpm` is missing/offline, note it and run the three commands when network is available — the CI gate requires `schema.d.ts` to match `openapi.yaml`.
- [ ] Commit: stage `scripts/generate_openapi.py docs/api/openapi.yaml frontend/src/api/schema.d.ts`, generate subject via **caveman:caveman-commit**, then `git ... commit -m "<subject>"`.

---

### Task 4: Register the `/v1` prefix in CloudFront + Vite (MUST-FIX 1)

**Files:**
- Modify `/Users/roman/Projects/clouder-projects/clouder-core/.claude/worktrees/service_improve/infra/frontend.tf` (`api_gw_pure_path_patterns` ~L124-140)
- Modify `/Users/roman/Projects/clouder-projects/clouder-core/.claude/worktrees/service_improve/frontend/vite.config.ts` (`BACKEND_ONLY_PREFIXES` ~L14-27)

- [ ] In `infra/frontend.tf`, add `"/v1*"` as the last entry of `api_gw_pure_path_patterns` (after `"/tags*",`). `/v1` is a pure API prefix (no SPA-route collision), so the existing `dynamic "ordered_cache_behavior"` loop over that local auto-creates the CachingDisabled / AllViewerExceptHostHeader behavior to the `api-gw` origin. One registration covers `/v1/telemetry` now and `/v1/analytics/*` in Increment 5.
  ```hcl
      "/tags*",
      "/v1*",
    ]
  ```
- [ ] In `frontend/vite.config.ts`, add `'/v1'` to the end of `BACKEND_ONLY_PREFIXES` (it is pure API — no `spaAwareOpts` bypass needed):
  ```ts
    '/collect_bp_releases',
    '/v1',
  ];
  ```
- [ ] Verify both edits (grep, not a test — these are config arrays):
  ```bash
  grep -n '"/v1\*"' /Users/roman/Projects/clouder-projects/clouder-core/.claude/worktrees/service_improve/infra/frontend.tf
  grep -n "'/v1'" /Users/roman/Projects/clouder-projects/clouder-core/.claude/worktrees/service_improve/frontend/vite.config.ts
  ```
  Expected: one match in each file.
- [ ] Confirm Vite config still typechecks (it is part of `tsconfig`-adjacent tooling but is plain TS — `terraform fmt` covers the HCL in Task 5). Run the frontend typecheck again to be safe:
  ```bash
  cd /Users/roman/Projects/clouder-projects/clouder-core/.claude/worktrees/service_improve/frontend && pnpm typecheck
  ```
  Expected: exits 0.
- [ ] Commit: stage `infra/frontend.tf frontend/vite.config.ts`, generate subject via **caveman:caveman-commit**, then `git ... commit -m "<subject>"`.

---

### Task 5: `infra/telemetry.tf` — Lambda + role + Firehose + S3 lake + Glue + outputs

**Files:**
- Modify `/Users/roman/Projects/clouder-projects/clouder-core/.claude/worktrees/service_improve/infra/main.tf` (add `telemetry_lambda_name` local in the locals block ~L34)
- Create `/Users/roman/Projects/clouder-projects/clouder-core/.claude/worktrees/service_improve/infra/telemetry.tf`
- Modify `/Users/roman/Projects/clouder-projects/clouder-core/.claude/worktrees/service_improve/infra/outputs.tf` (append two outputs read by the Task 6 runbook)

- [ ] In `infra/main.tf` add the lambda-name local next to `curation_lambda_name`:
  ```hcl
    telemetry_lambda_name                   = "${local.name_prefix}-telemetry"
  ```
- [ ] Create `infra/telemetry.tf` (FULL). Reuses existing refs: `local.name_prefix`, `local.lambda_zip_file`, `var.aws_region`, `var.log_retention_days`, `data.aws_caller_identity.current`, `aws_apigatewayv2_api.collector`, `aws_apigatewayv2_authorizer.jwt`:
  ```hcl
  # ── Analytics lake bucket (medallion: bronze / silver / gold) ───────
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

  resource "aws_s3_bucket_server_side_encryption_configuration" "analytics_lake" {
    bucket = aws_s3_bucket.analytics_lake.id
    rule {
      apply_server_side_encryption_by_default {
        sse_algorithm = "AES256"
      }
    }
  }

  resource "aws_s3_bucket_lifecycle_configuration" "analytics_lake" {
    bucket = aws_s3_bucket.analytics_lake.id

    rule {
      id     = "expire-athena-results"
      status = "Enabled"
      filter { prefix = "athena-results/" }
      expiration { days = 7 }
    }

    rule {
      id     = "bronze-to-ia"
      status = "Enabled"
      filter { prefix = "bronze/" }
      transition {
        days          = 90
        storage_class = "STANDARD_IA"
      }
    }
  }

  # ── Glue Data Catalog: db + bronze events table (partition projection) ─
  resource "aws_glue_catalog_database" "analytics" {
    name = "clouder_analytics"
  }

  # bronze/events: Firehose format-conversion target. Columns are the JSON->Parquet
  # source schema. `dt` + `event_name` are partition keys (NOT data columns), filled
  # by Firehose dynamic partitioning. Out of scope here: lightweight Glue tables for
  # bronze/catalog_export and bronze/ops — they ship with their producers in
  # Increment 3 (no producer exists yet, so no table yet).
  resource "aws_glue_catalog_table" "bronze_events" {
    name          = "events"
    database_name = aws_glue_catalog_database.analytics.name
    table_type    = "EXTERNAL_TABLE"

    parameters = {
      classification                 = "parquet"
      "projection.enabled"           = "true"
      "projection.dt.type"           = "date"
      "projection.dt.format"         = "yyyy-MM-dd"
      "projection.dt.range"          = "2026-01-01,NOW"
      "projection.dt.interval"       = "1"
      "projection.dt.interval.unit"  = "DAYS"
      "projection.event_name.type"   = "enum"
      "projection.event_name.values" = "triage_session_start,triage_session_end,track_view,track_categorized,playback_play,playback_pause,playback_seek,playback_ended,playback_skip,hotkey_used,playlist_add,playlist_reorder,playlist_publish"
      "storage.location.template"    = "s3://${aws_s3_bucket.analytics_lake.bucket}/bronze/events/dt=$${dt}/event_name=$${event_name}"
    }

    partition_keys {
      name = "dt"
      type = "string"
    }
    partition_keys {
      name = "event_name"
      type = "string"
    }

    storage_descriptor {
      location      = "s3://${aws_s3_bucket.analytics_lake.bucket}/bronze/events/"
      input_format  = "org.apache.hadoop.hive.ql.io.parquet.MapredParquetInputFormat"
      output_format = "org.apache.hadoop.hive.ql.io.parquet.MapredParquetOutputFormat"

      ser_de_info {
        serialization_library = "org.apache.hadoop.hive.ql.io.parquet.serde.ParquetHiveSerDe"
      }

      columns {
        name = "event_id"
        type = "string"
      }
      columns {
        name = "session_id"
        type = "string"
      }
      columns {
        name = "ts_client"
        type = "string"
      }
      columns {
        name = "ts_server"
        type = "string"
      }
      columns {
        name = "context"
        type = "struct<user_id:string,device:string,route:string,app_version:string>"
      }
      # Schema-on-read: the handler emits props as a JSON STRING (an object value
      # would not coerce onto this string column and would be routed to
      # bronze/_errors/). dbt casts it back to a struct in silver.
      columns {
        name = "props"
        type = "string"
      }
    }
  }

  # ── Firehose delivery role (S3 write + Glue read for format conversion) ─
  data "aws_iam_policy_document" "firehose_telemetry_assume" {
    statement {
      effect  = "Allow"
      actions = ["sts:AssumeRole"]
      principals {
        type        = "Service"
        identifiers = ["firehose.amazonaws.com"]
      }
    }
  }

  resource "aws_iam_role" "firehose_telemetry" {
    name               = "${local.name_prefix}-telemetry-firehose-role"
    assume_role_policy = data.aws_iam_policy_document.firehose_telemetry_assume.json
  }

  data "aws_iam_policy_document" "firehose_telemetry" {
    statement {
      sid    = "WriteLake"
      effect = "Allow"
      actions = [
        "s3:AbortMultipartUpload",
        "s3:GetBucketLocation",
        "s3:GetObject",
        "s3:ListBucket",
        "s3:ListBucketMultipartUploads",
        "s3:PutObject",
      ]
      resources = [
        aws_s3_bucket.analytics_lake.arn,
        "${aws_s3_bucket.analytics_lake.arn}/*",
      ]
    }
    statement {
      sid       = "GlueReadForConversion"
      effect    = "Allow"
      actions   = ["glue:GetTable", "glue:GetTableVersion", "glue:GetTableVersions"]
      resources = ["*"]
    }
    statement {
      sid       = "FirehoseLogs"
      effect    = "Allow"
      actions   = ["logs:PutLogEvents"]
      resources = ["${aws_cloudwatch_log_group.firehose_telemetry.arn}:*"]
    }
  }

  resource "aws_iam_role_policy" "firehose_telemetry" {
    name   = "${local.name_prefix}-telemetry-firehose-policy"
    role   = aws_iam_role.firehose_telemetry.id
    policy = data.aws_iam_policy_document.firehose_telemetry.json
  }

  resource "aws_cloudwatch_log_group" "firehose_telemetry" {
    name              = "/aws/kinesisfirehose/${local.name_prefix}-telemetry"
    retention_in_days = var.log_retention_days
  }

  # ── Firehose Direct PUT: JSON -> Parquet, dynamic-partition dt + event_name ─
  resource "aws_kinesis_firehose_delivery_stream" "telemetry" {
    name        = "${local.name_prefix}-telemetry"
    destination = "extended_s3"

    extended_s3_configuration {
      role_arn   = aws_iam_role.firehose_telemetry.arn
      bucket_arn = aws_s3_bucket.analytics_lake.arn

      prefix              = "bronze/events/dt=!{partitionKeyFromQuery:dt}/event_name=!{partitionKeyFromQuery:event_name}/"
      error_output_prefix = "bronze/_errors/!{firehose:error-output-type}/dt=!{timestamp:yyyy-MM-dd}/"

      # ponytail: spec §5.3 INTENT is 5min/5MB to amortise the 5KB-per-record floor.
      # CONSTRAINT: AWS enforces a 64MB buffer FLOOR when BOTH data-format-conversion
      # and dynamic-partitioning are enabled, so 5MB is rejected at apply. 300s/64MB
      # is the smallest legal config; at portfolio volume the 300s timer fires first,
      # so the 5-minute intent is preserved.
      buffering_interval = 300
      buffering_size     = 64

      dynamic_partitioning_configuration {
        enabled = true
      }

      processing_configuration {
        enabled = true
        processors {
          type = "MetadataExtraction"
          parameters {
            parameter_name  = "MetadataExtractionQuery"
            parameter_value = "{dt: .ts_server[0:10], event_name: .event_name}"
          }
          parameters {
            parameter_name  = "JsonParsingEngine"
            parameter_value = "JQ-1.6"
          }
        }
      }

      data_format_conversion_configuration {
        input_format_configuration {
          deserializer {
            open_x_json_ser_de {}
          }
        }
        output_format_configuration {
          serializer {
            parquet_ser_de {}
          }
        }
        schema_configuration {
          database_name = aws_glue_catalog_database.analytics.name
          table_name    = aws_glue_catalog_table.bronze_events.name
          role_arn      = aws_iam_role.firehose_telemetry.arn
          region        = var.aws_region
        }
      }

      cloudwatch_logging_options {
        enabled         = true
        log_group_name  = aws_cloudwatch_log_group.firehose_telemetry.name
        log_stream_name = "S3Delivery"
      }
    }
  }

  # ── Telemetry Lambda: own least-privilege role (Firehose PutRecordBatch only) ─
  resource "aws_iam_role" "telemetry_lambda" {
    name               = "${local.name_prefix}-telemetry-lambda-role"
    assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
  }

  data "aws_iam_policy_document" "telemetry_lambda" {
    statement {
      sid       = "AllowCloudWatchLogs"
      effect    = "Allow"
      actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
      resources = ["${aws_cloudwatch_log_group.telemetry.arn}:*"]
    }
    statement {
      sid       = "AllowFirehosePut"
      effect    = "Allow"
      actions   = ["firehose:PutRecordBatch"]
      resources = [aws_kinesis_firehose_delivery_stream.telemetry.arn]
    }
  }

  resource "aws_iam_role_policy" "telemetry_lambda" {
    name   = "${local.name_prefix}-telemetry-lambda-policy"
    role   = aws_iam_role.telemetry_lambda.id
    policy = data.aws_iam_policy_document.telemetry_lambda.json
  }

  resource "aws_cloudwatch_log_group" "telemetry" {
    name              = "/aws/lambda/${local.telemetry_lambda_name}"
    retention_in_days = var.log_retention_days
  }

  resource "aws_lambda_function" "telemetry" {
    function_name = local.telemetry_lambda_name
    role          = aws_iam_role.telemetry_lambda.arn
    runtime       = "python3.12"
    handler       = "collector.telemetry_handler.lambda_handler"
    filename      = local.lambda_zip_file
    timeout       = 10
    memory_size   = 256

    source_code_hash = filebase64sha256(local.lambda_zip_file)

    environment {
      variables = {
        TELEMETRY_FIREHOSE_STREAM_NAME = aws_kinesis_firehose_delivery_stream.telemetry.name
        LOG_LEVEL                      = "INFO"
      }
    }

    depends_on = [aws_cloudwatch_log_group.telemetry]
  }

  # ── API Gateway wiring: own integration + route (CUSTOM authorizer) ─
  resource "aws_lambda_permission" "telemetry_apigw" {
    statement_id  = "AllowExecutionFromApiGatewayTelemetry"
    action        = "lambda:InvokeFunction"
    function_name = aws_lambda_function.telemetry.function_name
    principal     = "apigateway.amazonaws.com"
    source_arn    = "${aws_apigatewayv2_api.collector.execution_arn}/*/*"
  }

  resource "aws_apigatewayv2_integration" "telemetry_lambda" {
    api_id                 = aws_apigatewayv2_api.collector.id
    integration_type       = "AWS_PROXY"
    integration_uri        = aws_lambda_function.telemetry.invoke_arn
    payload_format_version = "2.0"
  }

  resource "aws_apigatewayv2_route" "telemetry_post" {
    api_id             = aws_apigatewayv2_api.collector.id
    route_key          = "POST /v1/telemetry"
    target             = "integrations/${aws_apigatewayv2_integration.telemetry_lambda.id}"
    authorization_type = "CUSTOM"
    authorizer_id      = aws_apigatewayv2_authorizer.jwt.id
  }
  ```
- [ ] Append two outputs to `infra/outputs.tf` (the Task 6 runbook reads these; without them `terraform output -raw analytics_lake_bucket` / `telemetry_lambda_name` error out):
  ```hcl
  output "analytics_lake_bucket" {
    value = aws_s3_bucket.analytics_lake.bucket
  }

  output "telemetry_lambda_name" {
    value = aws_lambda_function.telemetry.function_name
  }
  ```
- [ ] Format + validate (run from `infra/`; terraform `init -backend=false` is needed for a clean-room validate if `.terraform` is absent):
  ```bash
  cd /Users/roman/Projects/clouder-projects/clouder-core/.claude/worktrees/service_improve/infra && terraform fmt && terraform validate
  ```
  Expected: `terraform fmt` lists `telemetry.tf` (and `main.tf`/`outputs.tf` if reformatted), `terraform validate` prints `Success! The configuration is valid.` If `validate` errors with "provider not initialized", first run `terraform init -backend=false` then re-run `terraform validate`.
- [ ] Commit: stage `infra/main.tf infra/telemetry.tf infra/outputs.tf`, generate subject via **caveman:caveman-commit**, then `git ... commit -m "<subject>"`.

---

### Task 6: Integration smoke (one-shot, against a deployed stack)

**Files:** none (runbook — spec §14 / §17 acceptance "POST a batch → Parquet in `bronze/events/` → Athena `count(*) > 0`"). This is a deploy-and-verify step, not an automated test (a real Firehose→S3→Athena round trip can't be cheaply faked; do not add moto for it).

- [ ] Build the shared zip + apply (telemetry shares the one artifact):
  ```bash
  /Users/roman/Projects/clouder-projects/clouder-core/.claude/worktrees/service_improve/scripts/package_lambda.sh
  cd /Users/roman/Projects/clouder-projects/clouder-core/.claude/worktrees/service_improve/infra && terraform apply
  ```
  Expected: `aws_lambda_function.telemetry`, `aws_kinesis_firehose_delivery_stream.telemetry`, `aws_s3_bucket.analytics_lake`, `aws_glue_catalog_table.bronze_events`, `aws_apigatewayv2_route.telemetry_post` created.
- [ ] Obtain a JWT bearer (manual `/auth/login` → `/auth/callback` flow, per the OpenAPI description) and POST a 2-event batch **through the CloudFront domain** — this proves the new `/v1*` ordered_cache_behavior routes to the api-gw origin, not the SPA shell (which is the headline of MUST-FIX 1). `frontend_url` resolves to `https://<dist>.cloudfront.net`; CloudFront forwards the `Authorization` header via the `AllViewerExceptHostHeader` origin-request policy, so the Bearer POST works end-to-end:
  ```bash
  API="$(cd /Users/roman/Projects/clouder-projects/clouder-core/.claude/worktrees/service_improve/infra && terraform output -raw frontend_url)"
  curl -sS -X POST "$API/v1/telemetry" \
    -H "Authorization: Bearer $JWT" -H "Content-Type: application/json" -H "Accept: application/json" \
    -d '{"events":[
      {"event_name":"track_view","event_id":"smoke-1","session_id":"s","ts_client":"2026-06-27T10:00:00Z","context":{"device":"desktop","route":"/curate/:id"},"props":{"track_id":"t1","dwell_ms":900}},
      {"event_name":"playback_play","event_id":"smoke-2","session_id":"s","ts_client":"2026-06-27T10:00:01Z","context":{"device":"desktop","route":"/curate/:id"},"props":{"track_id":"t1","position_ms":0,"duration_ms":200,"source":"triage_player"}}
    ]}'
  ```
  Expected body: `{"accepted": 2, "rejected": 0}` with HTTP 202.
  - (Optional gateway-route-only check: repeat against `terraform output -raw api_endpoint` — the direct API Gateway invoke URL — to isolate the gateway from CloudFront if the CloudFront hit fails.)
- [ ] After the Firehose buffer flushes (≤ 5 min), confirm a Parquet object landed under the partitioned prefix (and nothing was routed to `bronze/_errors/`, which would mean props failed format conversion):
  ```bash
  LAKE="$(cd /Users/roman/Projects/clouder-projects/clouder-core/.claude/worktrees/service_improve/infra && terraform output -raw analytics_lake_bucket)"
  aws s3 ls "s3://$LAKE/bronze/events/" --recursive | grep -E 'dt=.*/event_name=.*\.parquet'
  aws s3 ls "s3://$LAKE/bronze/_errors/" --recursive  # expect: empty (no conversion failures)
  ```
  Expected: at least one `.parquet` object under `dt=2026-06-27/event_name=track_view/` (and `…/event_name=playback_play/`); `bronze/_errors/` empty.
- [ ] Athena count via partition projection (no MSCK needed):
  ```bash
  aws athena start-query-execution \
    --query-string "SELECT count(*) FROM clouder_analytics.events WHERE dt = date_format(current_date, '%Y-%m-%d')" \
    --query-execution-context Database=clouder_analytics \
    --result-configuration OutputLocation="s3://$LAKE/athena-results/"
  # then: aws athena get-query-results --query-execution-id <id>
  ```
  Expected: scalar result `>= 2`.
- [ ] Confirm logs carry only allowlisted fields and no `bp_token`:
  ```bash
  LAMBDA="$(cd /Users/roman/Projects/clouder-projects/clouder-core/.claude/worktrees/service_improve/infra && terraform output -raw telemetry_lambda_name)"
  aws logs filter-log-events --log-group-name "/aws/lambda/$LAMBDA" --filter-pattern '"telemetry_ingest"' | grep -i bp_token
  ```
  Expected: **no matches** (grep exits 1). The `telemetry_ingest` line shows `message`, `user_id`, `status_code`, `duration_ms`, `count` only (structlog `EventRenamer` puts the event name under `message`).
- [ ] Record results inline in the PR description (no separate report file). If anything fails, use superpowers:systematic-debugging before patching.

---

### Task 7: Finalize

**Files:** none.

- [ ] Full unit suite + final verification:
  ```bash
  PYTHONPATH=/Users/roman/Projects/clouder-projects/clouder-core/.claude/worktrees/service_improve/src \
    /Users/roman/Projects/clouder-projects/clouder-core/.venv/bin/pytest \
    /Users/roman/Projects/clouder-projects/clouder-core/.claude/worktrees/service_improve/tests/unit -q
  ```
  Expected: exit 0.
- [ ] Push the branch and open a PR. Generate **both the PR title and body** via the **caveman:caveman-commit** skill before `gh pr create` (repo policy). PR body multi-line via non-indented heredoc, EOF at column 0; no AI-attribution trailer:
  ```bash
  git -C /Users/roman/Projects/clouder-projects/clouder-core/.claude/worktrees/service_improve push -u origin feat/telemetry-ingest-landing
  gh pr create --title "<caveman-commit title>" --body "$(cat <<'EOF'
  <caveman-commit body>
  EOF
  )"
  ```
- [ ] Use superpowers:verification-before-completion before claiming done: paste the `20 passed` / `11 passed`, `OPENAPI OK`, `terraform validate` Success, and the `{"accepted":2,"rejected":0}` + empty `bronze/_errors/` + Athena `count>=2` evidence into the PR.
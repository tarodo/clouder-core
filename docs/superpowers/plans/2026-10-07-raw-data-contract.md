# Raw Data Contract, Quarantine and Drift Detection Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make "what Beatport sends" an explicit, tested contract: records that break it are quarantined with a reason instead of silently dropped, and new, missing, re-typed or suddenly empty fields raise an alarm on the first run that brings them.

**Architecture:** `collector.contracts` declares the raw Beatport track contract as data — every known top-level field with its allowed JSON types, the two required fields, and per-field NULL-share limits — and `screen(records)` returns the valid records plus a report (quarantined records with reasons, unknown / missing / re-typed fields, NULL shares over limit). The canonicalization worker and the backfill replay screen every run before normalizing: quarantined records go to `raw/bp/releases/_quarantine/run_id=<id>/records.json.gz`, drift is logged as `contract_drift`. CloudWatch metric filters on the worker log turn both into metrics (`CLOUDER/DataContracts`) with alarms. A script audits the whole raw zone against the contract.

**Tech Stack:** Python 3.12 (stdlib), AWS Lambda, S3, CloudWatch Logs metric filters and alarms, Terraform, pytest.

**Spec:** inline — "Spec" section below (source: hiring audit §15.3 "C").

## Global Constraints

- No new runtime dependency (no pydantic model, no jsonschema): the contract is a declarative table in `src/collector/contracts.py`.
- Required fields keep today's normalize rule exactly (`id` positive integer, `name` non-empty string); nothing that is canonicalized today gets quarantined, only made visible.
- A dry-run replay never writes (no quarantine object).
- `log_event` keeps only `ALLOWED_LOG_FIELDS`; field names in drift events are joined strings.
- The worker's IAM role is not widened: quarantine objects go under the existing `${raw_prefix}/` write grant; metrics come from log metric filters, not `PutMetricData`.
- Telemetry already has an edge contract (`TelemetryEnvelope`, `extra="forbid"`, allowlisted props → `props_extra`); it is documented, not changed.
- No money figures in docs. Branch `feat/raw-data-contract` from `origin/main`, worktree `../clouder-core-contract`; `$VENV=<repo>/.venv/bin`; `terraform fmt -check` passes.

## Spec

**Problem (measured 2026-10-07 over the whole raw zone: 154 objects, 107,795 records).**

| | |
|---|---|
| Contract | none written down; `normalize_tracks` silently skips records without a positive `id` or a `name` |
| Silently dropped | 1 record (style 91, week 27: `name = ""`) — nobody knew |
| Schema drift | `is_dj_version` appeared between 2026-07-20 (last object without it) and 2026-09-13 (first with it) and has been on every record since — unnoticed |
| Field profile | 42 top-level keys; `bpm` and `key` NULL once; `sub_genre` NULL on 82.5 % |

**Decisions.**

1. *Contract as data.* `FIELDS: dict[str, frozenset[str]]` — the 42 known top-level keys with allowed JSON types (`integer`, `string`, `boolean`, `object`, `array`, `null`); `REQUIRED = {"id", "name"}` with today's normalize rule; `NULL_SHARE_LIMITS` for the fields canonicalization needs (`isrc`, `bpm`, `length_ms`, `key`, `publish_date`: 1 % per run).
2. *Quarantine, not drop.* A record failing a required rule is quarantined with its reasons; everything else is canonicalized as today. Quarantine object: `raw/bp/releases/_quarantine/run_id=<run_id>/records.json.gz`, JSON list of `{"reasons": [...], "record": {...}}`, written once per run (overwritten on replay — idempotent).
3. *Drift per run.* Unknown keys (not in `FIELDS`), missing keys (in `FIELDS`, on no record of a run with ≥ 1 record — `ALWAYS_PRESENT` excludes keys that are legitimately absent, today `is_dj_version` on old data and none else), type drift (a value whose JSON type is not allowed, per field count), NULL share over limit. Any of them → one `contract_drift` WARNING log with the field names; counts on `canonicalization_completed`.
4. *Metrics and alarms.* Log metric filters on the canonicalization worker log group: `QuarantinedRecords` (value `$.records_quarantined` of `canonicalization_completed`) and `ContractDrift` (1 per `contract_drift`), namespace `CLOUDER/DataContracts`; alarms on daily Sum ≥ 1. Acknowledging a new field = adding it to `FIELDS` (a reviewed code change), which clears the alarm.
5. *Backfill.* The replay screens the same way; dry run reports `records_quarantined` and `drift_fields` per run and in the summary without writing; apply writes the quarantine object.
6. *Audit script.* `scripts/audit_raw_contract.py` screens every raw object (S3 prefix or local dir) and prints per-object drift and quarantine plus the first object where each unknown field appeared.

**Non-goals.** Telemetry `schema_version` (edge contract exists; a version needs a frontend SDK change); nested-object contracts beyond the top level (normalize reads only `id`/`name` of artists/release/label/genre — covered by type checks of the parent); quarantine replay tooling (a quarantined record is fixed upstream and re-ingested).

**Success criteria.** Unit tests for each rule; the audit script over the production raw zone reports exactly the "Before" facts (1 quarantined record; with `is_dj_version` removed from `FIELDS`, the first flagged object is 2026-09-13); deploy creates two metric filters and two alarms; `docs/data/contracts.md` records before/after.

## Review Focus

1. **A record that normalize accepts today is quarantined** (e.g. `bpm` as a string) → must not happen; type drift is reported, the record is canonicalized. Test: `test_type_drift_is_reported_not_quarantined` (Task 1).
2. **An empty run (0 records)** → no "missing fields" drift. Test: `test_empty_run_reports_nothing` (Task 1).
3. **Dry-run backfill** → no quarantine object written. Test: `test_replay_dry_run_does_not_write_quarantine` (Task 2).
4. **Quarantine write fails** (S3 error) → the run fails as transient (retried), it does not silently drop the records. Test: `test_quarantine_write_failure_fails_the_run` (Task 2).
5. **Field names with characters outside the allowlist** (a key like `a b`) → logged safely as one joined string. Test: covered by `test_unknown_fields_are_reported_sorted` (Task 1).

---

### Task 1: The contract and `screen()`, plus the raw-zone audit script

**Files:**
- Create: `src/collector/contracts.py`, `tests/unit/test_contracts.py`, `scripts/audit_raw_contract.py`

**Interfaces:**
- Produces: `contracts.FIELDS`, `contracts.REQUIRED`, `contracts.NULL_SHARE_LIMITS`, `contracts.ALWAYS_PRESENT`; `contracts.screen(records: Sequence[Any]) -> ContractReport` with `ContractReport(valid: list[dict], quarantined: list[dict] (each {"reasons": list[str], "record": Any}), unknown_fields: tuple[str, ...], missing_fields: tuple[str, ...], type_drift: dict[str, int], null_share_over: dict[str, float])` and `ContractReport.drift_fields -> tuple[str, ...]` (sorted union of all drifting field names).

- [ ] **Step 1: Failing tests** — `tests/unit/test_contracts.py`:

```python
from __future__ import annotations

import copy

from collector import contracts
from collector.contracts import screen


def _record(**overrides):
    base = {key: None for key in contracts.FIELDS}
    base.update(
        id=1, name="Track", mix_name="Original Mix", isrc="QZ1", bpm=128, length_ms=300000,
        publish_date="2026-09-26", new_release_date="2026-09-26", key={"name": "A Minor"},
        artists=[{"id": 2, "name": "A"}], release={"id": 3, "name": "R"}, genre={"id": 1, "name": "G"},
        remixers=[], bsrc_remixer=[], free_downloads=[], available_worldwide=True, exclusive=False,
        is_available_for_streaming=True, is_dj_edit=False, is_dj_version=False, is_explicit=False,
        is_hype=False, is_ugc_remix=False, pre_order=False, catalog_number="C1", current_status={},
        encoded_date="2026-09-01T00:00:00", image={}, length="5:00", price={}, publish_status="published",
        sale_type={}, sample_end_ms=1, sample_start_ms=0, sample_url="u", slug="track", url="u",
    )
    base.update(overrides)
    return base


def test_a_conforming_run_is_clean() -> None:
    report = screen([_record(id=1), _record(id=2)])
    assert [r["id"] for r in report.valid] == [1, 2]
    assert report.quarantined == [] and report.drift_fields == ()


def test_records_normalize_would_skip_are_quarantined_with_reasons() -> None:
    report = screen([_record(id=1), _record(id=0), _record(id=2, name="  "), "not a dict"])
    assert [r["id"] for r in report.valid] == [1]
    assert [q["reasons"] for q in report.quarantined] == [
        ["id: not a positive integer"], ["name: empty"], ["record: not an object"],
    ]


def test_type_drift_is_reported_not_quarantined() -> None:
    report = screen([_record(id=1, bpm="128"), _record(id=2)])
    assert [r["id"] for r in report.valid] == [1, 2]
    assert report.type_drift == {"bpm": 1}
    assert report.drift_fields == ("bpm",)


def test_unknown_fields_are_reported_sorted() -> None:
    report = screen([_record(id=1, is_new=True, **{"a b": 1})])
    assert report.unknown_fields == ("a b", "is_new")


def test_a_field_missing_from_every_record_is_reported() -> None:
    rows = [_record(id=i) for i in (1, 2)]
    for row in rows:
        del row["isrc"]
    assert screen(rows).missing_fields == ("isrc",)


def test_null_share_over_the_limit_is_reported() -> None:
    rows = [_record(id=i) for i in range(1, 101)]
    rows[0]["bpm"] = rows[1]["bpm"] = None
    assert screen(rows).null_share_over == {"bpm": 0.02}
    assert screen(rows[1:]).null_share_over == {}


def test_empty_run_reports_nothing() -> None:
    report = screen([])
    assert report.drift_fields == () and report.quarantined == []


def test_the_september_drift_would_have_been_caught(monkeypatch) -> None:
    # The contract as of July did not know is_dj_version.
    fields = dict(contracts.FIELDS)
    del fields["is_dj_version"]
    monkeypatch.setattr(contracts, "FIELDS", fields)
    assert screen([_record(id=1)]).unknown_fields == ("is_dj_version",)
```

Run: `$VENV/pytest tests/unit/test_contracts.py -q` — Expected: `ModuleNotFoundError: No module named 'collector.contracts'`.

- [ ] **Step 2: Implement** — `src/collector/contracts.py`:

```python
"""Contract for raw Beatport track records (docs/data/contracts.md).

The contract is data: every known top-level field with its allowed JSON types,
the fields a record cannot be canonicalized without, and how empty the fields
canonicalization relies on may get per run. `screen` splits a run into records
to canonicalize and records to quarantine, and reports drift: unknown, missing,
re-typed or suddenly empty fields. A new upstream field is acknowledged by
adding it here.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Sequence

_S, _I, _B, _O, _A, _N = "string", "integer", "boolean", "object", "array", "null"

# Field -> allowed JSON types; measured over the raw zone on 2026-10-07.
FIELDS: dict[str, frozenset[str]] = {
    "id": frozenset({_I}),
    "name": frozenset({_S}),
    "mix_name": frozenset({_S, _N}),
    "isrc": frozenset({_S, _N}),
    "bpm": frozenset({_I, _N}),
    "length_ms": frozenset({_I, _N}),
    "length": frozenset({_S, _N}),
    "publish_date": frozenset({_S, _N}),
    "new_release_date": frozenset({_S, _N}),
    "key": frozenset({_O, _N}),
    "artists": frozenset({_A}),
    "remixers": frozenset({_A}),
    "bsrc_remixer": frozenset({_A}),
    "release": frozenset({_O}),
    "genre": frozenset({_O}),
    "sub_genre": frozenset({_O, _N}),
    "available_worldwide": frozenset({_B}),
    "exclusive": frozenset({_B}),
    "is_available_for_streaming": frozenset({_B}),
    "is_dj_edit": frozenset({_B}),
    "is_dj_version": frozenset({_B}),  # appeared upstream between 2026-07-20 and 2026-09-13
    "is_explicit": frozenset({_B}),
    "is_hype": frozenset({_B}),
    "is_ugc_remix": frozenset({_B}),
    "pre_order": frozenset({_B}),
    "pre_order_date": frozenset({_S, _N}),
    "free_downloads": frozenset({_A}),
    "free_download_start_date": frozenset({_S, _N}),
    "free_download_end_date": frozenset({_S, _N}),
    "catalog_number": frozenset({_S, _N}),
    "label_track_identifier": frozenset({_S, _N}),
    "current_status": frozenset({_O, _N}),
    "encoded_date": frozenset({_S, _N}),
    "image": frozenset({_O, _N}),
    "price": frozenset({_O, _N}),
    "publish_status": frozenset({_S, _N}),
    "sale_type": frozenset({_O, _N}),
    "sample_end_ms": frozenset({_I, _N}),
    "sample_start_ms": frozenset({_I, _N}),
    "sample_url": frozenset({_S, _N}),
    "slug": frozenset({_S, _N}),
    "url": frozenset({_S, _N}),
}

# Without these a record cannot become a canonical track (normalize's rule).
REQUIRED = frozenset({"id", "name"})

# Fields canonicalization relies on: share of NULLs per run above which the run drifts.
NULL_SHARE_LIMITS: dict[str, float] = {
    "isrc": 0.01, "bpm": 0.01, "length_ms": 0.01, "key": 0.01, "publish_date": 0.01,
}

# Known fields expected on every record; is_dj_version is absent from data before 2026-09.
ALWAYS_PRESENT = frozenset(FIELDS) - {"is_dj_version"}


@dataclass(frozen=True)
class ContractReport:
    valid: list[dict[str, Any]]
    quarantined: list[dict[str, Any]]
    unknown_fields: tuple[str, ...] = ()
    missing_fields: tuple[str, ...] = ()
    type_drift: dict[str, int] = field(default_factory=dict)
    null_share_over: dict[str, float] = field(default_factory=dict)

    @property
    def drift_fields(self) -> tuple[str, ...]:
        return tuple(sorted(
            set(self.unknown_fields) | set(self.missing_fields)
            | set(self.type_drift) | set(self.null_share_over)
        ))


def json_type(value: Any) -> str:
    if value is None:
        return _N
    if isinstance(value, bool):
        return _B
    if isinstance(value, int):
        return _I
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        return _S
    if isinstance(value, list):
        return _A
    if isinstance(value, dict):
        return _O
    return type(value).__name__


def _required_violations(record: Any) -> list[str]:
    if not isinstance(record, dict):
        return ["record: not an object"]
    reasons = []
    rid = record.get("id")
    if not (isinstance(rid, int) and not isinstance(rid, bool) and rid > 0):
        reasons.append("id: not a positive integer")
    name = record.get("name")
    if not (isinstance(name, str) and name.strip()):
        reasons.append("name: empty")
    return reasons


def screen(records: Sequence[Any]) -> ContractReport:
    valid: list[dict[str, Any]] = []
    quarantined: list[dict[str, Any]] = []
    seen: Counter[str] = Counter()
    nulls: Counter[str] = Counter()
    retyped: Counter[str] = Counter()
    for record in records:
        reasons = _required_violations(record)
        if reasons:
            quarantined.append({"reasons": reasons, "record": record})
            continue
        valid.append(record)
        for key, value in record.items():
            seen[key] += 1
            kind = json_type(value)
            if kind == _N:
                nulls[key] += 1
            allowed = FIELDS.get(key)
            if allowed is not None and kind not in allowed:
                retyped[key] += 1
    n = len(valid)
    if not n:
        return ContractReport(valid=valid, quarantined=quarantined)
    shares = {f: round(nulls[f] / n, 4) for f in NULL_SHARE_LIMITS}
    return ContractReport(
        valid=valid,
        quarantined=quarantined,
        unknown_fields=tuple(sorted(k for k in seen if k not in FIELDS)),
        missing_fields=tuple(sorted(f for f in ALWAYS_PRESENT if f in FIELDS and not seen[f])),
        type_drift=dict(sorted(retyped.items())),
        null_share_over={f: s for f, s in shares.items() if s > NULL_SHARE_LIMITS[f]},
    )
```

(`missing_fields` uses `f in FIELDS` so a monkeypatched contract stays consistent.)

Run the tests — Expected: 8 passed.

- [ ] **Step 3: Audit script** — `scripts/audit_raw_contract.py`: argparse `--dir PATH` (local mirror) or `--bucket NAME --prefix raw/bp/releases` (boto3 list + get, read-only), optional `--without FIELD` (repeatable; removes fields from `contracts.FIELDS` to replay the contract "as it was"). For every `releases.json.gz` in key order (with LastModified), `screen()` it and print one line per object with drift or quarantine; at the end: totals (objects, records, quarantined, objects with drift) and, per unknown field, the first object (by LastModified) where it appeared. Run it over the scratchpad mirror:

`PYTHONPATH=src $VENV/python scripts/audit_raw_contract.py --dir $SCRATCH/raw` → Expected: 154 objects, 107,795 records, 1 quarantined (style 91 week 27, `name: empty`), 0 objects with drift.
`... --without is_dj_version` → Expected: unknown field `is_dj_version` first seen in the object modified 2026-09-13 (style 1, week 29); 88 objects flagged.

Record both outputs in the ledger (they are "Before"/"what the detector would have said" in the docs).

- [ ] **Step 4: Commit** — `feat(contracts): raw Beatport contract and screening`.

---

### Task 2: Quarantine and drift in the worker and the backfill

**Files:**
- Modify: `src/collector/storage.py` (`write_quarantine`), `src/collector/worker_handler.py`, `src/collector/backfill_handler.py`, `src/collector/logging_utils.py`
- Test: `tests/unit/test_worker_handler.py`, `tests/unit/test_backfill_handler.py`, `tests/unit/test_storage_quarantine.py` (create)

**Interfaces:**
- Consumes: `contracts.screen`, `ContractReport` (Task 1).
- Produces: `S3Storage.write_quarantine(run_id: str, quarantined: list[dict]) -> str` (key `f"{raw_prefix}/_quarantine/run_id={run_id}/records.json.gz"`, gzip JSON); `contracts.screen_run(raw_tracks, *, run_id, storage, write: bool, correlation_id: str | None) -> ContractReport` (screens, writes quarantine when `write` and any, logs `contract_drift`); log fields `records_quarantined`, `drift_fields`, `unknown_fields`.

- [ ] **Step 1: Failing tests**
  - `tests/unit/test_storage_quarantine.py`: a fake S3 client captures `put_object`; `write_quarantine("r1", [{"reasons": ["name: empty"], "record": {"id": 1}}])` → key `raw/bp/releases/_quarantine/run_id=r1/records.json.gz`, body gunzips to the list, `ContentEncoding="gzip"`.
  - `tests/unit/test_worker_handler.py`: (a) `test_worker_quarantines_records_it_cannot_canonicalize` — S3 data = the happy record + `{"id": 2, "name": ""}` → `processed == 1`, one quarantine `put_object` with key `.../_quarantine/run_id=run-42/records.json.gz`; (b) `test_worker_logs_contract_drift` — record with an extra key `is_new` → a `contract_drift` log event with `unknown_fields="is_new"` (capture via monkeypatching `collector.contracts.log_event`); (c) `test_quarantine_write_failure_fails_the_run` — the fake S3 client raises on `put_object` → the worker re-raises (transient) and marks the run FAILED.
  - `tests/unit/test_backfill_handler.py`: `test_replay_dry_run_does_not_write_quarantine` and `test_replay_apply_writes_quarantine` with a storage fake that records `write_quarantine`; the replay result carries `records_quarantined` and `drift_fields`; `summarize` sums `records_quarantined` and unions `drift_fields`.

Run the four files — Expected: failures on the missing `write_quarantine` / `screen_run` / result keys.

- [ ] **Step 2: Implement**
  - `S3Storage.write_quarantine` (reuse `_put_object` with gzip + `application/json`).
  - `contracts.screen_run(...)`: `report = screen(raw)`; if `write and report.quarantined`: `storage.write_quarantine(run_id, report.quarantined)`; if `report.drift_fields`: `log_event("WARNING", "contract_drift", run_id=..., correlation_id=..., drift_fields=",".join(report.drift_fields), unknown_fields=",".join(report.unknown_fields), count=len(report.drift_fields))`; return report.
  - Worker: after `read_releases`, `phase = "screen"`, `report = screen_run(raw_tracks, run_id=run_id, storage=storage, write=True, correlation_id=correlation_id)`; normalize `report.valid`; add `records_quarantined=len(report.quarantined)` and `drift_fields=",".join(report.drift_fields)` to `canonicalization_completed`. A quarantine write error propagates (not in `_PERMANENT_ERRORS` → transient).
  - Backfill `replay`: `report = screen_run(raw, run_id=run["run_id"], storage=storage, write=not dry_run, correlation_id=run["run_id"])`; normalize `report.valid`; result gains `records_quarantined`, `drift_fields` (list); `summarize` adds `records_quarantined` to totals and the sorted union of `drift_fields`.
  - `ALLOWED_LOG_FIELDS`: `records_quarantined`, `drift_fields`, `unknown_fields`.

Run: the four files, then `$VENV/pytest -q` — Expected: all pass.

- [ ] **Step 3: Commit** — `feat(worker): quarantine bad records, log contract drift`.

---

### Task 3: Metrics and alarms

**Files:**
- Create: `infra/data_contracts.tf`
- Test: `tests/unit/test_lakehouse_infra.py` → rename not needed; create `tests/unit/test_contract_alarms_infra.py`

- [ ] **Step 1: Failing test** — `tests/unit/test_contract_alarms_infra.py` reads `infra/data_contracts.tf` and asserts two `aws_cloudwatch_log_metric_filter` resources on `aws_cloudwatch_log_group.canonicalization_worker.name` with patterns `{ $.message = "canonicalization_completed" }` (value `$.records_quarantined`) and `{ $.message = "contract_drift" }` (value `1`), namespace `CLOUDER/DataContracts`, and two alarms with `threshold = 1` and `treat_missing_data = "notBreaching"`. Run — Expected: FileNotFoundError.

- [ ] **Step 2: Terraform** — `infra/data_contracts.tf`:

```hcl
# ── Raw data contract: quarantine and drift metrics (docs/data/contracts.md) ──
# Metric filters on the worker's structured logs; no PutMetricData grant needed.

locals {
  data_contracts_namespace = "CLOUDER/DataContracts"
}

resource "aws_cloudwatch_log_metric_filter" "quarantined_records" {
  name           = "${local.name_prefix}-quarantined-records"
  log_group_name = aws_cloudwatch_log_group.canonicalization_worker.name
  pattern        = "{ $.message = \"canonicalization_completed\" }"

  metric_transformation {
    name          = "QuarantinedRecords"
    namespace     = local.data_contracts_namespace
    value         = "$.records_quarantined"
    default_value = "0"
  }
}

resource "aws_cloudwatch_log_metric_filter" "contract_drift" {
  name           = "${local.name_prefix}-contract-drift"
  log_group_name = aws_cloudwatch_log_group.canonicalization_worker.name
  pattern        = "{ $.message = \"contract_drift\" }"

  metric_transformation {
    name      = "ContractDrift"
    namespace = local.data_contracts_namespace
    value     = "1"
  }
}

resource "aws_cloudwatch_metric_alarm" "quarantined_records" {
  alarm_name          = "${local.name_prefix}-quarantined-records"
  alarm_description   = "Raw records failed the contract and were quarantined — docs/data/contracts.md"
  namespace           = local.data_contracts_namespace
  metric_name         = "QuarantinedRecords"
  statistic           = "Sum"
  period              = 86400
  evaluation_periods  = 1
  threshold           = 1
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "notBreaching"

  alarm_actions = var.alarm_sns_topic_arn != "" ? [var.alarm_sns_topic_arn] : []
  ok_actions    = var.alarm_sns_topic_arn != "" ? [var.alarm_sns_topic_arn] : []
}

resource "aws_cloudwatch_metric_alarm" "contract_drift" {
  alarm_name          = "${local.name_prefix}-contract-drift"
  alarm_description   = "Beatport records drifted from the contract (unknown/missing/re-typed/empty fields) — docs/data/contracts.md"
  namespace           = local.data_contracts_namespace
  metric_name         = "ContractDrift"
  statistic           = "Sum"
  period              = 86400
  evaluation_periods  = 1
  threshold           = 1
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "notBreaching"

  alarm_actions = var.alarm_sns_topic_arn != "" ? [var.alarm_sns_topic_arn] : []
  ok_actions    = var.alarm_sns_topic_arn != "" ? [var.alarm_sns_topic_arn] : []
}
```

Run the test + `terraform -chdir=infra fmt -check` — Expected: pass, clean. Commit `feat(infra): contract drift and quarantine alarms`.

---

### Task 4: Docs

**Files:** Create `docs/data/contracts.md`, `docs/adr/0026-raw-data-contract.md`; Modify `docs/adr/README.md` (row, next free `0027`), `docs/data/README.md`, `docs/data/canonicalization.md` (screening step before normalize), `docs/ops/runbook.md` (section "Contract drift or quarantined records").

- `docs/data/contracts.md`: **Why** (upstream changes surface late or not at all), **Before** (Spec table), **The contract** (table of fields: required / used by canonicalization with allowed types and NULL limits / known), **What changed** (screening, quarantine location and format, drift kinds, metrics, alarms, backfill reporting, audit script, telemetry's existing edge contract), **How to respond** (drift alarm → read `contract_drift` logs → acknowledge in `FIELDS` or fix upstream; quarantine → read the object, fix upstream, re-ingest), **After** (the audit over the raw zone with the current contract, and with July's contract: the September drift caught on the first object; production numbers from the first runs pending), **What it buys**, **Not done, and why**.
- ADR-0026: contract as data vs pydantic/JSON Schema; quarantine vs drop vs fail; metric filters vs PutMetricData.
- Doc check: files exist, `0026-raw-data-contract` in the index, `grep -nE '\$[0-9]|USD|руб'` → 0; full suite green. Commit `docs(contracts): raw data contract guide and ADR-0026`, then `chore(graphify): refresh graph after data contract`.

## After merge (loop follow-up)

1. Deploy; verify the two metric filters and alarms exist.
2. Backfill dry run (`--input '{}'`): summary `records_quarantined` = 1 and `drift_fields` = [] expected; apply only the run with the quarantined record (style 91) to write its quarantine object.
3. Fill "After" in `docs/data/contracts.md` and the audit; stop the loop (all five initiatives closed).

# Raw data contract

Status: deployed on 2026-10-07.

## Why

Everything downstream assumes a shape for Beatport's track records, but that shape was written
down nowhere except in `normalize_tracks`, which skips a record it cannot use without saying
so. An upstream change — a field renamed, re-typed, emptied or added — would surface as a
canonicalization error, as quietly NULL columns, or not at all. The contract makes the shape
explicit and tested, keeps bad records instead of losing them, and raises an alarm on the
first run that drifts.

## Before (2026-10-07, the whole raw zone: 154 objects, 107,795 records)

| | |
|---|---|
| Contract | none written down; `normalize_tracks` silently skipped records without a positive `id` or a `name` |
| Silently dropped | 1 record (style 91, week 27, `name = ""`, ingested 2026-07-13) — nobody knew |
| Schema drift | Beatport added `is_dj_version` between 2026-07-20 (last object without it) and 2026-09-13 (first with it); it has been on every record since — unnoticed for weeks |
| Field profile | 42 top-level fields; `bpm` and `key` NULL once; `sub_genre` NULL on 82.5 % |

## The contract

Declared as data in `src/collector/contracts.py`:

| Part | Fields | Rule |
|---|---|---|
| Required | `id`, `name` | `id` is a positive integer, `name` a non-empty string — otherwise the record is **quarantined** (the same rule normalize applied, now visible) |
| Used by canonicalization | `mix_name`, `isrc`, `bpm`, `length_ms`, `publish_date`, `new_release_date`, `key`, `artists`, `release`, `genre` | allowed JSON types per field; `isrc`, `bpm`, `length_ms`, `key`, `publish_date` may be NULL on at most 1 % of a run's records |
| Known | the other 30 top-level fields (`remixers`, `sub_genre`, `is_dj_version`, `price`, …) | allowed JSON types; expected on every record, except the `OPTIONAL` ones that older raw objects lack (today `is_dj_version`) |

A record is never quarantined for a type or presence problem: those are **drift** — the run is
canonicalized as before and the drift is reported. An absent key counts as empty for the NULL
limits (normalize reads it the same way). A quarantined record contributes nothing: before, normalize
still took its artists, release and label and recorded a track–artist link to a track it never
created; the one real case (Beatport track 29381883) loses nothing, as its release, label and
artist appear on other tracks.

## What changed

- **Screening.** Every run — live ingest and backfill — is screened before normalize:
  `screen()` returns the records to canonicalize and the records to quarantine, plus drift:
  unknown fields, fields missing from every record of the run, values of a type the contract
  does not allow (count per field), and NULL shares over the limit.
- **Quarantine.** Records that fail a required rule are written, with their reasons, to
  `raw/bp/releases/_quarantine/run_id=<run_id>/records.json.gz` (a JSON list of
  `{"reasons": [...], "record": {...}}`), one object per run, overwritten on replay. A failed
  quarantine write fails the run (it is retried), so a record can no longer disappear.
- **Drift.** A drifting run logs one `contract_drift` event naming each kind: `unknown_fields`,
  `missing_fields`, `type_drift` (`field=count`), `null_share_over` (`field=share`);
  `canonicalization_completed` carries `records_quarantined` and `drift_fields`.
- **Metrics and alarms.** Log metric filters on the canonicalization worker turn these into
  `CLOUDER/DataContracts` metrics `QuarantinedRecords` and `ContractDrift`, with the alarms
  `clouder-prod-quarantined-records` and `clouder-prod-contract-drift` (daily sum ≥ 1; they
  email the owner through the alarm topic, like every alarm here — `docs/ops/deploy.md`).
- **Backfill.** A replay screens the same way; the summary carries `records_quarantined` and
  the union of `drift_fields`. A dry run writes no quarantine object; an apply writes it (the
  backfill role may put objects under `_quarantine/` only).
- **Audit.** `scripts/audit_raw_contract.py` screens every raw object (S3 or a local mirror),
  read-only; `--without FIELD` replays the contract as it was before a field was acknowledged.

Telemetry already had an edge contract: `TelemetryEnvelope` forbids unknown top-level keys and
only allowlisted props reach the lake (the rest land in `props_extra`); it is unchanged.

## How to respond

- **`contract-drift` alarm.** Read the run's `contract_drift` log — it names the kind of drift
  per field. A new upstream field that is fine: add it to `FIELDS` and, since older raw objects
  lack it, to `OPTIONAL` (a reviewed change); the alarm returns to OK after a day without
  drift. A field that went missing, changed type or emptied: check what canonicalization reads
  from it before acknowledging it.
- **`quarantined-records` alarm.** Read the run's quarantine object and fix the cause upstream,
  then re-ingest the week. A replay re-reads the same raw object and quarantines the same
  record again; it helps only after the contract itself changed (`docs/ops/backfill.md`).

## After

| | Result |
|---|---|
| Audit of the raw zone with the current contract | 154 objects, 107,795 records, 1 quarantined (style 91, week 27, `name: empty`), 0 objects with drift |
| Audit with the contract as of July (`--without is_dj_version`) | drift flagged on 88 objects, the first being the run of 2026-09-13 13:46 UTC — the alarm would have fired on that run instead of never |
| Production, full backfill dry run (2026-10-07) | 153 runs, 100,268 tracks: 1 record to quarantine, no drift, no track changes |
| Production, applied replay of style 91 | the quarantine object written (`run_id=28a98d2d…/records.json.gz`, reason `name: empty`); alarms OK |

## What it buys

- The shape the pipeline relies on is written down, reviewed and tested; changing it is a
  code review, not a surprise.
- No record is lost silently: a bad one is kept with its reason and counted.
- Upstream changes surface on the run that brings them, as an alarm with the field names.
- The whole history can be audited against the contract in one command.

## Not done, and why

- **Telemetry `schema_version`.** The edge contract already guards the envelope; a version
  needs a frontend SDK change and has no reader yet.
- **Contracts for nested objects** (artists, release, label, genre). Canonicalization reads only
  their `id` and `name`; their parents' types are checked.
- **Replaying quarantined records.** A quarantined record is fixed upstream and re-ingested.

# ADR-0023: Data-quality checks as plain SQL in a scheduled Lambda
Status: Accepted
Date: 2026-10-07

## Context

Alarms covered pipeline health (Lambda errors, DLQ depth, latency, Aurora capacity) but not
data health: freshness per style, weekly volume, ISRC and Spotify coverage, identity-map
integrity, plausible values. A stuck ingest run was found only by a manual query.

Options considered:
- **Great Expectations / Soda / Deequ** — expressive and well known, but a new runtime and
  configuration surface (and Spark for Deequ) for about ten checks over one Postgres database,
  plus a store for results.
- **dbt tests** — natural if a dbt project existed; it does not today (a dbt layer may come
  later for the analytics lake, not for Aurora).
- **Plain SQL checks** — each check is one read-only statement returning a number, compared
  with a threshold, run by the existing Python stack through the RDS Data API.

## Decision

Checks are plain SQL in `src/collector/data_quality.py`, run nightly (00:10 UTC, after the
catalog export, with a wake-up probe for an auto-paused Aurora) by a dedicated Lambda with its
own least-privilege role.
CloudWatch is both the metric store (namespace `CLOUDER/DataQuality`, one metric per check plus
`FailedChecks`) and the alert channel (alarm on `FailedChecks ≥ 1`).

## Consequences

- No new service or runtime; checks live next to the code they guard and are tested against
  Postgres like the repositories.
- History comes from CloudWatch's 15-month retention; there is no results table and no
  row-level report — a failing check names the problem, the investigation uses SQL.
- Adding a check is one entry in `CHECKS` plus a Postgres test; thresholds are the SLOs in
  `docs/data/data-quality.md`.
- Revisit if a dbt project lands: its tests could absorb row-level checks on the
  lake, while catalog checks stay here.

**Cross-references:** ADR-0001, `docs/data/data-quality.md`.

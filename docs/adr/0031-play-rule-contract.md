# ADR-0031: One play rule in two engines, pinned by a shared contract test
Status: Accepted
Date: 2026-11-01

## Context

A play is a `playback_play` and the pauses, resumes and end that follow it. Its listened time is
the playing stretches, capped at the track's duration, with a 10-minute fallback when the duration
is unknown. Two places compute it:

- `_plays_cte` in `src/collector/analytics_handler.py`: Athena SQL built in Python, run live
  for the listening and time-per-track cards.
- `gold.fct_play` in dbt: built nightly into Iceberg, with the track's style as of the play
  ([ADR-0025](0025-iceberg-dbt-lakehouse.md)).

The cards read silver history plus the last three days straight from bronze, so the Lambda needs
the rule whether or not gold has it. Each copy had its own tests, but nothing compared them, so a
change to the rule in one copy would pass both suites. Comparing them found a real gap: dbt drops
an event whose `ts_client` doesn't parse (`stg_events` uses `try`), while the Lambda failed the
whole query on it and returned 500 for that user's cards.

## Decision

- Keep two implementations, each in its own form: Python-built SQL for Trino/DuckDB, and a dbt
  model.
- The dbt unit test `fct_play_follows_the_play_rule` (`dbt/models/gold/_gold.yml`) is the
  contract. Its rows are events as they sit in `silver.events`. It expects one play per row with
  user, track, stage, start and `ms`.
- It covers:
  - pause, resume and end
  - older data that runs to the next play
  - the duration cap
  - the 10-minute fallback
  - a `ts_client` tie broken by `event_id`
  - an unparsable `ts_client`
  - interleaved users
  - a resume before any play
- dbt runs it in CI. `tests/unit/test_analytics_play_contract.py` loads the same rows and runs
  them through `_plays_cte` on DuckDB.
- Both checks are triggered for any change:
  - the rows live under `dbt/`, so editing them runs the dbt job;
  - pytest runs on every pull request.

  A rule changed on one side alone fails CI; changing it means editing both copies and the
  contract in one pull request.
- An unparsable `ts_client` drops the event on both sides.

## Alternatives rejected

- **One SQL generator for both**, from Python or from shared Jinja macros. That is more
  machinery than the ~40 lines the two share, across different dialects.
- **Cards read `gold.fct_play`.** Gold is nightly. The three-day tail would still need the
  Lambda's rule, so the duplication stays and the cards lose freshness.
- **pytest compiles and runs the dbt model.** This brings dbt and Jinja rendering into the
  Python tests. Shared rows give the same guarantee.
- **A written spec of the rule.** That would be a third copy that could drift. The contract rows
  are the executable spec; the prose stays in `_plays_cte`'s docstring and
  `docs/data/lakehouse.md`.

## Consequences

- The contract proves the logic on DuckDB, not on Athena, so Trino-only problems (functions,
  types) slip past it. Changed card SQL is still run once in Athena before merging.
- Percentiles (`approx_percentile` vs `quantile_cont`) are outside the contract. It compares
  `ms` per play.
- Silver deduplicates events; the bronze tail doesn't. A redelivered event can make the last
  three days differ from gold, and the contract can't see it, because both sides get the same
  deduplicated rows.
- `gold.fct_play` has no serving reader yet. The contract keeps it trustworthy for the planned
  switch of time-per-track to point-in-time style.

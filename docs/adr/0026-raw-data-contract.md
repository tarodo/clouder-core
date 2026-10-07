# ADR-0026: Raw Beatport data contract as data, with quarantine and drift alarms
Status: Accepted
Date: 2026-10-07

## Context

The shape of a raw Beatport track lived only in `normalize_tracks`, which skipped records it
could not use without a trace. Over the whole raw zone (107,795 records) that had dropped one
record silently, and an upstream field (`is_dj_version`) had been added in September without
anyone noticing. A bigger change — a renamed or re-typed field the pipeline reads — would have
shown up as errors or as quietly empty columns.

Options considered:
- **pydantic model / JSON Schema** — familiar, but a model mixes "cannot use this record" with
  "this field changed", and a schema library adds a dependency for a 42-field table.
- **Contract as data** — a table of fields and allowed JSON types, two required fields, NULL
  limits; a small screening function reports each kind of problem separately.

For bad records: drop (status quo), fail the run, or quarantine. For signals: `PutMetricData`
from the worker (a wider role), or metric filters on its structured logs.

## Decision

- The contract is data in `src/collector/contracts.py`; required rules equal normalize's rule
  so nothing canonicalized today is rejected.
- Records failing a required rule are quarantined to S3 with reasons; a failed quarantine write
  fails the run (retried). Type, presence and NULL-share problems are drift: reported, not
  rejected.
- Drift and quarantine counts are structured log fields; CloudWatch metric filters turn them
  into `CLOUDER/DataContracts` metrics with alarms. A new upstream field is acknowledged by
  adding it to the contract.
- The backfill screens replays the same way; dry runs write nothing.

## Consequences

- Upstream changes surface on the first run that brings them; acknowledging one is a reviewed
  code change.
- The worker's IAM role is unchanged (quarantine objects live under the raw prefix it already
  writes; metrics come from logs).
- The contract covers top-level fields; nested objects are checked through their parent's type.
- Until `alarm_sns_topic_arn` is set, the alarms are visible in CloudWatch but notify no one.

**Cross-references:** ADR-0023, ADR-0024, `docs/data/contracts.md`.

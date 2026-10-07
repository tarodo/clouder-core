# Data quality

Status: checks deployed; "After" is filled from the first nightly run.

## Why

The pipeline was watched — Lambda errors, DLQ depth, API latency — but the data was not. A
run can succeed and still leave the catalog wrong: a style that quietly stopped being ingested,
a week with half the usual releases, ISRC or Spotify coverage sliding, identity rows pointing
at nothing, an ingest run stuck without a final status. On 2026-10-06 one such stuck run was
found only by a manual query. These checks turn "the pipeline ran" into "the data is right"
and say so every night.

## Checks

| Check | Measures | Pass | Why it matters |
|---|---|---|---|
| `stuck_ingest_runs` | runs not COMPLETED/FAILED two hours after they started | 0 | a run that never finishes means a week that never reaches the catalog |
| `styles_behind` | active styles (ingested within 8 weeks) whose latest completed week ends before the Saturday-week that is due (week end + 3 days) | 0 | freshness: users curate the week that just closed |
| `weekly_volume_anomalies` | styles whose latest week has under half or over twice the median of their previous 8 weeks (≥ 4 weeks of history) | 0 | an upstream API change or a broken page loop shows up as volume first |
| `isrc_coverage_pct` | tracks created in the last 30 days that carry an ISRC | ≥ 99 % | ISRC is the cross-vendor join key |
| `spotify_match_pct` | tracks searched on Spotify in the last 30 days that were found | ≥ 95 % | playback and publishing need the Spotify id |
| `spotify_unsearched_stale` | tracks older than a day that were never searched | 0 | a lost search message leaves tracks unplayable forever |
| `orphan_identities` | `identity_map` rows whose canonical row does not exist | 0 | the identity map is the catalog's foreign key to the outside world |
| `artists_without_identity` | canonical artists no source maps to | recorded | duplicate suspects (e.g. created by a Spotify playlist import) |
| `bpm_out_of_range` | tracks with BPM outside 40–250 | 0 | implausible values break DJ filters |
| `length_out_of_range` | tracks with a length of zero or over an hour | 0 | same |
| `review_backlog_days` | age of the oldest pending match review | ≤ 14 days | matches stuck in review keep playlists unpublished |

A check with nothing to measure (no tracks in the window, no pending reviews) passes and
publishes no metric. A check whose SQL fails is recorded as failed, so a broken check cannot
hide behind a green run. The SQL lives in `src/collector/data_quality.py` and is tested against
Postgres (`tests/db/test_data_quality_pg.py`).

## SLOs

| Area | Objective |
|---|---|
| Freshness | every active style's Saturday-week is in the catalog within 3 days of its close |
| Completeness | ISRC on ≥ 99 % and a Spotify match for ≥ 95 % of the last 30 days' tracks |
| Integrity | no orphan identity rows; no ingest run stuck without a final status |
| Plausibility | no BPM or length outside physical ranges |
| Operations | no match waits for review longer than 14 days |

## How it runs

EventBridge starts `clouder-prod-data-quality` at 00:10 UTC, ten minutes after the nightly
catalog export has already woken the auto-paused Aurora. The Lambda runs the checks through
the RDS Data API with its own role (Data API, the cluster secret, `PutMetricData` limited to its
namespace), logs a `dq_check_result` event per check, publishes every measured value plus
`FailedChecks` to the CloudWatch namespace `CLOUDER/DataQuality`, and the alarm
`clouder-prod-data-quality-failed-checks` fires on `FailedChecks ≥ 1`. Alarm notifications go
to SNS when `alarm_sns_topic_arn` is set, like every other alarm. Why plain SQL and CloudWatch
rather than a DQ framework: ADR-0023.

## Before (2026-10-06)

| | |
|---|---|
| Data checks | none — only pipeline health (errors, DLQ depth, latency) was alarmed |
| Found by hand | 1 ingest run of 156 without a final status |
| Catalog-wide, by hand | ISRC on 100 % of tracks; 96.9 % matched on Spotify |

## After

Filled from the first nightly run (CloudWatch `CLOUDER/DataQuality`).

## What it buys

- Data problems surface the next morning as an alarm with the failing check's name, instead
  of when a user notices a missing week.
- Every check has an explicit threshold, so "is the data fine?" has a yes/no answer and a
  history (CloudWatch keeps metrics for 15 months).
- Thresholds double as the SLOs above, so changes to the pipeline can be judged against them.

## How to read the numbers

```bash
aws cloudwatch get-metric-statistics --namespace CLOUDER/DataQuality \
  --metric-name spotify_match_pct --start-time <from> --end-time <to> \
  --period 86400 --statistics Maximum
aws logs filter-log-events --log-group-name /aws/lambda/clouder-prod-data-quality \
  --filter-pattern '{ $.message = "dq_check_result" }'
```

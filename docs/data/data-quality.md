# Data quality

Status: deployed; first results on 2026-10-07.

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
| `stuck_ingest_runs` | runs from the last 14 days not COMPLETED/FAILED two hours after they started | 0 | a run that never finishes means a week that never reaches the catalog |
| `styles_behind` | active, visible styles (ingested within 8 weeks, not hidden) whose latest completed week ends before the Saturday-week that is due | 0 | freshness: users curate the week that just closed |
| `weekly_volume_anomalies` | active, visible styles whose latest closed week has under half or over twice the median of their previous 8 weeks (≥ 4 weeks of history; custom-range runs ignored) | 0 | an upstream API change or a broken page loop shows up as volume first |
| `isrc_coverage_pct` | Beatport tracks created in the last 30 days that carry an ISRC | ≥ 99 % | ISRC is the cross-vendor join key |
| `spotify_match_pct` | Beatport tracks created in the last 30 days and already searched that were found (retries of older tracks do not skew it) | ≥ 95 % | playback and publishing need the Spotify id |
| `spotify_unsearched_stale` | tracks with an ISRC, older than a day, never searched | 0 | a lost search message leaves tracks unplayable forever |
| `orphan_identities` | `identity_map` rows whose canonical row does not exist | 0 | the identity map is the catalog's foreign key to the outside world |
| `artists_without_identity` | canonical artists no source maps to | recorded | duplicate suspects (e.g. created by a Spotify playlist import) |
| `bpm_out_of_range` | tracks with BPM outside 40–250 | 0 | implausible values break DJ filters |
| `length_out_of_range` | tracks with a length of zero or over three hours (continuous DJ mixes run for hours) | 0 | same |
| `review_backlog_days` | age of the oldest pending match review | recorded | matches stuck in review keep playlists unpublished; it is user workflow state, so it is tracked, not alarmed |

A check with nothing to measure (no tracks in the window, no pending reviews) passes and
publishes no metric. A check whose SQL fails is recorded as failed, so a broken check cannot
hide behind a green run. The SQL lives in `src/collector/data_quality.py` and is tested against
Postgres (`tests/db/test_data_quality_pg.py`).

## SLOs

| Area | Objective |
|---|---|
| Freshness | every active, visible style's Saturday-week (closing Friday) is in the catalog by the end of the following Monday, UTC — checked at 00:10 UTC on Tuesday |
| Completeness | ISRC on ≥ 99 % and a Spotify match for ≥ 95 % of the last 30 days' tracks |
| Integrity | no orphan identity rows; no ingest run stuck without a final status |
| Plausibility | no BPM or length outside physical ranges |
| Operations | match-review backlog age is tracked (no alarm) |

## How it runs

EventBridge starts `clouder-prod-data-quality` at 00:10 UTC. The 00:00 catalog export usually
leaves Aurora awake (it auto-pauses after 300 s idle), and a wake-up probe (`SELECT 1` for up to
60 s on `DatabaseResumingException`) covers the nights it does not, so a paused database delays
the run instead of failing every check. The Lambda runs the checks through
the RDS Data API with its own role (Data API, the cluster secret, `PutMetricData` limited to its
namespace), logs a `dq_check_result` event per check, publishes every measured value plus
`FailedChecks` to the CloudWatch namespace `CLOUDER/DataQuality`, and the alarm
`clouder-prod-data-quality-failed-checks` fires on `FailedChecks ≥ 1`. The failing check's name
is in that night's `dq_check_result` logs. Like every other alarm here, it notifies only when
`alarm_sns_topic_arn` is set; until then it is visible in the CloudWatch console. One combined
alarm means a check that stays red masks new failures until it is fixed — runs older than two
weeks are left out of `stuck_ingest_runs` and the review backlog is recorded only, so the
alarm reflects recent, actionable problems. Why plain SQL and CloudWatch
rather than a DQ framework: ADR-0023.

## Before (2026-10-06)

| | |
|---|---|
| Data checks | none — only pipeline health (errors, DLQ depth, latency) was alarmed |
| Found by hand | 1 ingest run of 156 without a final status |
| Catalog-wide, by hand | ISRC on 100 % of tracks; 96.9 % matched on Spotify |

## After (first run, 2026-10-07 12:46 UTC)

The first run came from the backfill's quality gate, a few hours before the first scheduled
night; the values are the ones published to `CLOUDER/DataQuality`.

| Check | Value | Result |
|---|---|---|
| `stuck_ingest_runs` | 0 | pass |
| `styles_behind` | 2 | **fail** — two active styles had not ingested the week that closed on Friday 2026-10-02 |
| `weekly_volume_anomalies` | 0 | pass |
| `isrc_coverage_pct` | 100 % | pass |
| `spotify_match_pct` | 96.85 % | pass |
| `spotify_unsearched_stale` | 0 | pass |
| `orphan_identities` | 0 | pass |
| `artists_without_identity` | 24 | recorded |
| `bpm_out_of_range` | 0 | pass |
| `length_out_of_range` | 0 | pass |
| `review_backlog_days` | 129.8 | recorded |

Day one: ten checks green, and one real gap caught — two styles a week behind — that nothing
had reported before.

## What it buys

- Data problems surface the next morning as an alarm (the logs name the check), instead of
  when a user notices a missing week.
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

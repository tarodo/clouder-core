"""Sessionization rollup SQL for the analytics v2 marts.

One SQL source, two dialects: Trino/Athena in production, DuckDB in tests.
The gaps-and-islands logic (5-min idle splits a session) and all metrics are
identical across dialects; only timestamp parsing, epoch conversion, and the
percentile function differ — isolated in the DIALECT dicts. See the activity
model in the plan / spec.
"""

from __future__ import annotations

from typing import Mapping

# Dialect-specific function fragments. {} is the single positional arg.
TRINO: Mapping[str, str] = {
    "to_ts": "from_iso8601_timestamp({})",
    "epoch": "to_unixtime({})",
    "to_date": "date({})",
    "pctl": "approx_percentile({}, {})",
}
DUCKDB: Mapping[str, str] = {
    "to_ts": "CAST({} AS TIMESTAMP)",
    "epoch": "epoch({})",
    "to_date": "CAST({} AS DATE)",
    "pctl": "quantile_cont({}, {})",
}

_NEW_SESSION_GAP_S = 300

# Per-row contribution expressions (no curly braces — safe inside f-strings).
_PROMOTED_CONTRIB = """CASE
    WHEN activity_type = 'triage' AND event_name = 'track_categorized'
         AND action IN ('moved_to_bucket', 'categorized_curate')
         AND category_key <> 'DISCARD' THEN 1
    WHEN activity_type = 'triage' AND event_name = 'track_categorized'
         AND action = 'undo' AND category_key <> 'DISCARD' THEN -1
    WHEN activity_type = 'category' AND event_name = 'playlist_add'
         AND source_category_id IS NOT NULL THEN track_count
    ELSE 0 END"""

_DELETED_CONTRIB = """CASE
    WHEN activity_type = 'triage' AND event_name = 'track_categorized'
         AND action IN ('moved_to_bucket', 'categorized_curate')
         AND category_key = 'DISCARD' THEN 1
    WHEN activity_type = 'triage' AND event_name = 'track_categorized'
         AND action = 'undo' AND category_key = 'DISCARD' THEN -1
    WHEN activity_type = 'category' AND event_name = 'track_categorized'
         AND action = 'removed_from_category' THEN 1
    ELSE 0 END"""


def _sessioned_cte(d: Mapping[str, str], source: str) -> str:
    """Shared classified→events→gapped→sessioned CTE block (no leading WITH)."""
    ts = d["to_ts"].format("ts_server")
    epoch_ts = d["epoch"].format("ts")
    return f"""classified AS (
  SELECT
    user_id, {ts} AS ts, event_name, track_id, source, action,
    category_key, track_count, source_category_id, decision_ms,
    CASE
      WHEN event_name = 'track_categorized' AND action = 'removed_from_category' THEN 'category'
      WHEN event_name = 'playlist_add' AND source_category_id IS NOT NULL         THEN 'category'
      WHEN event_name IN ('triage_session_start', 'triage_session_end', 'track_view',
                          'track_categorized', 'hotkey_used')                     THEN 'triage'
      WHEN source = 'triage_player'   THEN 'triage'
      WHEN source = 'category_player' THEN 'category'
      WHEN source = 'playlist_player' THEN 'playlist'
      ELSE NULL
    END AS activity_type
  FROM {source}
  WHERE user_id IS NOT NULL
),
events AS (SELECT * FROM classified WHERE activity_type IS NOT NULL),
gapped AS (
  SELECT *,
    CASE WHEN {epoch_ts} - lag({epoch_ts}) OVER (
           PARTITION BY user_id, activity_type ORDER BY ts) > {_NEW_SESSION_GAP_S}
         THEN 1 ELSE 0 END AS is_new
  FROM events
),
sessioned AS (
  SELECT *,
    SUM(is_new) OVER (PARTITION BY user_id, activity_type ORDER BY ts
                      ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) AS session_seq
  FROM gapped
)"""


def sessions_sql(d: Mapping[str, str], *, source: str = "bronze_events") -> str:
    """SQL selecting one row per derived session (fact_session grain)."""
    epoch_max = d["epoch"].format("max(ts)")
    epoch_min = d["epoch"].format("min(ts)")
    to_date = d["to_date"].format("min(ts)")
    return f"""
WITH {_sessioned_cte(d, source)}
SELECT
  user_id, activity_type, session_seq,
  {to_date} AS dt,
  CAST(({epoch_max} - {epoch_min}) * 1000 AS BIGINT) AS duration_ms,
  CASE WHEN activity_type = 'playlist' THEN NULL
       ELSE count(DISTINCT CASE WHEN event_name = 'playback_play' THEN track_id END)
  END AS tracks_listened,
  CASE WHEN activity_type = 'playlist' THEN NULL
       ELSE sum({_PROMOTED_CONTRIB})
  END AS tracks_promoted,
  CASE WHEN activity_type = 'playlist' THEN NULL
       ELSE sum({_DELETED_CONTRIB})
  END AS tracks_deleted
FROM sessioned
GROUP BY user_id, activity_type, session_seq
"""


def mart_sql(d: Mapping[str, str], *, source: str = "bronze_events") -> str:
    """SQL selecting one row per (user_id, dt, activity_type) — mart_user_daily grain."""
    epoch_ts = d["epoch"].format("ts")
    epoch_max = d["epoch"].format("max(ts)")
    epoch_min = d["epoch"].format("min(ts)")
    to_date_min = d["to_date"].format("min(ts)")
    # FIRST_VALUE gives each sessioned row its session's start date.
    first_ts_expr = "FIRST_VALUE(ts) OVER (PARTITION BY user_id, activity_type, session_seq ORDER BY ts)"
    to_date_first = d["to_date"].format(first_ts_expr)
    # lead over ALL events in the session → wall-clock gap to next event.
    lead_epoch = f"lead({epoch_ts}) OVER (PARTITION BY user_id, activity_type, session_seq ORDER BY ts)"
    pctl50_dur = d["pctl"].format("fs.duration_ms", "0.5")
    pctl90_dur = d["pctl"].format("fs.duration_ms", "0.9")
    pctl50_t = d["pctl"].format("t_ms", "0.5")
    pctl90_t = d["pctl"].format("t_ms", "0.9")
    return f"""
WITH {_sessioned_cte(d, source)},
sessioned_with_dt AS (
  SELECT *,
    {to_date_first} AS dt
  FROM sessioned
),
fs AS (
  SELECT
    user_id, activity_type, session_seq, dt,
    CAST(({epoch_max} - {epoch_min}) * 1000 AS BIGINT) AS duration_ms,
    CASE WHEN activity_type = 'playlist' THEN NULL
         ELSE count(DISTINCT CASE WHEN event_name = 'playback_play' THEN track_id END)
    END AS tracks_listened,
    CASE WHEN activity_type = 'playlist' THEN NULL
         ELSE sum({_PROMOTED_CONTRIB})
    END AS tracks_promoted,
    CASE WHEN activity_type = 'playlist' THEN NULL
         ELSE sum({_DELETED_CONTRIB})
    END AS tracks_deleted
  FROM sessioned_with_dt
  GROUP BY user_id, activity_type, session_seq, dt
),
play_gap AS (
  SELECT
    user_id, activity_type, session_seq, dt, event_name,
    ({lead_epoch} - {epoch_ts}) * 1000 AS gap_ms
  FROM sessioned_with_dt
),
time_rows AS (
  SELECT user_id, dt, activity_type, CAST(decision_ms AS DOUBLE) AS t_ms
  FROM sessioned_with_dt
  WHERE activity_type = 'triage'
    AND event_name = 'track_categorized'
    AND decision_ms IS NOT NULL
  UNION ALL
  SELECT user_id, dt, activity_type, gap_ms AS t_ms
  FROM play_gap
  WHERE activity_type IN ('category', 'playlist')
    AND event_name = 'playback_play'
    AND gap_ms IS NOT NULL
),
daily_time AS (
  SELECT user_id, dt, activity_type,
    {pctl50_t} AS p50_time_per_track_ms,
    {pctl90_t} AS p90_time_per_track_ms
  FROM time_rows
  GROUP BY user_id, dt, activity_type
)
SELECT
  fs.user_id,
  fs.dt,
  fs.activity_type,
  count(*) AS sessions,
  avg(fs.tracks_listened)  AS avg_tracks_listened,
  avg(fs.tracks_promoted)  AS avg_tracks_promoted,
  avg(fs.tracks_deleted)   AS avg_tracks_deleted,
  {pctl50_dur} AS p50_duration_ms,
  {pctl90_dur} AS p90_duration_ms,
  max(dt2.p50_time_per_track_ms) AS p50_time_per_track_ms,
  max(dt2.p90_time_per_track_ms) AS p90_time_per_track_ms
FROM fs
LEFT JOIN daily_time dt2
  ON dt2.user_id = fs.user_id
 AND dt2.dt = fs.dt
 AND dt2.activity_type = fs.activity_type
GROUP BY fs.user_id, fs.dt, fs.activity_type
"""

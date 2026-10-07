{{ config(materialized='table', table_type='iceberg', format='parquet') }}

{#- Same rule as collector/analytics_handler.py:_plays_cte; 10-minute fallback
    for unknown durations (_FALLBACK_TRACK_MS). -#}
{%- set fallback_ms = 600000 -%}

with ev as (
    select
        user_id, event_id, event_name, track_id, source,
        ts_client_utc as ts,
        cast(coalesce(nullif(duration_ms, 0), {{ fallback_ms }}) as double) as dur_ms
    from {{ ref('events') }}
    where event_name in ('playback_play', 'playback_pause', 'playback_resume', 'playback_ended')
),

seq as (
    select
        *,
        sum(case when event_name = 'playback_play' then 1 else 0 end) over (
            partition by user_id order by ts, event_id
            rows between unbounded preceding and current row
        ) as play_no,
        date_diff('millisecond', ts, lead(ts) over (partition by user_id order by ts, event_id)) as gap_ms
    from ev
),

per_play as (
    select
        user_id,
        play_no,
        max(case when event_name = 'playback_play' then event_id end) as play_event_id,
        max(case when event_name = 'playback_play' then track_id end) as track_id,
        max(case when event_name = 'playback_play' then source end) as stage,
        max(case when event_name = 'playback_play' then dur_ms end) as dur_ms,
        min(case when event_name = 'playback_play' then ts end) as played_at,
        sum(case when event_name in ('playback_play', 'playback_resume')
                 then coalesce(cast(gap_ms as double), dur_ms) else 0 end) as played_ms
    from seq
    where play_no > 0
    group by user_id, play_no
),

plays as (
    select
        play_event_id, user_id, track_id, stage, played_at,
        cast(played_at as date) as played_on,
        cast(least(played_ms, dur_ms) as bigint) as ms
    from per_play
),

versions as (
    select
        track_id, style_id, valid_from, valid_to,
        row_number() over (partition by track_id order by valid_from) = 1 as is_first
    from {{ ref('dim_track_history') }}
)

select
    p.play_event_id, p.user_id, p.track_id, p.stage, p.played_at, p.played_on, p.ms,
    v.style_id
from plays p
left join versions v
    on v.track_id = p.track_id
   and (v.is_first or v.valid_from <= p.played_on)
   and (v.valid_to is null or p.played_on < v.valid_to)

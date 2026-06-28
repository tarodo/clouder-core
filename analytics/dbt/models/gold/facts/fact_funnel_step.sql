with viewed as (
    select user_id, track_id, ts_server, 'viewed' as step
    from {{ ref('stg_track_view') }}
),
categorized as (
    select user_id, track_id, ts_server, 'categorized' as step
    from {{ ref('stg_track_categorized') }}
    where action in ('moved_to_bucket', 'categorized_curate')
),
playlisted as (
    select p.user_id, tid as track_id, p.ts_server, 'playlisted' as step
    from {{ ref('stg_playlist') }} p
    cross join unnest(p.track_ids) as t (tid)
    where p.event_name = 'playlist_add'
),
published as (
    select p.user_id, tid as track_id, p.ts_server, 'published' as step
    from {{ ref('stg_playlist') }} p
    cross join unnest(p.track_ids) as t (tid)
    where p.event_name = 'playlist_publish'
),
ingested_latest as (
    select max(snapshot_dt) as snapshot_dt
    from {{ source('clouder_analytics', 'bronze_catalog_export') }}
    where tbl = 'clouder_tracks'
),
ingested as (
    select
        cast(null as varchar) as user_id,
        c.id as track_id,
        date_format(coalesce(try_cast(c.created_at as timestamp),
                             from_iso8601_timestamp(c.created_at)), '%Y-%m-%dT%H:%i:%sZ') as ts_server,
        'ingested' as step
    from {{ source('clouder_analytics', 'bronze_catalog_export') }} c
    cross join ingested_latest l
    where c.tbl = 'clouder_tracks' and c.snapshot_dt = l.snapshot_dt and c.created_at is not null
),
all_steps as (
    select * from ingested
    union all select * from viewed
    union all select * from categorized
    union all select * from playlisted
    union all select * from published
),
keyed as (
    select
        {{ surrogate_key(['user_id']) }} as user_key,
        {{ surrogate_key(['track_id']) }} as track_key,
        step,
        -- from_iso8601_timestamp returns timestamp(3) WITH TIME ZONE, which a
        -- Hive/Parquet CTAS rejects ("Unsupported Hive type"). Drop the zone.
        cast(from_iso8601_timestamp(ts_server) as timestamp(3)) as ts
    from all_steps
),
windowed as (
    select *,
        lag(ts)   over (partition by track_key order by ts) as prev_ts,
        lag(step) over (partition by track_key order by ts) as prev_step
    from keyed
)
select
    {{ surrogate_key(['user_key', 'track_key', 'step', 'ts']) }} as funnel_key,
    user_key,
    track_key,
    cast(date_format(ts, '%Y%m%d') as integer) as date_key,
    step,
    ts,
    prev_step,
    date_diff('millisecond', prev_ts, ts) as ms_since_prev,
    date_format(ts, '%Y-%m-%d') as dt
from windowed
{% if is_incremental() %}
where date_format(ts, '%Y-%m-%d') >= date_format(date_add('day', -{{ var('lookback_days') }}, current_date), '%Y-%m-%d')
{% endif %}

with src as (
    select
        event_id,
        event_name,
        session_id,
        ts_server,
        json_extract_scalar(context, '$.user_id') as user_id,
        json_extract_scalar(props, '$.track_id') as track_id,
        json_extract_scalar(props, '$.source') as source,
        try_cast(json_extract_scalar(props, '$.position_ms') as bigint) as position_ms,
        try_cast(json_extract_scalar(props, '$.duration_ms') as bigint) as duration_ms,
        try_cast(json_extract_scalar(props, '$.listen_through_ratio') as double) as listen_through_ratio,
        try_cast(json_extract_scalar(props, '$.seek_count') as bigint) as seek_count,
        dt
    from {{ source('clouder_analytics', 'bronze_events') }}
    where event_name in ('playback_play', 'playback_pause', 'playback_ended', 'playback_skip')
    {% if is_incremental() %}
    and dt >= date_format(date_add('day', -{{ var('lookback_days') }}, current_date), '%Y-%m-%d')
    {% endif %}
),
deduped as (
    select *, row_number() over (partition by event_id order by ts_server) as rn from src
)
select event_id, event_name, session_id, ts_server, user_id, track_id, source,
       position_ms, duration_ms, listen_through_ratio, seek_count, dt
from deduped where rn = 1

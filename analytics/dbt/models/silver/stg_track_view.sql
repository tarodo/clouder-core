with src as (
    select
        event_id,
        session_id,
        ts_server,
        json_extract_scalar(context, '$.user_id') as user_id,
        json_extract_scalar(props, '$.track_id') as track_id,
        try_cast(json_extract_scalar(props, '$.dwell_ms') as bigint) as dwell_ms,
        dt
    from {{ source('clouder_analytics', 'bronze_events') }}
    where event_name = 'track_view'
    {% if is_incremental() %}
    and dt >= date_format(date_add('day', -{{ var('lookback_days') }}, current_date), '%Y-%m-%d')
    {% endif %}
),
deduped as (
    select *, row_number() over (partition by event_id order by ts_server) as rn from src
)
select event_id, session_id, ts_server, user_id, track_id, dwell_ms, dt
from deduped where rn = 1

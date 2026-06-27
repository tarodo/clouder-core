with src as (
    select
        event_id,
        event_name,
        session_id,
        ts_server,
        json_extract_scalar(context, '$.user_id') as user_id,
        json_extract_scalar(props, '$.playlist_id') as playlist_id,
        cast(json_extract(props, '$.track_ids') as array(varchar)) as track_ids,
        try_cast(json_extract_scalar(props, '$.track_count') as bigint) as track_count,
        json_extract_scalar(props, '$.target') as target,
        dt
    from {{ source('clouder_analytics', 'bronze_events') }}
    where event_name in ('playlist_add', 'playlist_reorder', 'playlist_publish')
    {% if is_incremental() %}
    and dt >= date_format(date_add('day', -{{ var('lookback_days') }}, current_date), '%Y-%m-%d')
    {% endif %}
),
deduped as (
    select *, row_number() over (partition by event_id order by ts_server) as rn from src
)
select event_id, event_name, session_id, ts_server, user_id, playlist_id,
       track_ids, track_count, target, dt
from deduped where rn = 1

with ev as (
    select
        event_id, event_name, session_id, ts_server,
        json_extract_scalar(context, '$.user_id') as user_id,
        json_extract_scalar(props, '$.block_id') as block_id,
        json_extract_scalar(props, '$.bucket_id') as bucket_id,
        try_cast(json_extract_scalar(props, '$.session_ms') as bigint) as session_ms,
        try_cast(json_extract_scalar(props, '$.tracks_seen') as bigint) as tracks_seen,
        try_cast(json_extract_scalar(props, '$.tracks_categorized') as bigint) as tracks_categorized,
        try_cast(json_extract_scalar(props, '$.undo_rate') as double) as undo_rate,
        dt
    from {{ source('clouder_analytics', 'bronze_events') }}
    where event_name in ('triage_session_start', 'triage_session_end')
    {% if is_incremental() %}
    and dt >= date_format(date_add('day', -{{ var('lookback_days') }}, current_date), '%Y-%m-%d')
    {% endif %}
),
deduped as (
    select *, row_number() over (partition by event_id order by ts_server) as rn from ev
),
starts as (
    select session_id, user_id, block_id, bucket_id, ts_server as ts_start
    from deduped where rn = 1 and event_name = 'triage_session_start'
),
ends as (
    select session_id, ts_server as ts_end, session_ms, tracks_seen,
           tracks_categorized, undo_rate, dt
    from deduped where rn = 1 and event_name = 'triage_session_end'
)
select
    e.session_id, s.user_id, s.block_id, s.bucket_id,
    s.ts_start, e.ts_end, e.session_ms, e.tracks_seen, e.tracks_categorized,
    e.undo_rate, e.dt
from ends e
left join starts s on s.session_id = e.session_id

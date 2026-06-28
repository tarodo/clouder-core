select
    {{ surrogate_key(['event_id']) }} as seek_key,
    event_id,
    {{ surrogate_key(['user_id']) }} as user_key,
    {{ surrogate_key(['track_id']) }} as track_key,
    cast(date_format(from_iso8601_timestamp(ts_server), '%Y%m%d') as integer) as date_key,
    from_position_ms,
    to_position_ms,
    ts_server,
    date_format(from_iso8601_timestamp(ts_server), '%Y-%m-%d') as dt
from {{ ref('stg_playback_seek') }}
{% if is_incremental() %}
where dt >= date_format(date_add('day', -{{ var('lookback_days') }}, current_date), '%Y-%m-%d')
{% endif %}

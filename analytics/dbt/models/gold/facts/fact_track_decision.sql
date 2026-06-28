select
    {{ surrogate_key(['event_id']) }} as decision_key,
    event_id,
    {{ surrogate_key(['user_id']) }} as user_key,
    {{ surrogate_key(['track_id']) }} as track_key,
    category_key,  -- degenerate dimension (bucket_type string), NOT a dim_category FK
    cast(date_format(from_iso8601_timestamp(ts_server), '%Y%m%d') as integer) as date_key,
    decision_ms,
    cast(null as bigint) as dwell_ms,  -- ponytail: dwell lives on track_view in P1 (§7)
    action,
    surface,
    ts_server,
    date_format(from_iso8601_timestamp(ts_server), '%Y-%m-%d') as dt
from {{ ref('stg_track_categorized') }}
{% if is_incremental() %}
where dt >= date_format(date_add('day', -{{ var('lookback_days') }}, current_date), '%Y-%m-%d')
{% endif %}

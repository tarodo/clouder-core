with undos as (
    select session_id, count(*) as undo_count
    from {{ ref('stg_track_categorized') }}
    where action = 'undo' and surface = 'triage'
    group by session_id
)
select
    {{ surrogate_key(['s.session_id']) }} as session_key,
    s.session_id,
    {{ surrogate_key(['s.user_id']) }} as user_key,
    s.block_id,
    s.bucket_id,
    cast(date_format(from_iso8601_timestamp(s.ts_end), '%Y%m%d') as integer) as date_key,
    s.session_ms,
    s.tracks_seen,
    s.tracks_categorized,
    coalesce(u.undo_count, 0) as undo_count,
    s.undo_rate,
    s.ts_start,
    s.ts_end,
    s.dt
from {{ ref('stg_triage_session') }} s
left join undos u on u.session_id = s.session_id
{% if is_incremental() %}
where s.dt >= date_format(date_add('day', -{{ var('lookback_days') }}, current_date), '%Y-%m-%d')
{% endif %}

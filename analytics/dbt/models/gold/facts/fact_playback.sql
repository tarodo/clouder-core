-- One play = one playback_play matched to its terminal (pause/end/skip) within
-- (session_id, track_id). Grouping by a running playback_play count: LOCAL resume
-- via togglePlayPause emits a new playback_play only when queue transitions from
-- idle/ended (play() call); normal local pause->resume uses playerRef.togglePlay()
-- which does NOT re-emit playback_play (same group). REMOTE resume (spotifyApi.resume)
-- also does NOT re-emit playback_play (same group, terminal resolves to later end/skip).
-- See PlaybackProvider.tsx recon: togglePlayPause L435-L462.
--
-- Incremental note: stg_playback is read in full to handle cross-day grouping
-- (a play event and its terminal may land on different calendar dates). The
-- is_incremental() filter is applied only on the FINAL output dt column to
-- avoid the HIVE_TOO_MANY_OPEN_PARTITIONS limit (>~100 days of partitions).
with pb as (
    select * from {{ ref('stg_playback') }}
),
grouped as (
    select *,
        sum(case when event_name = 'playback_play' then 1 else 0 end)
            over (partition by session_id, track_id order by ts_server
                  rows between unbounded preceding and current row) as play_group
    from pb
),
plays as (
    select session_id, track_id, play_group,
           max(user_id) as user_id,
           max(case when event_name = 'playback_play' then source end) as source,
           max(case when event_name = 'playback_play' then duration_ms end) as duration_ms,
           min(case when event_name = 'playback_play' then ts_server end) as play_ts
    from grouped
    group by session_id, track_id, play_group
),
terminals as (
    select session_id, track_id, play_group, event_name, ts_server,
           position_ms, listen_through_ratio,
           row_number() over (
               partition by session_id, track_id, play_group
               order by case when event_name in ('playback_ended', 'playback_skip') then 0 else 1 end,
                        ts_server desc
           ) as rn
    from grouped
    where event_name <> 'playback_play'
),
seeks as (
    select session_id, track_id, count(*) as seek_count
    from {{ ref('stg_playback_seek') }}
    group by session_id, track_id
),
joined as (
    select
        p.session_id, p.track_id, p.play_group, p.user_id, p.source, p.duration_ms, p.play_ts,
        t.event_name as terminal, t.position_ms, t.listen_through_ratio, t.ts_server as terminal_ts,
        coalesce(s.seek_count, 0) as seek_count
    from plays p
    join terminals t
      on t.session_id = p.session_id and t.track_id = p.track_id
     and t.play_group = p.play_group and t.rn = 1
    left join seeks s on s.session_id = p.session_id and s.track_id = p.track_id
)
select
    {{ surrogate_key(['session_id', 'track_id', 'play_group']) }} as playback_key,
    {{ surrogate_key(['session_id', 'track_id', 'play_group']) }} as event_id,
    {{ surrogate_key(['user_id']) }} as user_key,
    {{ surrogate_key(['track_id']) }} as track_key,
    cast(date_format(from_iso8601_timestamp(terminal_ts), '%Y%m%d') as integer) as date_key,
    source,
    coalesce(position_ms, cast(listen_through_ratio * duration_ms as bigint)) as played_ms,
    duration_ms,
    coalesce(
        listen_through_ratio,
        try(cast(coalesce(position_ms, 0) as double) / nullif(duration_ms, 0))
    ) as listen_through_ratio,
    seek_count,
    terminal = 'playback_skip' as skipped,
    terminal_ts as ts_server,
    date_format(from_iso8601_timestamp(terminal_ts), '%Y-%m-%d') as dt
from joined
{% if is_incremental() %}
where date_format(from_iso8601_timestamp(terminal_ts), '%Y-%m-%d') >= date_format(date_add('day', -{{ var('lookback_days') }}, current_date), '%Y-%m-%d')
{% endif %}

with latest as (
    select max(snapshot_dt) as snapshot_dt
    from {{ source('clouder_analytics', 'bronze_catalog_export') }}
    where tbl = 'clouder_tracks'
),
albums as (
    -- album_id -> label_id: clouder_tracks has no direct label, the chain is
    -- track.album_id -> album.label_id -> label.id, so dim_track can carry label_key.
    select a.id as album_id, a.label_id
    from {{ source('clouder_analytics', 'bronze_catalog_export') }} a
    cross join latest l
    where a.tbl = 'clouder_albums' and a.snapshot_dt = l.snapshot_dt
),
src as (
    select id, title, bpm, key_name, key_camelot, style_id,
           spotify_release_date, publish_date, album_id, isrc,
           release_type, is_ai_suspected, origin
    from {{ source('clouder_analytics', 'bronze_catalog_export') }} c
    cross join latest l
    where c.tbl = 'clouder_tracks' and c.snapshot_dt = l.snapshot_dt
)
select
    {{ surrogate_key(['s.id']) }} as track_key,
    s.id as track_id,
    s.title,
    try_cast(s.bpm as integer) as bpm,
    s.key_name,
    s.key_camelot,
    s.style_id,
    coalesce(try_cast(s.spotify_release_date as date), try_cast(s.publish_date as date)) as release_date,
    s.album_id,
    -- matches dim_label.label_key = surrogate_key(['id']) since album.label_id == label.id
    {{ surrogate_key(['al.label_id']) }} as label_key,
    s.isrc,
    s.release_type,
    cast(s.is_ai_suspected as boolean) as is_ai_suspected,
    s.origin
from src s
left join albums al on al.album_id = s.album_id

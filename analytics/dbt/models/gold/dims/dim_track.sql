with latest as (
    select max(snapshot_dt) as snapshot_dt
    from {{ source('clouder_analytics', 'bronze_catalog_export') }}
    where tbl = 'clouder_tracks'
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
    {{ surrogate_key(['id']) }} as track_key,
    id as track_id,
    title,
    try_cast(bpm as integer) as bpm,
    key_name,
    key_camelot,
    style_id,
    coalesce(try_cast(spotify_release_date as date), try_cast(publish_date as date)) as release_date,
    album_id,
    isrc,
    release_type,
    cast(is_ai_suspected as boolean) as is_ai_suspected,
    origin
from src

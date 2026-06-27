with latest as (
    select max(snapshot_dt) as snapshot_dt
    from {{ source('clouder_analytics', 'bronze_catalog_export') }}
    where tbl = 'clouder_track_artists'
),
src as (
    select track_id, artist_id, role
    from {{ source('clouder_analytics', 'bronze_catalog_export') }} c
    cross join latest l
    where c.tbl = 'clouder_track_artists' and c.snapshot_dt = l.snapshot_dt
)
select
    {{ surrogate_key(['track_id']) }} as track_key,
    {{ surrogate_key(['artist_id']) }} as artist_key,
    role
from src

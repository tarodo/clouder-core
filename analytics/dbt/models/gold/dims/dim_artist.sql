with latest as (
    select max(snapshot_dt) as snapshot_dt
    from {{ source('clouder_analytics', 'bronze_catalog_export') }}
    where tbl = 'clouder_artists'
),
src as (
    select id, name, normalized_name, is_ai_suspected
    from {{ source('clouder_analytics', 'bronze_catalog_export') }} c
    cross join latest l
    where c.tbl = 'clouder_artists' and c.snapshot_dt = l.snapshot_dt
)
select
    {{ surrogate_key(['id']) }} as artist_key,
    id as artist_id,
    name,
    normalized_name,
    cast(is_ai_suspected as boolean) as is_ai_suspected
from src

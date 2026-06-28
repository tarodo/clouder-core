with latest as (
    select max(snapshot_dt) as snapshot_dt
    from {{ source('clouder_analytics', 'bronze_catalog_export') }}
    where tbl = 'clouder_labels'
),
src as (
    select id, name, normalized_name
    from {{ source('clouder_analytics', 'bronze_catalog_export') }} c
    cross join latest l
    where c.tbl = 'clouder_labels' and c.snapshot_dt = l.snapshot_dt
)
select
    {{ surrogate_key(['id']) }} as label_key,
    id as label_id,
    name,
    normalized_name
from src

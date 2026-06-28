-- ponytail: dim_category.category_key (surrogate) and fact_track_decision.category_key
-- (degenerate bucket-type string, §7) share a name but not a domain — no relationships
-- test joins them. category_tracks membership bridge is unmodeled until a dashboard needs it.
with latest as (
    select max(snapshot_dt) as snapshot_dt
    from {{ source('clouder_analytics', 'bronze_catalog_export') }}
    where tbl = 'categories'
),
src as (
    select id, user_id, style_id, name, normalized_name, position, deleted_at
    from {{ source('clouder_analytics', 'bronze_catalog_export') }} c
    cross join latest l
    where c.tbl = 'categories' and c.snapshot_dt = l.snapshot_dt
)
select
    {{ surrogate_key(['id']) }} as category_key,
    id as category_id,
    user_id,
    style_id,
    name,
    normalized_name,
    try_cast(position as integer) as position,
    deleted_at
from src

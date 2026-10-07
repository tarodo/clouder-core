{{ config(
    materialized='incremental',
    unique_key=['track_id', 'valid_from'],
    incremental_strategy=('merge' if target.type == 'athena' else 'delete+insert'),
    table_type='iceberg',
    format='parquet',
) }}

{%- set tracked = ['title', 'bpm', 'key_camelot', 'publish_date', 'album_id', 'style_id',
                   'isrc', 'release_type', 'is_ai_suspected', 'spotify_release_date'] -%}
{%- set parts = [] -%}
{%- for c in tracked -%}
    {%- do parts.append("coalesce(cast(" ~ c ~ " as varchar), '~')") -%}
{%- endfor -%}

with snapshots as (
    select
        cast(snapshot_dt as date) as observed_on,
        id as track_id,
        {{ tracked | join(', ') }}
    from {{ source('bronze', 'catalog_export') }}
    where tbl = 'clouder_tracks'
      and id is not null
    {% if is_incremental() %}
      -- Every retained snapshot after the latest version: a missed night catches up.
      and cast(snapshot_dt as date) > (select max(valid_from) from {{ this }})
    {% endif %}
),

observed as (
    select
        observed_on, track_id, {{ tracked | join(', ') }},
        {{ hash_text("concat_ws('|', " ~ parts | join(', ') ~ ")") }} as row_hash
    from snapshots
    {% if is_incremental() %}
    union all
    -- Current versions take part so a change closes them and a repeat is a no-op.
    select valid_from as observed_on, track_id, {{ tracked | join(', ') }}, row_hash
    from {{ this }}
    where valid_to is null
    {% endif %}
),

changes as (
    select
        *,
        lag(row_hash) over (partition by track_id order by observed_on) as prev_hash
    from observed
),

versions as (
    select * from changes
    where prev_hash is null or prev_hash <> row_hash
)

select
    track_id,
    observed_on as valid_from,
    lead(observed_on) over (partition by track_id order by observed_on) as valid_to,
    {{ tracked | join(', ') }},
    row_hash
from versions

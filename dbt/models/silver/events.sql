{{ config(
    materialized='incremental',
    unique_key='event_id',
    incremental_strategy=('merge' if target.type == 'athena' else 'delete+insert'),
    table_type='iceberg',
    format='parquet',
    partitioned_by=['dt'],
    on_schema_change='append_new_columns',
    post_hook=([
        "optimize {{ this.render_pure() }} rewrite data using bin_pack",
        "vacuum {{ this.render_pure() }}",
    ] if target.type == 'athena' else []),
) }}

with source_rows as (
    select * from {{ ref('stg_events') }}
    {% if is_incremental() %}
    -- Late arrivals and Firehose redeliveries land in recent partitions; the
    -- MERGE on event_id makes re-reading them idempotent.
    where dt >= (select {{ dt_minus_days('max(dt)', var('events_lookback_days')) }} from {{ this }})
    {% endif %}
),

ranked as (
    select
        *,
        row_number() over (
            partition by event_id
            order by ts_server_utc, ts_client_utc
        ) as copy_no
    from source_rows
)

select
    event_id, session_id, user_id, event_name, track_id, source, duration_ms,
    ts_client, ts_client_utc, ts_server_utc, dt
from ranked
where copy_no = 1

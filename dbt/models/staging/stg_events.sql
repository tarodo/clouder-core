-- Typed view over bronze events; the raw ts_client string is kept for the
-- analytics Lambda's hot/cold union (it parses it itself). Deleted users
-- (docs/privacy.md) are dropped here, so silver and gold never rebuild them.
select
    event_id,
    session_id,
    user_id,
    event_name,
    track_id,
    source,
    cast(duration_ms as bigint) as duration_ms,
    ts_client,
    {{ parse_utc_ts('ts_client') }} as ts_client_utc,
    {{ parse_utc_ts('ts_server') }} as ts_server_utc,
    dt
from {{ source('bronze', 'events') }} e
where event_id is not null
  and not exists (
      select 1 from {{ source('governance', 'deleted_users') }} d where d.user_id = e.user_id
  )

-- No silver event is older than the retention window (docs/privacy.md).
select e.event_id
from {{ ref('events') }} e
cross join (select max(dt) as newest from {{ ref('events') }}) m
where e.dt < {{ dt_minus_days('m.newest', var('events_retention_days')) }}

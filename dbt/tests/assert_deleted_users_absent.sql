-- A user deleted by scripts/delete_user.py (docs/privacy.md) has no rows in
-- silver or gold, even after a full refresh re-reads bronze.
with gone as (select user_id from {{ source('governance', 'deleted_users') }})
select 'events' as tbl, e.user_id from {{ ref('events') }} e where e.user_id in (select user_id from gone)
union all
select 'fct_play' as tbl, p.user_id from {{ ref('fct_play') }} p where p.user_id in (select user_id from gone)

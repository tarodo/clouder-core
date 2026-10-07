-- A track has exactly one current version.
select track_id
from {{ ref('dim_track_history') }}
where valid_to is null
group by track_id
having count(*) > 1

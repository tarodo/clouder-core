-- Closed versions end after they start; a track's versions never overlap.
select track_id, valid_from, valid_to
from (
    select
        track_id, valid_from, valid_to,
        lead(valid_from) over (partition by track_id order by valid_from) as next_from
    from {{ ref('dim_track_history') }}
) v
where (valid_to is not null and valid_to <= valid_from)
   or (next_from is not null and (valid_to is null or valid_to <> next_from))

with ids as (
    select user_id from {{ ref('stg_track_categorized') }} where user_id is not null
    union
    select user_id from {{ ref('stg_track_view') }} where user_id is not null
    union
    select user_id from {{ ref('stg_triage_session') }} where user_id is not null
    union
    select user_id from {{ ref('stg_playback') }} where user_id is not null
    union
    select user_id from {{ ref('stg_playback_seek') }} where user_id is not null
    union
    select user_id from {{ ref('stg_playlist') }} where user_id is not null
)
select {{ surrogate_key(['user_id']) }} as user_key, user_id
from (select distinct user_id from ids)

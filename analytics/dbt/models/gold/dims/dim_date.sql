with spine as (
    select d as date
    from unnest(sequence(date '2024-01-01', date '2031-12-31', interval '1' day)) as t (d)
),
sat as (
    select date, {{ last_saturday_on_or_before('date') }} as saturday from spine
),
computed as (
    select
        date,
        saturday,
        year(saturday) as sat_year,
        {{ first_saturday('year(saturday)') }} as fs_curr,
        {{ first_saturday('year(saturday) - 1') }} as fs_prev
    from sat
)
select
    cast(date_format(date, '%Y%m%d') as integer) as date_key,
    date,
    case when saturday < fs_curr then sat_year - 1 else sat_year end as saturday_week_year,
    case
        when saturday < fs_curr then (date_diff('day', fs_prev, saturday) / 7) + 1
        else (date_diff('day', fs_curr, saturday) / 7) + 1
    end as saturday_week_number,
    year(date_add('day', 4 - day_of_week(date), date)) as iso_week_year,
    week(date) as iso_week_number,
    day_of_week(date) as day_of_week,
    month(date) as month,
    quarter(date) as quarter,
    year(date) as year
from computed

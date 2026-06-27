-- Live contract pin: known Saturday-week boundaries (mirrors saturday_week.py).
with expected (date, saturday_week_year, saturday_week_number) as (
    values
        (date '2026-01-02', 2025, 52),  -- Fri before first Saturday -> prev year (2025 w52)
        (date '2026-01-03', 2026, 1),   -- first Saturday on/after Jan 1
        (date '2026-01-09', 2026, 1),   -- Friday of week 1
        (date '2026-01-10', 2026, 2),
        (date '2022-01-01', 2022, 1)    -- Jan 1 is itself a Saturday
)
select e.date
from expected e
join {{ ref('dim_date') }} d on d.date = e.date
where d.saturday_week_year <> e.saturday_week_year
   or d.saturday_week_number <> e.saturday_week_number

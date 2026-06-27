{% macro last_saturday_on_or_before(d) -%}
date_add('day', -(((day_of_week({{ d }}) - 6) % 7 + 7) % 7), {{ d }})
{%- endmacro %}

{% macro first_saturday(year_expr) -%}
date_add(
  'day',
  ((6 - day_of_week(cast(concat(cast({{ year_expr }} as varchar), '-01-01') as date))) % 7 + 7) % 7,
  cast(concat(cast({{ year_expr }} as varchar), '-01-01') as date)
)
{%- endmacro %}

{#- The few SQL fragments that differ between Athena (Trino) in prod and DuckDB in CI. -#}

{% macro parse_utc_ts(col) %}{{ return(adapter.dispatch('parse_utc_ts', 'clouder')(col)) }}{% endmacro %}
{#- NULL for a malformed string: one bad client clock must not stop the nightly build.
    Plain `timestamp`: Athena stores views as Hive views, and Hive has no timestamp(6). -#}
{% macro athena__parse_utc_ts(col) %}cast(try(from_iso8601_timestamp({{ col }})) at time zone 'UTC' as timestamp){% endmacro %}
{% macro default__parse_utc_ts(col) %}(try_cast({{ col }} as timestamptz) at time zone 'UTC'){% endmacro %}

{% macro dt_minus_days(expr, days) %}{{ return(adapter.dispatch('dt_minus_days', 'clouder')(expr, days)) }}{% endmacro %}
{% macro athena__dt_minus_days(expr, days) %}cast(date_add('day', -{{ days }}, cast({{ expr }} as date)) as varchar){% endmacro %}
{% macro default__dt_minus_days(expr, days) %}cast(cast({{ expr }} as date) - {{ days }} as varchar){% endmacro %}

{% macro hash_text(expr) %}{{ return(adapter.dispatch('hash_text', 'clouder')(expr)) }}{% endmacro %}
{% macro athena__hash_text(expr) %}lower(to_hex(md5(to_utf8({{ expr }})))){% endmacro %}
{% macro default__hash_text(expr) %}md5({{ expr }}){% endmacro %}

{#- Iceberg tables on Athena take microsecond timestamps only. -#}
{% macro iceberg_ts(col) %}{{ return(adapter.dispatch('iceberg_ts', 'clouder')(col)) }}{% endmacro %}
{% macro athena__iceberg_ts(col) %}cast({{ col }} as timestamp(6)){% endmacro %}
{% macro default__iceberg_ts(col) %}{{ col }}{% endmacro %}

{#- Deletes silver partitions older than the retention window, counted back from the
    newest partition (in production that is today; in CI it is the newest fixture, so
    fixtures never age out). An empty table deletes nothing. The cutoff is an inlined
    date literal: Athena mis-parses bound 'YYYY-MM-DD' parameters. -#}
{% macro delete_expired_events() %}
  {%- if execute -%}
    {%- set rel = this.render_pure() if target.type == 'athena' else this -%}
    {%- set newest = run_query("select max(dt) from " ~ rel).columns[0].values()[0] -%}
    {%- if newest -%}
      {%- set cutoff = (modules.datetime.date.fromisoformat(newest | string) - modules.datetime.timedelta(days=var('events_retention_days'))).isoformat() -%}
      delete from {{ rel }} where dt < '{{ cutoff }}'
    {%- else -%}
      select 1
    {%- endif -%}
  {%- else -%}
    select 1
  {%- endif -%}
{% endmacro %}

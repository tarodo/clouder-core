{% macro surrogate_key(cols) -%}
to_hex(md5(to_utf8(concat_ws('||'
  {%- for c in cols %}, coalesce(cast({{ c }} as varchar), '__NULL__'){% endfor -%}
))))
{%- endmacro %}

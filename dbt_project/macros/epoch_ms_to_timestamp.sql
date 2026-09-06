{% macro epoch_ms_to_timestamp(column_name) %}
    timestamp_millis({{ column_name }})
{% endmacro %}
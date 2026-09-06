{#
    By default dbt prefixes custom schemas with the target schema, so
    +schema: silver would become silver_silver. This override makes the
    custom schema name the final name, which is what the setup DDL and
    the ERD assume.
#}

{% macro generate_schema_name(custom_schema_name, node) -%}

    {%- set default_schema = target.schema -%}

    {%- if custom_schema_name is none -%}
        {{ default_schema }}
    {%- else -%}
        {{ custom_schema_name | trim }}
    {%- endif -%}

{%- endmacro %}

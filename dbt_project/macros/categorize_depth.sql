{% macro categorize_depth(column_name) %}
    case
        when {{ column_name }} < 70 then 'Shallow'
        when {{ column_name }} <= 300 then 'Intermediate'
        else 'Deep'
    end
{% endmacro %}
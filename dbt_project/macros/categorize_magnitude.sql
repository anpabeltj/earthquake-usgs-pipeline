{% macro categorize_magnitude(column_name) %}
    case
        when {{ column_name }} < 4.0 then 'Minor'
        when {{ column_name }} < 5.0 then 'Light'
        when {{ column_name }} < 6.0 then 'Moderate'
        when {{ column_name }} < 7.0 then 'Strong'
        else 'Major'
    end
{% endmacro %}
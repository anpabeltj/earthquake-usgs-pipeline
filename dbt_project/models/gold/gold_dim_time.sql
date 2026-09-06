/*
    Time dimension, one row per distinct event timestamp.

    With 26 years of history the year and month columns matter: most
    dashboard questions are answered by grouping on those rather than on
    the raw timestamp.
*/

with cleaned as (

    select distinct event_time
    from {{ ref('silver_usgs_cleaned') }}

)

select
    {{ dbt_utils.generate_surrogate_key(['event_time']) }} as time_id,
    date(event_time) as date,
    extract(hour from event_time) as hour,
    format_date('%A', date(event_time)) as day_name,
    extract(month from event_time) as month,
    extract(year from event_time) as year
from cleaned

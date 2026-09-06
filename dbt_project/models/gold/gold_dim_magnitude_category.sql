/*
    Magnitude bands, listed explicitly so every band exists as a filter
    option even before an earthquake of that size has been recorded.
    Values match the case expression in silver_usgs_category.
*/

with categories as (

    select 'Minor'    as magnitude_category union all
    select 'Light'    union all
    select 'Moderate' union all
    select 'Strong'   union all
    select 'Major'

)

select
    {{ dbt_utils.generate_surrogate_key(['magnitude_category']) }} as magnitude_category_id,
    magnitude_category
from categories

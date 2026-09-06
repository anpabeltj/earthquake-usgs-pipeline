/*
    Depth bands, listed explicitly for the same reason as the magnitude
    dimension, and matching silver_usgs_category.
*/

with categories as (

    select 'Shallow'      as depth_category union all
    select 'Intermediate' union all
    select 'Deep'

)

select
    {{ dbt_utils.generate_surrogate_key(['depth_category']) }} as depth_category_id,
    depth_category
from categories
